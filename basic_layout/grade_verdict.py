"""Rubric-verdict grader for the basic_layout task — PHASE 2 (verify.yaml).

This is the trimmed successor to the old grade_rubric.py. The heavy lifting —
running the app, driving Playwright across viewports, scoring against rubric.md —
is no longer done HERE. It is done by the VERIFIER, which is now a first-class
promptfoo provider (anthropic:claude-agent-sdk) in verify.yaml, one per solved
workspace. See docs/ADR-verifier-as-provider.md for why.

So this assertion no longer spawns a subprocess, manages ports, retries, or an
isolated Claude home. It just reads the verifier provider's structured verdict
and turns it into a pass/score + per-section diagnostic columns:

  1. Locate this row's workspace from context['provider'] (verify-codex ->
     workspaces/codex, etc.).
  2. Read the verdict. Primary source: the provider's STRUCTURED OUTPUT (the
     configured output_format schema), delivered as the parsed `output` object
     (or context['metadata']['structuredOutput']). Fallback: verify-result.json
     in the workspace, which the verify prompt also asks the agent to write.
  3. Sum the per-section scores, normalize to 0..1 (handles the 21- vs 24-point
     total automatically), pass if it clears RUBRIC_PASS_THRESHOLD.

Because the verifier is a provider, promptfoo now tracks ITS cost / tokens /
latency natively as the verify-* rows — closing the "verifier cost is invisible"
gap the subprocess design had. The SOLVER's behavioural trace (skills, MCP,
archaeology, tokens) is emitted by grade_static.py on the PHASE 1 solver rows,
not here.

Per ADR 0002 the rubric is a FLOOR, not the optimization target.

Env:
  RUBRIC_PASS_THRESHOLD  floor as a 0..1 fraction of max (default: 0.6)
"""

import base64
import html
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))            # promptfoo/basic_layout
_PASS_THRESHOLD = float(os.environ.get("RUBRIC_PASS_THRESHOLD", "0.6"))

# Reference images seeded from the problem dir — exclude from the captured set.
_REFERENCE_IMAGES = {"Basic layout.png", "Basic layout (mobile).png"}

# Valid workspace names. A provider label maps to one of these EXACTLY after the
# `verify-` prefix is stripped: solver labels ARE the name (codex / claude /
# claude-no-skills); verifier labels are `verify-<name>`. Exact match — not a
# substring scan — so 'claude' can never be mistaken for 'claude-no-skills' (the id
# `anthropic:claude-agent-sdk` also contains "claude"), regardless of ordering.
_WORKSPACES = frozenset(("codex", "claude", "claude-no-skills"))


def _agent_from_provider(context):
    """Map the grading row's provider to its workspace name.

    Handles both PHASE 1 solver labels (codex / claude / claude-no-skills) and
    PHASE 2 verifier labels (verify-codex / verify-claude / verify-claude-no-skills),
    by stripping the `verify-` prefix and matching the remainder EXACTLY. Returns
    None for anything unrecognized — a clean fail, not a silent misroute.
    """
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


def _workspace(context):
    agent = _agent_from_provider(context)
    if not agent:
        return None
    ws = os.path.join(_HERE, "workspaces", agent)
    return ws if os.path.isdir(ws) else None


def _as_verdict(cand):
    """Coerce a candidate into a verdict dict ({'criteria': [...]}) or None."""
    if isinstance(cand, dict) and isinstance(cand.get("criteria"), list):
        return cand
    if isinstance(cand, str):
        s = cand.strip()
        # Tolerate a stray markdown fence around the JSON, just in case.
        if s.startswith("```"):
            s = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", s).strip()
        try:
            v = json.loads(s)
        except Exception:
            return None
        if isinstance(v, dict) and isinstance(v.get("criteria"), list):
            return v
    return None


def _load_verdict(output, context, workspace):
    """Return (verdict_dict, source_label) or (None, None).

    Prefer the provider's structured output (parsed object in `output`, or
    metadata.structuredOutput); fall back to verify-result.json on disk.
    """
    meta = (context or {}).get("metadata") or {}
    for cand in (output, meta.get("structuredOutput")):
        v = _as_verdict(cand)
        if v:
            return v, "structured output"
    if workspace:
        rp = os.path.join(workspace, "verify-result.json")
        if os.path.isfile(rp):
            try:
                with open(rp, encoding="utf-8") as f:
                    v = json.load(f)
                if isinstance(v, dict) and isinstance(v.get("criteria"), list):
                    return v, "verify-result.json (fallback)"
            except Exception:
                pass
    return None, None


def _slug(name):
    """Stable, column-friendly metric suffix from a rubric section title,
    e.g. 'Alignment (wide viewport)' -> 'alignment_wide_viewport'."""
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or "section"


def _write_screenshot_gallery(workspace, out_name, title):
    """Self-contained HTML gallery of the verifier's PNG captures (data URIs).

    Scans the workspace root and its `.pw-verify` Playwright output dir, skipping
    the seeded reference wireframes. Best-effort: returns (None, 0) if none. We do
    NOT inline images into the assertion `reason` — promptfoo renders reasons as
    plain text, so a path pointer is friendlier than a base64 wall.
    """
    if not workspace or not os.path.isdir(workspace):
        return None, 0
    candidates = []
    for d in (workspace, os.path.join(workspace, ".pw-verify")):
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            if n.lower().endswith(".png") and n not in _REFERENCE_IMAGES:
                candidates.append(os.path.join(d, n))
    if not candidates:
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
    for fp in candidates:
        try:
            with open(fp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except Exception:
            continue
        name = os.path.basename(fp)
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
    return out_path, len(candidates)


def get_assert(output, context=None):
    workspace = _workspace(context)
    if not workspace:
        return {"pass": False, "score": 0.0,
                "reason": "Could not locate this provider's workspace (expected "
                          "workspaces/<codex|claude|claude-no-skills> from "
                          "context['provider'])."}

    verdict, source = _load_verdict(output, context, workspace)
    if not verdict:
        return {"pass": False, "score": 0.0,
                "reason": "No rubric verdict found. The verifier provider should "
                          "return the structured output schema (and write "
                          "verify-result.json as a fallback) in {ws}. Check the "
                          "verify-* row's transcript/output for where it aborted "
                          "and that app/run.sh builds and serves.".format(ws=workspace)}

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
        if m:
            named["rubric_" + _slug(sec.get("section"))] = round(s / m, 4)

    score = (total / max_total) if max_total else 0.0

    reason = "Rubric verdict ({}): {}/{} ({:.0%}); floor = {:.0%}\n".format(
        source, total, max_total, score, _PASS_THRESHOLD) + "\n".join(lines)

    gallery, n_shots = _write_screenshot_gallery(
        workspace, "verify-screenshots.html",
        "{} — basic_layout verifier screenshots".format(os.path.basename(workspace)))
    if gallery:
        reason += ("\n\nScreenshots: {} viewport capture(s) — open in a browser "
                   "(promptfoo shows reasons as plain text, not images):\n  "
                   "{}".format(n_shots, gallery))

    result = {
        "pass": bool(score >= _PASS_THRESHOLD),
        "score": score,
        "reason": reason,
    }
    if named:
        result["namedScores"] = named
    return result
