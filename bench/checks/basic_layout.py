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

        # --- Vaadin-specific (confirm structural intent in code) ---
        ("uses HorizontalLayout", ctx.jhas("HorizontalLayout"), True),
        ("uses VerticalLayout", ctx.jhas("VerticalLayout"), True),
        ("content area uses Scroller", ctx.jhas("Scroller"), False),
    ]
    # No inline styles (Java + templates) and no leaked React/TSX views.
    checks += ctx.common_hygiene()
    return checks
