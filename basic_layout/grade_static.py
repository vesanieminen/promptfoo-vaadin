"""Deterministic source-level grader for the basic_layout task.

promptfoo custom Python assertion. It reads the produced app from the
per-provider workspace seed.js created (workspaces/<codex|claude>/app) and
checks the parts of the rubric verifiable by reading source — the Structure
section (presence) and the Vaadin-specific section ("verify by reading the
source — DOM inspection alone is not sufficient").

This is the cheap, reproducible gate. The behavioural / visual rubric bullets
(alignment, scrolling, viewport behaviour) are graded by grade_rubric.py.

Contract: define get_assert(output, context) -> {pass, score, reason}.
The workspace is located from `context['provider']` (the row being graded), not
from `output`: the native agentic providers return the agent's final message,
not a workspace path.
"""

import glob
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))  # promptfoo/basic_layout


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


def _app_dir(context):
    agent = _agent_from_provider(context)
    if not agent:
        return None
    return os.path.join(_HERE, "workspaces", agent, "app")


def get_assert(output, context=None):
    app = _app_dir(context)
    if not app or not os.path.isdir(app):
        return {
            "pass": False,
            "score": 0.0,
            "reason": "Could not locate the produced app/ dir for this provider "
                      "(expected workspaces/<codex|claude>/app from "
                      "context['provider']).",
        }

    java_files = glob.glob(os.path.join(app, "src/main/java/**/*.java"), recursive=True)
    src = ""
    for fp in java_files:
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                src += f.read() + "\n"
        except Exception:
            pass

    checks = []

    def chk(name, ok, critical=False):
        checks.append((name, bool(ok), critical))

    # --- Structure (presence in code) ---
    chk('@Route("basic_layout") present',
        re.search(r'@Route\(\s*"basic_layout"', src) is not None, critical=True)

    # --- Vaadin-specific (rubric says: confirm structural intent in code) ---
    chk("uses HorizontalLayout", "HorizontalLayout" in src, critical=True)
    chk("uses VerticalLayout", "VerticalLayout" in src, critical=True)
    chk("content area uses Scroller", "Scroller" in src)

    # No inline styles in Java (getStyle().set(...) / setAttribute("style", ...)).
    inline_java = (re.search(r'getStyle\(\)\s*\.\s*set', src) is not None
                   or re.search(r'setAttribute\(\s*"style"', src) is not None)
    chk("no inline styles in Java", not inline_java)

    # No inline style="" in any template/HTML shipped with the app.
    tmpl_inline = False
    for ext in ("html", "ts", "tsx", "js", "jsx"):
        for fp in glob.glob(os.path.join(app, "src/main/**/*." + ext), recursive=True):
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    if re.search(r'style\s*=\s*["\']', f.read()):
                        tmpl_inline = True
                        break
            except Exception:
                pass
        if tmpl_inline:
            break
    chk("no inline style= in templates", not tmpl_inline)

    # Vaadin Flow (Java) only — no React/TSX view files leaked in.
    tsx = glob.glob(os.path.join(app, "src/main/frontend/**/*.tsx"), recursive=True)
    chk("no React/TSX view files", len(tsx) == 0)

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    score = passed / total if total else 0.0
    critical_ok = all(ok for _, ok, crit in checks if crit)

    lines = ["{:4}  {}".format("PASS" if ok else "FAIL", name) for name, ok, _ in checks]
    return {
        "pass": bool(critical_ok),
        "score": score,
        "reason": "Static source checks (Structure & Vaadin-specific) "
                  "{}/{} passed:\n".format(passed, total) + "\n".join(lines),
    }
