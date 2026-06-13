# Bench run reports

> **Browsing locally?** Open [`index.html`](index.html) — a visual landing page that links
> every report as a card grid (newest first). This `README.md` is the text equivalent for
> GitHub. Both list the same reports.

Visual HTML reports for individual **agentic-DX bench** sweeps — one self-contained
file per run. Each report reads a range of promptfoo evals (a solve→verify pass over
the three problems) and lays out the rubric scores, costs, per-problem deductions, and
the solvers' result screenshots.

These are **run reports** (a snapshot of one sweep's numbers). They're distinct from the
explainer docs one level up in `docs/` (`basic-layout-how-it-works.html`,
`promptfoo-idiom-review.html`, the ADR, …), which document how the bench *works* rather
than what a given run produced.

## What's here

| Report | Run | Solvers | Headline |
|---|---|---|---|
| [`bench-results-2026-06-10.html`](bench-results-2026-06-10.html) | 2026-06-10 (`eval-mVK` → `eval-6HA`) | codex · claude · claude-no-skills | Codex tops every rubric but is least idiomatic & ~2.3× the cost; the 480px narrow-viewport bug hits all three |
| [`bench-results-2026-06-10.md`](bench-results-2026-06-10.md) | 2026-06-10 | — | Markdown twin of the report above (same content, no charts/screenshots) |
| [`bench-results-2026-06-11.html`](bench-results-2026-06-11.html) | 2026-06-11 (`eval-Q5b` → `eval-ayP`) | claude (hosted MCP) · claude-local-mcp · claude-no-skills | Local Vaadin docs MCP ≈ hosted (no rubric/cost difference); the 480px bug recurs; one row killed by the SDK-hang artifact |
| [`bench-results-2026-06-11-run2.html`](bench-results-2026-06-11-run2.html) | 2026-06-11 (`eval-RJd` → `eval-DZW`) | claude · claude-local-mcp · claude-no-skills — **graded by Codex** | First run with the phase-2 verifier set to Codex (`gpt-5.5`): the Claude solvers are cross-graded, not self-graded. All clear the 60% floor (local-mcp 94.7% mean); basic_form near-perfect; the 480px bug recurs; two solve rows hung but graded fine in phase 2; Codex verification (~$50) outcosts solving (~$31); the Codex solver produced no rows |
| [`bench-results-2026-06-11-run3.html`](bench-results-2026-06-11-run3.html) | 2026-06-11 (`eval-oVM` → `eval-0ub`) | claude · claude-local-mcp · claude-no-skills — **graded by Claude** | Third sweep of the same A/B/C, back to Claude self-grading. The skills edge doesn't reproduce: the no-skills baseline posts the top mean (93.4%) and wins basic_layout while the skill variants take basic_form, all three within a point; basic_form near-perfect; the 480px bug recurs a third time; all three leak idiom points (plain `Div` over `HorizontalLayout`, `FormLayout` over `Composite`). The SDK hang was rampant — claude hung on all 3 solves ($0 recorded); one verifier row hung and was re-graded (`eval-0ub`). No screenshots (attachable shots landed only on hung rows) |
| [`bench-results-2026-06-12.html`](bench-results-2026-06-12.html) | 2026-06-12 (`eval-KZh` → `eval-Fbb`) | claude · claude-local-mcp · claude-no-skills — **graded by Codex** (`gpt-5.5`), solvers at `effort=medium` | Fourth sweep of the same A/B/C, cross-graded by Codex with the solvers pinned to medium effort. The dead heat holds: the three conditions finish within 0.6 pt on the mean (no-skills 90.9% · local-mcp 90.5% · claude 90.3%) and each wins one problem (local-mcp basic_layout, claude basic_form, no-skills md_ui_spec). A non-Claude grader independently confirms the recurring 480px narrow-viewport bug (4th straight sweep) and the plain-`Div` / `FormLayout`-over-`Composite` idiom leaks. Only 1 of 9 solve rows hung; Codex verification (~$59) outcost solving (~$21); sweep $80.50. **Not comparable to run 3** — grader (Claude→Codex) and solver effort (default→medium) both changed |
| [`bench-results-2026-06-13-mcp-vs-cli-vs-vanilla.html`](bench-results-2026-06-13-mcp-vs-cli-vs-vanilla.html) | 2026-06-13 (`eval-vPP` → `eval-cnf`) | claude (skills + Vaadin MCP, Playwright MCP) · claude-pw-cli (skills + Vaadin MCP, Playwright CLI) · claude-no-skills (vanilla, Playwright MCP) — **graded by Claude** | Three rows folding **two clean A/Bs** into one sweep — browser **transport** (MCP vs CLI, all else equal) and Vaadin **skills + docs MCP** vs **vanilla** (same MCP browser). **Transport ties exactly** on all three problems (20/24 · 30/31 · 48/48). **Skills add ~4 pooled points** (98/103 = 95.1% vs 94/103 = 91.3%), entirely on Vaadin idiom: vanilla built `basic_form` with a CSS-grid `Div` over `FormLayout` (−2) and on `md_ui_spec` shipped a **silently-broken delete flow** (server drops the `ConfirmDialog` event), `FormLayout` over `Composite`, and mixed Aura/Lumo theming (−3). The **CLI row matched claude's scores at ~26% lower cost** ($17.31 vs $23.29). The 480px breakpoint bug recurs on all three. *`basic_form`'s `pw-cli`/`vanilla` phase-2 verdicts recovered from disk after the agent-SDK teardown hang; one `vanilla` solve also hung but kept its trace.* |

## How to read a report

Each HTML report is a single portable file (CSS + base64 screenshots inlined — no network
needed). Sections: **TL;DR → Rubric scores → Cost → one chapter per problem**
(`basic_layout`, `basic_form`, `md_ui_spec`, each with a solve-trace table, color-coded
deduction callouts, and the result screenshots) **→ cross-cutting observations → caveats**.
Click any screenshot to open it full-resolution in an in-page lightbox (Esc / click to close).

Agent colors are consistent within a report: codex = amber, claude = teal,
claude-local-mcp = violet, claude-no-skills = gray.

Recurring caveats worth keeping in mind: scores are **n = 1 per cell** (treat ±1–2 points
as noise), the built-in token columns understate throughput (use `cost`), and when no Codex
runs, all grading is **Claude-judging-Claude** (self-grading).

## Generating a new one

These reports are written by prompting Claude Code with a run's start/end eval (URL or id)
on `localhost:15500`, then hand-authoring the self-contained HTML here. Start with the data
helper, which does the tedious, error-prone extraction (but no prose — that's the point):

```bash
python3 bench/extract_run.py --start <start-eval> --end <end-eval>
# writes bench/extracts/<end-id>/{run.json, run.md, *.png} and prints run.md
```

`run.md` gives the rubric scores, costs, per-bullet deductions, the **actual verifier**
(Claude vs Codex), and flags for hung solve rows / absent solvers; the `*.png` files are the
attached result screenshots. Author the HTML report from that (inline the screenshots as
base64), then add a matching card to [`index.html`](index.html) and a row to the table above
so both indexes stay in sync.

Judgment calls to get right (the numbers are easy; the framing is the point): identify the
**actual verifier** (Claude vs Codex) and caveat self- vs cross-grading accordingly; treat a
timed-out / exit-143 solve row as the **agent-SDK hang** (the workspace built fine and grades
normally in phase 2 — not a solver failure) rather than a $0 success; and only embed the
**attached** screenshots, never PNGs pulled off disk (later runs overwrite those workspaces).
