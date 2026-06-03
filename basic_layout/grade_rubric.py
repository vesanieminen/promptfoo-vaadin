"""Agentic rubric grader for the basic_layout task.

promptfoo custom Python assertion that ports verify_task.sh + verify_prompt.md
from the agentic-dx-improvement harness into promptfoo. It:

  1. Locates the per-provider workspace seed.js created (from context['provider']).
  2. Copies rubric.md back into the workspace (the solver never saw it).
  3. Runs the agentic verifier (Claude + Playwright MCP, driven by
     verify_prompt.md) in the workspace. The verifier runs app/run.sh, inspects
     the app across the rubric's viewports, and writes verify-result.json.
  4. Parses verify-result.json, sums the per-section scores, and returns a
     normalized score (handles the 21- vs 24-point total automatically).

CONCURRENCY: graders for the two solver rows can run at the same time, so each
is isolated:
  - server port: the baked per-provider port (workspaces/<agent>/.run-port) is
    set as PORT for the verifier and injected into the verify prompt, so the
    two graders' apps never share 8080;
  - Claude config + Playwright MCP: a per-workspace home (workspaces/<agent>/
    .claude-home, built by seed.js with an --isolated browser profile).
The run's port is freed before the verifier starts (clearing any dev server the
solver left running) and after it finishes.

Per ADR 0002, the rubric is a FLOOR, not the optimization target: pass = score
clears RUBRIC_PASS_THRESHOLD. The full trace + agent-time-breakdown.json the
verifier produces are preserved in the workspace as the real DX signal.

Env:
  AGENTIC_DX_DIR        path to the agentic-dx-improvement checkout
                        (default: ../agentic-dx-improvement, sibling of this repo)
  PROBLEM               problem name (default: basic_layout)
  RUBRIC_PASS_THRESHOLD floor as a 0..1 fraction of max (default: 0.6)
  VERIFIER_CMD          optional shell command to run the verifier instead of the
                        default `claude ...`; runs with cwd=workspace and PORT set.
"""

import base64
import json
import os
import re
import shutil
import signal
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))               # promptfoo/basic_layout
_REPO_ROOT = os.path.dirname(_HERE)                              # promptfoo
_AGENTIC_DX_DIR = os.environ.get(
    "AGENTIC_DX_DIR", os.path.join(_REPO_ROOT, "..", "agentic-dx-improvement")
)
_PROBLEM = os.environ.get("PROBLEM", "basic_layout")
_PASS_THRESHOLD = float(os.environ.get("RUBRIC_PASS_THRESHOLD", "0.6"))

# Reference images seeded from the problem dir — exclude from the embedded set.
_REFERENCE_IMAGES = {"Basic layout.png", "Basic layout (mobile).png"}


def _workspace_screenshots(workspace):
    """Markdown data-URI image tags for PNGs the verifier left in the workspace
    root (e.g. wide/narrow viewport captures), excluding the seeded reference
    images. Embedded into the rubric assertion's reason so they surface in
    `promptfoo view`. Unlike grade_static, this runs AFTER the verifier, so the
    screenshots actually exist by the time it reads the workspace."""
    imgs = []
    for name in sorted(os.listdir(workspace)) if os.path.isdir(workspace) else []:
        if not name.lower().endswith(".png") or name in _REFERENCE_IMAGES:
            continue
        try:
            with open(os.path.join(workspace, name), "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            imgs.append("![{}](data:image/png;base64,{})".format(name, b64))
        except Exception:
            pass
    return "\n\n".join(imgs)

# Bash command fragments that signal "Vaadin API archaeology" — the agent
# digging through jars / decompiling / spelunking the local Maven cache because
# it couldn't recall an API. CONTEXT.md calls this out as a key DX pain signal.
_ARCHAEOLOGY_HINTS = ("jar tf", "jar xf", "javap", ".m2/repository", "unzip ")


def _slug(name):
    """A stable, column-friendly metric suffix from a rubric section title,
    e.g. 'Layout (wide viewport)' -> 'layout_wide_viewport'."""
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or "section"


def _trace_metrics(context):
    """Behavioural-trace metrics for the SOLVER, read straight from the row's
    provider-response metadata.

    promptfoo's agentic providers (anthropic:claude-code, openai:codex) attach
    skillCalls / toolCalls / numTurns / durationMs / modelUsage / permissionDenials
    to the response metadata, and the Python-assertion context exposes it as
    `context['metadata']` (a.k.a. context['providerResponse']['metadata']). So we
    get the trace WITHOUT needing the solver's stream-json transcript
    (agent.log.jsonl) — the native providers don't write one into the workspace.

    Returns a dict of metric_name -> number (becomes promptfoo namedScores /
    columns). Degrades to {} for a provider that exposes no such metadata.

    NB: this is the SOLVER's trace. The agentic verifier this grader spawns runs
    as a subprocess, invisible to promptfoo, so its tool calls are not counted
    here (nor is its cost — see the cost note in the eval README).
    """
    ctx = context or {}
    meta = ctx.get("metadata") or (ctx.get("providerResponse") or {}).get("metadata") or {}
    if not isinstance(meta, dict) or not meta:
        return {}

    tool_calls = meta.get("toolCalls") or []
    skill_calls = meta.get("skillCalls") or []

    def _name(t):
        return str((t or {}).get("name") or "")

    mcp = [t for t in tool_calls if _name(t).startswith("mcp__")]
    errored = [t for t in tool_calls if (t or {}).get("is_error")]
    archaeology = 0
    for t in tool_calls:
        if _name(t) == "Bash":
            cmd = ((t.get("input") or {}).get("command") or "") if isinstance(t.get("input"), dict) else ""
            if any(h in cmd for h in _ARCHAEOLOGY_HINTS):
                archaeology += 1

    out = {
        "skill_calls": float(len(skill_calls)),
        "mcp_calls": float(len(mcp)),
        "tool_calls": float(len(tool_calls)),
        "tool_errors": float(len(errored)),
        "api_archaeology_calls": float(archaeology),
    }
    if isinstance(meta.get("numTurns"), (int, float)):
        out["num_turns"] = float(meta["numTurns"])
    if isinstance(meta.get("durationMs"), (int, float)):
        out["solve_seconds"] = round(meta["durationMs"] / 1000.0, 1)
    denials = meta.get("permissionDenials") or []
    if denials:
        out["permission_denials"] = float(len(denials))

    # Real token throughput. promptfoo's top-level token columns capture only
    # input+output and DROP cache_read / cache_creation — which dominate agentic
    # runs (e.g. 3.1M cache-read vs 65 input). modelUsage keeps the full picture.
    mu = meta.get("modelUsage") or {}
    cache_read = output_tok = 0
    for m in (mu.values() if isinstance(mu, dict) else []):
        if not isinstance(m, dict):
            continue
        cache_read += (m.get("cacheReadInputTokens") or m.get("cache_read_input_tokens") or 0)
        output_tok += (m.get("outputTokens") or m.get("output_tokens") or 0)
    if cache_read:
        out["cache_read_ktokens"] = round(cache_read / 1000.0, 1)
    if output_tok:
        out["output_tokens"] = float(output_tok)
    return out


def _agent_from_provider(context):
    """Map the grading row's provider to its solver name (codex|claude)."""
    prov = (context or {}).get("provider")
    if isinstance(prov, dict):
        ident = prov.get("label") or prov.get("id") or ""
    else:
        ident = str(prov or "")
    ident = ident.lower()
    if "codex" in ident:
        return "codex"
    if "claude" in ident:
        return "claude"
    return None


def _workspace(context):
    agent = _agent_from_provider(context)
    if not agent:
        return None
    ws = os.path.join(_HERE, "workspaces", agent)
    return ws if os.path.isdir(ws) else None


def _run_port(workspace):
    try:
        with open(os.path.join(workspace, ".run-port")) as f:
            return int(f.read().strip())
    except Exception:
        return 8080


def _claude_home(workspace):
    """Isolated CLAUDE_CONFIG_DIR for this workspace (built by seed.js); the
    --isolated Playwright profile in it keeps concurrent verifiers from
    deadlocking on a shared browser profile."""
    home = os.path.join(workspace, ".claude-home")
    if os.path.isdir(home):
        return home
    # Fallback: the shared bench home (fine when runs are serialized).
    return os.environ.get(
        "CLAUDE_CONFIG_DIR", os.path.join(_AGENTIC_DX_DIR, ".bench-claude-home")
    )


def _free_port(port):
    try:
        out = subprocess.run(["lsof", "-ti", "tcp:%d" % port],
                             capture_output=True, text=True)
        for pid in out.stdout.split():
            try:
                os.kill(int(pid), signal.SIGTERM)
            except Exception:
                pass
    except Exception:
        pass


def _run_verifier(workspace):
    """Run the agentic verifier in `workspace`; returns the verify-result.json path."""
    result_path = os.path.join(workspace, "verify-result.json")

    # Reuse a precomputed verdict if present (e.g. a manual or prior run).
    if os.path.isfile(result_path):
        return result_path

    problem_dir = os.path.join(_AGENTIC_DX_DIR, "problems", _PROBLEM)
    rubric_src = os.path.join(problem_dir, "rubric.md")
    verify_prompt_file = os.path.join(_AGENTIC_DX_DIR, "problems", "verify_prompt.md")
    if not os.path.isfile(verify_prompt_file):
        return None

    # The verifier expects rubric.md + prompt.txt + app/ in its cwd. seed.js
    # already wrote prompt.txt and app/; restore the rubric the solver never saw.
    if os.path.isfile(rubric_src):
        shutil.copy(rubric_src, os.path.join(workspace, "rubric.md"))
    with open(verify_prompt_file, encoding="utf-8") as f:
        verify_prompt = f.read()

    # The verify prompt hardcodes port 8080; override it with this run's baked
    # port so concurrent graders don't collide (and the right app is inspected).
    port = _run_port(workspace)
    if port != 8080:
        verify_prompt += (
            "\n\n--- PORT OVERRIDE (authoritative) ---\n"
            "This app runs on port {p}, NOT 8080. The PORT environment variable is "
            "already set to {p} and app/run.sh honours it. Wait for the application "
            "to start on port {p} and use http://localhost:{p} throughout; ignore "
            "any mention of port 8080 above.".format(p=port)
        )

    env = dict(os.environ)
    env["PORT"] = str(port)
    env["CLAUDE_CONFIG_DIR"] = _claude_home(workspace)

    # Clear any dev server the solver left bound to this run's port before run.sh.
    _free_port(port)

    verifier_cmd = os.environ.get("VERIFIER_CMD")
    if verifier_cmd:
        cmd = ["bash", "-lc", verifier_cmd]
    else:
        # Mirrors verify_task.sh's container invocation, run locally.
        cmd = [
            "claude", "--dangerously-skip-permissions",
            "--output-format", "stream-json", "--verbose",
            "-p", verify_prompt,
        ]

    # Own session/group so we can reap a lingering app server afterwards.
    proc = subprocess.Popen(cmd, cwd=workspace, env=env, start_new_session=True)
    try:
        proc.wait()
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        _free_port(port)
    return result_path


def get_assert(output, context=None):
    workspace = _workspace(context)
    if not workspace:
        return {"pass": False, "score": 0.0,
                "reason": "Could not locate this provider's workspace "
                          "(expected workspaces/<codex|claude> from "
                          "context['provider'])."}

    result_path = _run_verifier(workspace)
    if not result_path or not os.path.isfile(result_path):
        return {"pass": False, "score": 0.0,
                "reason": "Verifier did not produce verify-result.json in {}. "
                          "Check the verifier CLI/auth and that app/run.sh "
                          "builds.".format(workspace)}

    try:
        with open(result_path, encoding="utf-8") as f:
            verdict = json.load(f)
    except Exception as e:
        return {"pass": False, "score": 0.0,
                "reason": "verify-result.json is not valid JSON: {}".format(e)}

    total = 0
    max_total = 0
    lines = []
    named = {}
    for sec in verdict.get("criteria", []):
        s = sec.get("score", 0) or 0
        m = sec.get("max-score", 0) or 0
        total += s
        max_total += m
        lines.append("  {}: {}/{}".format(sec.get("section", "?"), s, m))
        # Per-section rubric fraction as its own column (rubric_<section>).
        if m:
            named["rubric_" + _slug(sec.get("section"))] = round(s / m, 4)

    score = (total / max_total) if max_total else 0.0

    # Behavioural-trace columns (skills/MCP/backtracks/archaeology/tokens). These
    # are diagnostics, NOT part of pass/fail — the returned `score` (rubric
    # fraction) and the threshold are unchanged. namedScores normalization
    # divides out this assertion's weight, so the raw values display per row.
    trace = _trace_metrics(context)
    named.update(trace)

    reason = "Rubric verifier: {}/{} ({:.0%}); floor = {:.0%}\n".format(
        total, max_total, score, _PASS_THRESHOLD) + "\n".join(lines)
    if trace:
        reason += "\n\nSolver trace: " + ", ".join(
            "{}={:g}".format(k, v) for k, v in sorted(trace.items()))

    shots = _workspace_screenshots(workspace)
    if shots:
        reason += "\n\n### Screenshots\n\n" + shots

    result = {
        "pass": bool(score >= _PASS_THRESHOLD),
        "score": score,
        "reason": reason,
    }
    if named:
        result["namedScores"] = named
    return result
