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

These are produced by the **`bench-report`** skill (`.claude/skills/bench-report/`). Point it
at a run's start/end eval (URL or id) on `localhost:15500` and it fetches the evals, extracts
the numbers, embeds the attached screenshots, and writes the report here. See that skill's
`SKILL.md` for the workflow and the judgment calls (framing, the SIGTERM-hang artifact, and
the screenshot-coverage honesty rules).

After adding a report, regenerate the landing page so it's linked:

```bash
python3 .claude/skills/bench-report/scripts/gen_index.py   # rebuilds index.html from the folder
```
