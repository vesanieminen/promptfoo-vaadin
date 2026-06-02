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

import json
import os
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
    for sec in verdict.get("criteria", []):
        s = sec.get("score", 0) or 0
        m = sec.get("max-score", 0) or 0
        total += s
        max_total += m
        lines.append("  {}: {}/{}".format(sec.get("section", "?"), s, m))

    score = (total / max_total) if max_total else 0.0
    return {
        "pass": bool(score >= _PASS_THRESHOLD),
        "score": score,
        "reason": "Rubric verifier: {}/{} ({:.0%}); floor = {:.0%}\n".format(
            total, max_total, score, _PASS_THRESHOLD) + "\n".join(lines),
    }
