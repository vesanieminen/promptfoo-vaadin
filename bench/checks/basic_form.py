"""Static source checks for the basic_form problem (PHASE 1 gate).

Covers the rubric's source-verifiable bullets — the route, H2 headings, and the
8-bullet Vaadin-specific section ("verify by reading the source"). The layout /
field-configuration / reusability bullets that need a running browser are graded in
PHASE 2 by the verifier against rubric.md.

run_checks(ctx) -> [(name, ok, critical), ...]; ctx is grade_static.CheckCtx.
"""


def run_checks(ctx):
    checks = [
        # --- Structure ---
        ('@Route("basic_form") present', ctx.jre(r'@Route\(\s*"basic_form"'), True),
        ("section headings use H2", ctx.jhas("H2"), False),

        # --- Vaadin-specific (the rubric's read-the-source bullets) ---
        # Form is a separate reusable component (a Composite / layout subclass),
        # added to the view as an instance rather than inlined in the route class.
        ("form is a reusable component (extends Composite/layout)",
         ctx.jre(r'extends\s+Composite\b') or ctx.jre(r'class\s+\w*Form\w*\s+extends'), False),
        ("uses FormLayout", ctx.jhas("FormLayout"), True),
        # 2-col @≥800px / 1-col @<380px → responsive steps configured.
        ("FormLayout responsive steps configured",
         ctx.jre(r'setResponsiveSteps|ResponsiveStep'), False),
        # Full-row fields / aligned columns → colspans set.
        ("uses setColspan for full-row/column spans", ctx.jhas("setColspan("), False),
        ("required indicator set on required fields",
         ctx.jre(r'setRequiredIndicatorVisible\(\s*true\s*\)'), False),
        ("placeholders set (setPlaceholder)", ctx.jhas("setPlaceholder("), False),
        ("format hints set (setHelperText)", ctx.jhas("setHelperText("), False),
        ("single-choice groups use RadioButtonGroup", ctx.jhas("RadioButtonGroup"), False),
        ("multi-choice groups use CheckboxGroup", ctx.jhas("CheckboxGroup"), False),
        ("email fields use EmailField", ctx.jhas("EmailField"), False),
    ]
    checks += ctx.common_hygiene()
    return checks
