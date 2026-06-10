"""Static source checks for the md_ui_spec problem (PHASE 1 gate).

The Employees CRUD view. Covers the route/structure, the service contract, the
presence of automatic UI tests, and the 7-bullet Vaadin-specific section — all the
read-the-source bullets. The CRUD behaviour, validation, drawer visibility, layout,
and scrolling bullets are graded in PHASE 2 by the verifier against rubric.md.

run_checks(ctx) -> [(name, ok, critical), ...]; ctx is grade_static.CheckCtx.
"""


def run_checks(ctx):
    # No Aura+Lumo theme mix: fail only if BOTH theme families appear in the source
    # (a single family, or neither, is fine). Best-effort token sniff.
    mixes_themes = ctx.jre(r'\bLumo\w*') and ctx.jre(r'\bAura\w*')
    has_tests = len(ctx.glob_app("src/test/**/*.java")) > 0

    checks = [
        # --- Structure ---
        ('@Route("employees") present', ctx.jre(r'@Route\(\s*"employees"'), True),
        ('title rendered as H1', ctx.jhas("H1"), False),
        ("uses Grid", ctx.jhas("Grid"), True),

        # --- Service contract ---
        ("EmployeesService class present", ctx.jhas("EmployeesService"), False),
        ("service exposes findAll()", ctx.jre(r'\bfindAll\s*\('), False),
        ("service exposes save(Employee)", ctx.jre(r'\bsave\s*\(\s*Employee'), False),
        ("service exposes delete(Employee)", ctx.jre(r'\bdelete\s*\(\s*Employee'), False),

        # --- Vaadin-specific (the rubric's read-the-source bullets) ---
        ("form extends Composite<FormLayout>", ctx.jre(r'extends\s+Composite\s*<\s*FormLayout'), False),
        # Auto-responsive features, NOT manually configured responsiveSteps.
        ("FormLayout auto-responsive (no manual responsiveSteps)",
         ctx.jhas("FormLayout") and not ctx.jre(r'setResponsiveSteps|ResponsiveStep'), False),
        # Binder with method-reference binding (getter/setter refs), not String property names.
        ("Binder binds via method references",
         ctx.jhas("Binder") and ctx.jre(r'bind\([^)]*::'), False),
        ("component fields declared final",
         ctx.jre(r'private\s+final\s+(TextField|EmailField|DatePicker|ComboBox|Select|Checkbox|Button|Grid)'), False),
        ("EmployeesService constructor-injected",
         ctx.jre(r'public\s+\w+\s*\([^)]*EmployeesService\s+\w+'), False),
        ("delete confirmation uses ConfirmDialog", ctx.jhas("ConfirmDialog"), False),
        ("uses EmailField", ctx.jhas("EmailField"), False),
        ("does not mix Aura and Lumo themes", not mixes_themes, False),

        # --- Automatic UI tests (the task requires them) ---
        ("automatic UI tests present (src/test/**/*.java)", has_tests, False),
    ]
    checks += ctx.common_hygiene()
    return checks
