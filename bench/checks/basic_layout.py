"""Static source checks for the basic_layout problem (PHASE 1 gate).

Covers the rubric bullets verifiable by reading code: the Structure route and the
Vaadin-specific section ("verify by reading the source"). The behavioural/visual
bullets (alignment, scrolling, viewport, content-area, styling consistency) are
graded in PHASE 2 by the verifier against rubric.md.

run_checks(ctx) -> [(name, ok, critical), ...]; ctx is grade_static.CheckCtx.
"""


def run_checks(ctx):
    checks = [
        # --- Structure (presence in code) ---
        ('@Route("basic_layout") present', ctx.jre(r'@Route\(\s*"basic_layout"'), True),

        # --- Vaadin-specific ("verify by reading the source") ---
        # NOT critical: the rubric scores these (Vaadin-specific is 3/24 pts) but
        # never gates on them — a working layout built from plain Divs is docked,
        # not failed. Only @Route above hard-fails the row. (Matches the phase-2
        # rubric and the source benchmark; severity aligned in main's PR #19.)
        ("uses HorizontalLayout", ctx.jhas("HorizontalLayout"), False),
        ("uses VerticalLayout", ctx.jhas("VerticalLayout"), False),
        ("content area uses Scroller", ctx.jhas("Scroller"), False),
    ]
    # No inline styles (Java + templates) and no leaked React/TSX views.
    checks += ctx.common_hygiene()
    return checks
