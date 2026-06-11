---
name: bench-report
description: >-
  Generate a visual HTML report for an agentic-DX bench run — a promptfoo solve→verify
  sweep over the Vaadin problems on localhost:15500. Use this whenever the user asks to
  create/build/make a report, summary, or write-up of a bench run, an eval range,
  "today's"/"yesterday's" run, or pastes promptfoo eval URLs/ids and wants the results
  laid out. Produces a self-contained report (rubric charts, cost bars, per-problem
  deductions, embedded result screenshots, lightbox) in docs/bench-reports/. Reach for
  this even if the user just says "report the results" or "write up that run" — if it's
  about turning a promptfoo bench sweep into a readable report, this is the skill.
---

# bench-report

Turn one agentic-DX bench sweep into a single, self-contained, visual HTML report.

The bench (`bench/README.md`) runs each Vaadin problem in **two phases** — *solve*
(each agent edits a fresh workspace) then *verify* (a Playwright agent runs the app and
grades it against the rubric). One "run" is a solve→verify pass over the three problems,
which lands as ~6 promptfoo evals in a contiguous time range. This skill reads that range
off the promptfoo server and writes the report.

## Workflow

**1. Get the run's bounds.** You need the **start** and **end** eval — either the URL
(`http://localhost:15500/eval/eval-…`) or the bare id. The user usually gives both; if
they give a date or "today's run", list the evals and pick the first/last bench eval in
that window:

```bash
curl -s http://localhost:15500/api/results | python3 -c "import json,sys;[print(r['evalId'],'|',r['description'][:70]) for r in json.load(sys.stdin)['data'] if '<date>' in r['evalId']]"
```

**2. Generate the report.** The bundled script does all the mechanical work — selecting
the evals in range, pairing them into problems × {solve, verify}, extracting scores /
costs / traces / per-bullet deductions, detecting the solver set, embedding the attached
screenshots, and wiring the lightbox:

```bash
python3 .claude/skills/bench-report/scripts/gen_bench_report.py \
  --start <start-url-or-id> --end <end-url-or-id>
# writes docs/bench-reports/bench-results-<date>.html and prints the path
```

It prints what it found (agents, problems, screenshot count). Read that — it tells you the
solver set, which framing to use, and whether any row was killed.

**3. Refine the narrative.** The script writes a *complete, shippable* report with
data-derived defaults, but the parts that need judgement are marked with
`<!-- EDIT: … -->` comments. Open the file and rewrite those spots so the report says
something, not just shows numbers. Edit the HTML directly (it's plain HTML/CSS with the
screenshots already inlined — don't re-run the script unless the underlying data changed):

- **Hero lede** + **TL;DR** (the headline stat and bullets): lead with the run's actual
  finding. *What was being tested?* A model comparison (codex vs claude)? An A/B like
  local-vs-hosted MCP? Say so, and give the verdict. The auto-bullets just list who led —
  replace them with the story.
- **Per-problem framing** (`<!-- EDIT -->` in each chapter's sub-line) and the
  **deduction callouts**: the script lists each agent's below-max bullets with the
  verifier's raw feedback. Turn those into one or two readable sentences naming the root
  cause (e.g. "the 480px breakpoint", "Aura's vertical group default", "EmailField with no
  error message"). Keep the specifics — they're what makes the report useful.
- **Screenshot captions**: the script grabs *every* attached screenshot and captions each
  generically. Tie each shot to its rubric outcome, and prune redundant ones (delete the
  whole `<figure>…</figure>`) so each chapter shows the telling views, not all of them.
- **Observations**: keep the auto-detected ones (e.g. a section every agent lost — a
  benchmark-level bug) and add the cross-cutting insights only you can see across runs.

**4. Verify and open.**

```bash
python3 -c "s=open('<out>').read();print('sections',s.count('<section'),s.count('</section>'),'| divs',s.count('<div'),s.count('</div>'),'| figures',s.count('<figure'),s.count('</figure>'))"
open <out>
```

Tag counts must balance. Click a screenshot to confirm the lightbox opens it full-size.

**5. Index it.** Regenerate the visual landing page so the new report is linked from it,
and add a row to the text index:

```bash
python3 .claude/skills/bench-report/scripts/gen_index.py   # rebuilds docs/bench-reports/index.html
```

`gen_index.py` scans the folder and rebuilds `index.html` (a card grid, newest first) from
each report's `<title>`, hero lede, and solver legend chips — so it stays in sync as long as
your report has those (it always does). Then add a one-row entry to
`docs/bench-reports/README.md` (the GitHub-facing text index) for good measure.

## Honesty rules — get these right, they're the whole point

The numbers are easy; the integrity of the framing is what makes the report trustworthy.

- **Self-grading.** Every verifier is a Claude agent. When a Claude *solver* is graded,
  it's Claude judging Claude. The script auto-inserts the right caveat — *total* when no
  non-Claude solver ran (every grade is Claude-on-Claude), *partial* when e.g. Codex is
  present (its rows are the cleaner cross-graded signal). Keep that caveat; don't claim a
  clean head-to-head that the grading setup doesn't support.
- **The SIGTERM hang.** A solve row that exits code 143 is the documented agent-SDK hang
  (`docs/bench-solver-subprocess-hang.md`): the solver *finished its work* but the process
  never exited, so the timeout reaped it. The script flags the row as "killed" with $0/no
  trace — but if its verify row scored normally, the app was built fine. Never report this
  as a solver failure or let it drag down the agent in the narrative; say what happened.
- **Screenshots = only the attached blobs.** The report embeds the content-addressed
  screenshots that `attach_shots.js` attached to the solve rows at run time — those are the
  ones that genuinely belong to the run. Workspaces on disk get overwritten and re-seeded by
  later runs, so PNGs sitting in `bench/workspaces/**` may be from a *different* session.
  **Do not** pull screenshots off disk to fill coverage gaps — note the gap instead (the
  script already does: missing problems/agents get a "no screenshots attached" line).
- **n = 1.** One sweep per cell. Treat ±1–2 rubric points as noise. The script's caveats
  section says this; keep it.

## What the script auto-derives vs. what needs you

| Auto (trust it) | Needs your judgement (the `EDIT` spots) |
|---|---|
| eval selection, problem/phase pairing, agent detection | the headline insight & TL;DR story |
| rubric/static/cost tables + charts | per-problem framing, deduction prose |
| per-bullet deduction list (verifier feedback) | screenshot captions + pruning |
| killed-row + self-grading detection & caveats | cross-run observations |
| screenshot embedding + lightbox | the lede |

## Conventions

- **Output**: `docs/bench-reports/bench-results-<date>.html` (override with `--out`).
- **Agent colors** (consistent everywhere): codex = amber, claude = teal,
  claude-local-mcp = violet, claude-no-skills = gray; unknown agents get a fallback color.
- **Server**: defaults to `http://localhost:15500` (override `--base-url`); blobs read from
  `~/.promptfoo/blobs` (override `--config-dir`). Pure stdlib — no install step.
- The report is one portable file (CSS + base64 screenshots inlined); it needs no network.

## Example

> "Make a report for today's run, eval-Q5b … eval-ayP."

1. `gen_bench_report.py --start eval-Q5b-… --end eval-ayP-…` → writes the HTML, prints
   "agents: claude, claude-local-mcp, claude-no-skills · 1 killed row".
2. That agent set means the run is a **local-vs-hosted MCP A/B** with a no-skills control —
   frame the lede and TL;DR around that, note the killed local-mcp row was a hang (graded
   fine in phase 2), keep the *total* self-grading caveat.
3. Rewrite the deduction callouts (480px bug, Composite<FormLayout>, theme-mixing), caption
   the screenshots, prune duplicates, balance-check, open, then run `gen_index.py` and add the
   README row.
