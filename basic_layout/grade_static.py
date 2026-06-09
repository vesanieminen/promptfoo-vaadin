"""Deterministic source-level grader for the agentic-dx solve phase (PHASE 1).

promptfoo custom Python assertion. It reads the produced app from the per-provider
workspace seed.js created (workspaces/<problem>/<agent>/app) and checks the parts of
the rubric verifiable by reading source — the structural / Vaadin-specific bullets
the rubric says to "verify by reading the source — DOM inspection alone is not
sufficient".

PER-PROBLEM: the actual checks live in checks/<problem>.py (one module per problem,
each exporting run_checks(ctx) -> [(name, ok, critical), ...]); this file is the
problem-agnostic harness that picks the module from the PROBLEM env var, supplies a
CheckCtx of shared helpers (concatenated Java source, solver-authored globs, the
common Vaadin hygiene checks), runs the checks, and emits the pass/score/reason. The
problem is read from PROBLEM (set by run.sh per problem; default basic_layout) — the
same var seed.js / the configs use.

This is the cheap, reproducible gate. The behavioural / visual rubric bullets
(alignment, scrolling, viewport behaviour, flows) are graded in PHASE 2 by the
verifier provider in verify.js (parsed by grade_verdict.py).

This assertion ALSO emits the SOLVER's behavioural-trace diagnostic columns
(skill_calls, mcp_calls, api_archaeology_calls, num_turns, solve_seconds,
cache_read_ktokens, …) as namedScores, read from this row's provider-response
metadata. They're diagnostics (ADR 0002), not part of pass/fail. They live here
because the phase-2 verify-* rows' metadata describes the verifier, not the solver.

Contract: define get_assert(output, context) -> {pass, score, reason, namedScores}.
The workspace is located from `context['provider']` (the row being graded), not from
`output`: the native agentic providers return the agent's final message, not a path.
"""

import base64
import glob
import html
import importlib.util
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))  # promptfoo/basic_layout (the bench dir)

# The problem this row belongs to. run.sh sets PROBLEM per problem; the default
# keeps a bare phase-1 run scoring the original basic_layout task.
_PROBLEM = os.environ.get("PROBLEM", "basic_layout")

# Bash command fragments that signal "Vaadin API archaeology" — the agent digging
# through jars / decompiling / spelunking the local Maven cache because it couldn't
# recall an API. CONTEXT.md calls this out as a key DX pain signal.
_ARCHAEOLOGY_HINTS = ("jar tf", "jar xf", "javap", ".m2/repository", "unzip ")


def _trace_metrics(context):
    """Behavioural-trace metrics for the SOLVER, read straight from this row's
    provider-response metadata.

    promptfoo's agentic providers (anthropic:claude-code, openai:codex) attach
    skillCalls / toolCalls / numTurns / durationMs / modelUsage / permissionDenials
    to the response metadata, exposed to the Python assertion as context['metadata'].
    Returns metric_name -> number (becomes promptfoo namedScores / columns); {} for
    a provider that exposes no such metadata.

    These are DIAGNOSTICS, not pass/fail (ADR 0002: the trace is the real DX signal,
    the rubric is only a floor). Lives here, on the PHASE 1 solver rows, because the
    PHASE 2 verify-* rows' metadata describes the VERIFIER, not the solver.
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
    # runs. modelUsage keeps the full picture.
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


def _solver_authored(paths):
    """Drop framework-generated paths from a glob result.

    A Vaadin production build writes scaffolding into src/main/frontend/generated/
    (routes.tsx, Flow.tsx, vaadin-react.tsx, …) and pulls deps into node_modules.
    None of it is solver-authored, so the "no React/TSX view files" and
    "no inline style=" checks must ignore it — otherwise whichever agent happened
    to build/run the app trips a false FAIL purely from the generated bundle.
    """
    out = []
    for p in paths:
        parts = p.replace(os.sep, "/").split("/")
        if "generated" in parts or "node_modules" in parts:
            continue
        out.append(p)
    return out


# Valid workspace names. A provider label maps to one of these EXACTLY after the
# `verify-` prefix is stripped. Exact match — not a substring scan — so 'claude' can
# never be mistaken for 'claude-no-skills' (the id `anthropic:claude-agent-sdk` also
# contains "claude"), regardless of ordering.
_WORKSPACES = frozenset(("codex", "claude", "claude-no-skills"))


def _agent_from_provider(context):
    """Map the grading row's provider to its workspace name
    (codex | claude | claude-no-skills): exact-match the label with any `verify-`
    prefix stripped; None if unrecognized."""
    prov = (context or {}).get("provider")
    if isinstance(prov, dict):
        ident = prov.get("label") or prov.get("id") or ""
    else:
        ident = str(prov or "")
    ident = ident.strip().lower()
    for pfx in ("verify-", "verify_"):
        if ident.startswith(pfx):
            ident = ident[len(pfx):]
            break
    return ident if ident in _WORKSPACES else None


def _app_dir(context):
    agent = _agent_from_provider(context)
    if not agent:
        return None
    # workspaces/<problem>/<agent>/app — must match seed.js's bench.workspaceRel.
    return os.path.join(_HERE, "workspaces", _PROBLEM, agent, "app")


def _reference_images(workspace):
    """The seeded reference PNGs (wireframes) recorded by seed.js in
    .reference-images.json — so the screenshot gallery excludes them without
    hardcoding filenames per problem. Empty set if absent (e.g. md_ui_spec, no PNGs)."""
    try:
        with open(os.path.join(workspace, ".reference-images.json"), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {str(n) for n in data}
    except Exception:
        pass
    return set()


# ---------------------------------------------------------------------------
# CheckCtx — the helper bundle handed to each problem's run_checks(ctx). Carries the
# concatenated Java source plus file-access / common-check helpers so the per-problem
# modules stay tiny and import nothing but `re`. Keeping the helpers here (rather than
# a shared module the dynamically-loaded check files import) avoids any sys.path /
# package fragility in promptfoo's python runner.
# ---------------------------------------------------------------------------
class CheckCtx:
    def __init__(self, app):
        self.app = app
        self.java_files = glob.glob(os.path.join(app, "src/main/java/**/*.java"), recursive=True)
        src = ""
        for fp in self.java_files:
            src += self.read(fp) + "\n"
        self.java_src = src

    @staticmethod
    def read(fp):
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return ""

    def glob_app(self, pattern):
        """Solver-authored files matching `pattern` (recursive) under app/."""
        return _solver_authored(glob.glob(os.path.join(self.app, pattern), recursive=True))

    def jhas(self, substr):
        """Substring present anywhere in the concatenated Java source."""
        return substr in self.java_src

    def jre(self, pattern):
        """Regex match anywhere in the concatenated Java source."""
        return re.search(pattern, self.java_src) is not None

    # --- shared checks every Vaadin-Flow problem reuses (no inline styles, no TSX) ---
    def _inline_java_styles(self):
        return (re.search(r'getStyle\(\)\s*\.\s*set', self.java_src) is not None
                or re.search(r'setAttribute\(\s*"style"', self.java_src) is not None)

    def _template_inline_style(self):
        for ext in ("html", "ts", "tsx", "js", "jsx"):
            for fp in self.glob_app("src/main/**/*." + ext):
                if re.search(r'style\s*=\s*["\']', self.read(fp)):
                    return True
        return False

    def _has_tsx_views(self):
        # Vaadin Flow (Java) only — no solver-authored React/TSX view files leaked in.
        # (src/main/frontend/generated/*.tsx is Vaadin's own scaffolding — ignored.)
        return len(self.glob_app("src/main/frontend/**/*.tsx")) > 0

    def common_hygiene(self):
        """The Vaadin-specific 'no inline styles / no TSX views' bullets shared by
        all problems. Returns [(name, ok, critical), ...]."""
        return [
            ("no inline styles in Java", not self._inline_java_styles(), False),
            ("no inline style= in templates", not self._template_inline_style(), False),
            ("no React/TSX view files", not self._has_tsx_views(), False),
        ]


def _load_check_module(problem):
    """Load checks/<problem>.py by file path (no package/sys.path assumptions).
    Returns the module, or None if there is no module for this problem."""
    p = os.path.join(_HERE, "checks", problem + ".py")
    if not os.path.isfile(p):
        return None
    spec = importlib.util.spec_from_file_location("agentic_checks_" + problem, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_screenshot_gallery(workspace, out_name, title, reference_images):
    """Write a self-contained HTML gallery of the workspace's non-reference PNGs
    (each embedded as a data URI) and return (abs_path, count); (None, 0) if none.

    We do NOT embed the screenshots into the assertion `reason`: promptfoo's viewer
    renders the reason as PLAIN TEXT (whitespace-pre-wrap), not markdown, so data-URI
    <img> tags there show up as an unreadable base64 wall. Instead we drop a
    standalone gallery next to the captures, openable straight from disk (file://) —
    the reason just carries a path pointer.
    """
    if not os.path.isdir(workspace):
        return None, 0
    names = [n for n in sorted(os.listdir(workspace))
             if n.lower().endswith(".png") and n not in reference_images]
    if not names:
        return None, 0
    parts = [
        "<!doctype html><html><head><meta charset=\"utf-8\">",
        "<title>{}</title>".format(html.escape(title)),
        "<style>body{font-family:system-ui,-apple-system,sans-serif;margin:24px;"
        "background:#111;color:#eee}figure{margin:0 0 28px}figcaption{font:13px "
        "ui-monospace,monospace;margin-bottom:6px;color:#9cf}img{max-width:100%;"
        "height:auto;border:1px solid #333;background:#fff}</style></head><body>",
        "<h1>{}</h1>".format(html.escape(title)),
    ]
    for name in names:
        try:
            with open(os.path.join(workspace, name), "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except Exception:
            continue
        parts.append('<figure><figcaption>{n}</figcaption>'
                     '<img alt="{n}" src="data:image/png;base64,{b}"></figure>'
                     .format(n=html.escape(name), b=b64))
    parts.append("</body></html>")
    out_path = os.path.join(workspace, out_name)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(parts))
    except Exception:
        return None, 0
    return out_path, len(names)


def get_assert(output, context=None):
    app = _app_dir(context)
    if not app or not os.path.isdir(app):
        return {
            "pass": False,
            "score": 0.0,
            "reason": "Could not locate the produced app/ dir for this provider "
                      "(expected workspaces/{}/<codex|claude|claude-no-skills>/app "
                      "from context['provider']).".format(_PROBLEM),
        }

    ctx = CheckCtx(app)

    mod = _load_check_module(_PROBLEM)
    note = ""
    if mod is not None and hasattr(mod, "run_checks"):
        checks = [tuple(c) for c in mod.run_checks(ctx)]
    else:
        # No per-problem module: degrade to the shared hygiene checks (non-critical)
        # so a brand-new problem still gets some static signal instead of crashing.
        checks = ctx.common_hygiene()
        note = ("\n\n(note: no checks/{}.py — ran shared Vaadin hygiene checks only; "
                "add a module for problem-specific static checks)".format(_PROBLEM))

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    score = passed / total if total else 0.0
    critical_ok = all(ok for _, ok, crit in checks if crit)

    lines = ["{:4}  {}".format("PASS" if ok else "FAIL", name) for name, ok, _ in checks]
    reason = ("Static source checks for {} ({}/{} passed):\n".format(_PROBLEM, passed, total)
              + "\n".join(lines) + note)

    workspace = os.path.dirname(app)  # workspaces/<problem>/<agent>/app -> .../<agent>
    gallery, n_shots = _write_screenshot_gallery(
        workspace, "solver-screenshots.html",
        "{} — {} solver screenshots".format(os.path.basename(workspace), _PROBLEM),
        _reference_images(workspace))
    if gallery:
        reason += ("\n\nScreenshots: {} solver capture(s) — open in a browser "
                   "(promptfoo shows reasons as plain text, not images):\n  "
                   "{}".format(n_shots, gallery))

    # Solver behavioural-trace columns (diagnostics, not part of pass/fail).
    trace = _trace_metrics(context)
    if trace:
        reason += "\n\nSolver trace: " + ", ".join(
            "{}={:g}".format(k, v) for k, v in sorted(trace.items()))

    result = {
        "pass": bool(critical_ok),
        "score": score,
        "reason": reason,
    }
    if trace:
        result["namedScores"] = trace
    return result
