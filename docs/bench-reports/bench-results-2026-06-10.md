# agentic-DX bench results — 2026-06-10

A single full sweep of the bench: all **3 problems** × **3 solvers** (`codex`,
`claude`, `claude-no-skills`) × **2 phases** (solve + rubric verify). Every row
passed; the interesting signal is in the rubric deductions and the cost spread.

**Eval range** (promptfoo, `localhost:15500`):

| | Problem | Phase 1 — solve | Phase 2 — verify |
|---|---|---|---|
| start | `basic_layout` | [`eval-mVK`](http://localhost:15500/eval/eval-mVK-2026-06-10T07:27:51) 07:27:51 | [`eval-Ypm`](http://localhost:15500/eval/eval-Ypm-2026-06-10T07:41:35) 07:41:35 |
| | `basic_form` | [`eval-uut`](http://localhost:15500/eval/eval-uut-2026-06-10T07:48:35) 07:48:35 | [`eval-v4Y`](http://localhost:15500/eval/eval-v4Y-2026-06-10T08:06:46) 08:06:46 |
| end | `md_ui_spec` | [`eval-W4x`](http://localhost:15500/eval/eval-W4x-2026-06-10T08:17:56) 08:17:56 | [`eval-6HA`](http://localhost:15500/eval/eval-6HA-2026-06-10T08:35:14) 08:35:14 |

Wall-clock: ~07:28 → ~08:43 (~75 min for the whole sweep, runs serialized per problem).

---

## TL;DR

- **Everything passed.** 18 rows (9 solve + 9 verify), all above the `0.6`
  rubric floor. No critical static-check failures, no timeouts, no hangs.
- **Codex graded highest or tied on all three rubrics** (23/24, 31/31, 47/48) —
  *despite* failing more phase-1 static idiom checks (it skipped `setColspan` on
  `basic_form` and `Composite<FormLayout>` on `md_ui_spec`). It wins on observed
  behaviour, loses on Vaadin idiom.
- **Codex is ~2.3× the cost of either Claude solver** ($30.32 vs $13.29 / $10.57
  across the three solves) and **emits no behavioural trace** (turns / tool calls
  / tokens all blank — see caveats).
- **Skills give Claude a small, consistent edge:** `claude` ≥ `claude-no-skills`
  on every problem (+1 rubric point on `basic_layout` and `md_ui_spec`, tie on
  `basic_form`).
- **One systematic bug hit all three agents on `basic_layout`:** the responsive
  breakpoint is `max-width: 379.98px`, so at the rubric's **480px** narrow
  viewport the toolbars never switch to stacked mode. Every solver lost the
  narrow-viewport bullets to the same root cause.

---

## Rubric scores (phase 2 — the headline)

Normalized fraction of each problem's rubric max. All verifiers are
`anthropic:claude-agent-sdk` + Playwright agents that run the app and measure it.

| Problem (max) | `codex` | `claude` | `claude-no-skills` |
|---|---|---|---|
| `basic_layout` (24) | **23/24 — 0.958** | 22/24 — 0.917 | 21/24 — 0.875 |
| `basic_form` (31) | **31/31 — 1.000** | 29/31 — 0.935 | 29/31 — 0.935 |
| `md_ui_spec` (48) | **47/48 — 0.979** | **47/48 — 0.979** | 46/48 — 0.958 |

> ⚠️ **Self-grading caveat.** The `claude` and `claude-no-skills` rows are graded
> by a Claude verifier judging Claude's own output. The rubric is largely
> measurement-based (the verifier physically observes viewport positions / scroll
> behaviour), so bias is limited — but the `codex` rows are *cross*-graded
> (Claude verifier on Codex output) and so are the cleaner comparison.

## Static checks (phase 1 — source idiom gate)

Deterministic source reads. `critical` checks gate pass/fail (only the `@Route`);
the rest are deductions. **No critical failure occurred.**

| Problem (checks) | `codex` | `claude` | `claude-no-skills` |
|---|---|---|---|
| `basic_layout` (7) | 7/7 | 7/7 | 7/7 |
| `basic_form` (15) | 13/15 | 14/15 | 14/15 |
| `md_ui_spec` (19) | 17/19 | 17/19 | 17/19 |

## Cost

`cost` is accurate (the Agent SDK / Codex `total_cost_usd`). Grand total for the
sweep: **$90.78** — $54.18 solve + $36.60 verify.

| Agent | solve | verify | total |
|---|---|---|---|
| `codex` | $30.32 | $12.28 | **$42.60** |
| `claude` | $13.29 | $11.87 | **$25.17** |
| `claude-no-skills` | $10.57 | $12.45 | **$23.02** |

---

## Per-problem detail

### `basic_layout` — responsive toolbar view (rubric max 24)

**Solve (phase 1):**

| Agent | static | cost | wall | turns | mcp | tool (err) | api-arch | cache-read | out-tok |
|---|---|---|---|---|---|---|---|---|---|
| `codex` | 7/7 | $5.32 | — | — | — | — | — | — | — |
| `claude` | 7/7 | $3.76 | 819s | 79 | 26 | 77 (8) | 0 | 4727 kt | 29.7 k |
| `claude-no-skills` | 7/7 | $1.49 | 299s | 43 | 12 | 42 (3) | 2 | 1731 kt | 16.2 k |

**Rubric (phase 2):** `codex` 23/24 · `claude` 22/24 · `claude-no-skills` 21/24.

**The shared deduction — narrow-viewport breakpoint.** All three solvers nailed
Structure, wide-viewport alignment, content area, and Vaadin idiom, and lost
points only in **Alignment (narrow viewport)**:

- The CSS mobile breakpoint is `@media (max-width: 379.98px)`. The rubric tests
  **320 / 375 / 480**. At 480px the toolbars stay in row mode, so the two button
  groups don't stack onto separate rows and items don't grow to fill the row.
- `claude` & `codex`: held at 320/375, failed at 480 (−2 and −1 respectively).
- `claude-no-skills`: same, **plus** a horizontal scrollbar at 480px (groups'
  intrinsic width ≈517px > 480px → page `scrollWidth` 525 > 480) — costing it the
  extra Scrolling point (4/5) that the other two kept.

**Skills delta:** `claude` 22 vs `claude-no-skills` 21 (+1). Note `claude` spent
2.5× the cost and 2.7× the wall-clock for that single point.

### `basic_form` — responsive onboarding form (rubric max 31)

**Solve (phase 1):**

| Agent | static | cost | wall | turns | mcp | tool (err) | cache-read | out-tok |
|---|---|---|---|---|---|---|---|---|
| `codex` | 13/15 | $12.55 | — | — | — | — | — | — |
| `claude` | 14/15 | $3.05 | 552s | 45 | 19 | 44 (4) | 3158 kt | 37.1 k |
| `claude-no-skills` | 14/15 | $2.87 | 543s | 51 | 12 | 50 (4) | 2638 kt | 36.1 k |

Static fails: `codex` missed `setColspan` and tripped the no-inline-styles
hygiene check; both Claude rows tripped only no-inline-styles.

**Rubric (phase 2):** `codex` **31/31 (perfect)** · `claude` 29/31 ·
`claude-no-skills` 29/31.

- **`claude` (−2):** the *Emergency contact* section shrinks to 704px
  (`.onboarding-form` uses `align-items: flex-start`, section not forced full
  width), so its two-column edges sit 48–96px off the other five sections. Cost
  the matching Layout + Vaadin-specific (colspan-alignment) bullets.
- **`claude-no-skills` (−2):** the Aura **radio/checkbox orientation** trap — the
  T-shirt-size radio group and both checkbox groups render *vertical* but the
  mockup wants horizontal. Vaadin 25 Aura defaults group `flex-direction: column`
  and `removeThemeName('vertical')` is a no-op there; the fix is a CSS/theme
  override. (See repo memory: *Aura radio/checkbox group vertical default*.)
- **`codex`:** clean sweep — including the radio/checkbox orientation the Claude
  baseline missed.

**Skills delta:** tie (29 = 29). Interesting: `claude` fired **0** skills on this
problem yet still matched the baseline; its 2 lost points were a different defect
than the baseline's, so skills neither helped nor hurt here.

### `md_ui_spec` — Employees CRUD from a markdown spec (rubric max 48)

**Solve (phase 1):**

| Agent | static | cost | wall | turns | mcp | tool (err) | api-arch | cache-read | out-tok |
|---|---|---|---|---|---|---|---|---|---|
| `codex` | 17/19 | $12.46 | — | — | — | — | — | — | — |
| `claude` | 17/19 | $6.48 | 849s | 71 | 30 | 68 (7) | 7 | 7203 kt | 54.5 k |
| `claude-no-skills` | 17/19 | $6.21 | 1032s | 95 | 27 | 94 (5) | 11 | 7837 kt | 59.7 k |

This was the hardest problem — highest turn counts, most tool calls, and the most
"API archaeology" (digging through jars / `javap` for an API the agent couldn't
recall): `claude-no-skills` 11, `claude` 7, vs ~0–2 on the simpler problems.

**Rubric (phase 2):** `claude` **47/48** · `codex` **47/48** · `claude-no-skills`
46/48. The single lost point differs per agent:

- **`claude` (−1):** the **EmailField** shows a red invalid indicator but **no
  message text** (empty `errorMessage`, error slot hidden) — the only invalid
  field without an explanatory message. (See repo memory: *EmailField i18n
  overrides Binder EmailValidator message*.)
- **`codex` (−1):** `EmployeeForm extends FormLayout` directly instead of
  `Composite<FormLayout>` — the same gap flagged in its static checks.
- **`claude-no-skills` (−2):** the drawer renders **385px** wide, not the spec's
  400px (`setWidth("400px")` is correct but `drawer.setFlexShrink(0)` is a no-op
  — that overload sets shrink on the *varargs* children, not the drawer); plus
  the same `Composite<FormLayout>` miss as Codex.

**Skills delta:** `claude` 47 vs `claude-no-skills` 46 (+1), and skills also cut
the API-archaeology pain (7 vs 11 jar-digging Bash calls) and finished ~3 min
faster despite a near-identical token budget.

---

## Cross-cutting observations

1. **Codex grades best but writes the least idiomatic Vaadin.** It topped or tied
   every rubric, yet it's the one that skipped `setColspan` and
   `Composite<FormLayout>`. The rubric rewards *observed behaviour*; the static
   checks catch *idiom*. They disagree, and that's the point of running both.

2. **The 480px breakpoint bug is a benchmark-level finding, not an agent one.**
   All three agents independently chose `max-width: 379.98px` and all three lost
   the same narrow-viewport bullets at 480px. Either the task/skeleton nudges
   toward that breakpoint or 480px-as-"narrow" is underspecified in the task. Worth
   a look before reading too much into the `basic_layout` spread.

3. **Skills are a small but real positive for Claude** (+1, +0, +1) and reduce
   API-archaeology thrash on the hard problem — at a meaningful cost/time premium.
   The headline skills-vs-no-skills story is unchanged from prior runs: modest,
   consistent, never negative.

4. **Cost ranking is stable:** `codex` ≫ `claude` ≳ `claude-no-skills` on solve;
   verify costs are within ~$0.50 of each other per problem (the verifier is the
   same agent regardless of whose work it grades).

## Caveats & data gaps

- **Codex emits no behavioural trace.** Every `codex` solve row has blank
  `solve_seconds` / `num_turns` / `mcp_calls` / token columns — the
  `openai:codex` provider doesn't populate the metadata the Claude provider does.
  Only `cost` is reliable for Codex. The trace comparison is Claude-vs-Claude only.
- **Self-grading** applies to the two Claude solver rows (see caveat above). The
  `codex` rubric numbers are the cleanest cross-graded signal.
- **Token columns understate throughput** by design (cache-read/creation dropped
  from the top-level total); `cache_read_ktokens` / `output_tokens` above are the
  real figures from `metadata.modelUsage`. Use `cost`, not tokens, for efficiency.
- **n = 1 per cell.** This is a single sweep — treat ±1 rubric point as noise, not
  a ranking. Re-run with `REPEAT=N` for variance before drawing hard conclusions.

---

*Source: promptfoo evals `eval-mVK` … `eval-6HA` on `localhost:15500`,
2026-06-10. Generated from the eval JSON via the bench's two-phase
solve/verify pipeline (`bench/README.md`).*
