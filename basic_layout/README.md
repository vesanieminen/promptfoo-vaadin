# `basic_layout` — promptfoo configuration

A [promptfoo](https://www.promptfoo.dev/) port of the **`basic_layout`** benchmark
from the [`agentic-dx-improvement`](../../agentic-dx-improvement) harness.

The task: implement a responsive Vaadin Flow view at `/basic_layout` (top + bottom
toolbars with left/right component groups, a middle scrolling content area, and
specific wide vs `<380px` behaviour), starting from the Vaadin skeleton, then grade
the result against `rubric.md`.

It runs in **two phases**, both as ordinary promptfoo evals:

1. **Solve** (`promptfooconfig.yaml`) — three solvers, as promptfoo's **built-in
   agentic providers**, each edit a fresh workspace:
   - **`codex`** — the Codex CLI (`gpt-5.5`), with the Vaadin skills + docs MCP;
   - **`claude`** — the agentic Claude Code provider (`claude-opus-4-8`), with the
     Vaadin agent-skills plugin + docs MCP;
   - **`claude-no-skills`** — the **baseline**: same `claude` solver, *without* the
     Vaadin skills/MCP, to isolate how much the skills move the rubric.
2. **Verify** (`verify.yaml`) — one **verifier provider per solved workspace**
   (`anthropic:claude-agent-sdk` + Playwright) runs the app, inspects it across
   viewports, and returns a structured rubric verdict.

> **Why the verifier is a *provider*, not an assertion.** The verifier is itself an
> agent (it runs the app and drives a browser), so it's modelled as a first-class
> promptfoo provider rather than a subprocess spawned from inside a Python assertion
> (the old `grade_rubric.py`). This closes the "verifier cost is invisible" gap —
> promptfoo now tracks the verifier's cost/tokens/latency as the `verify-*` rows —
> and lets the verdict come back as structured output instead of a disk round-trip.
> See [`docs/ADR-verifier-as-provider.md`](../docs/ADR-verifier-as-provider.md).

> ⚠️ **Self-grading caveat.** The verifier is a Claude agent. When the **`claude`**
> (or **`claude-no-skills`**) solver's output is graded, Claude is judging Claude's
> own work. The rubric is largely *measurement*-based (viewport positions, scroll
> behaviour the verifier physically observes), so the bias is limited — but treat
> those rows' scores with that in mind.

## How it maps to the harness

| agentic-dx-improvement | promptfoo here |
|---|---|
| `run_task_local.sh` seeds a workspace and runs the solver agent | split in two: **`seed.js`** (a `beforeAll` extension) seeds the workspaces; the **native agentic providers** run the agents |
| the solver CLIs (`codex` / `claude` with `--dangerously-…`) | promptfoo's **`openai:codex:gpt-5.5`** and **`anthropic:claude-code`** providers (the latter twice — with and without the Vaadin skills) — agentic, full file/command access, Playwright + Vaadin-docs MCP, the Vaadin skills (Claude via the agent-skills plugin, Codex via `.agents/skills/`), **model pinned** (`claude-opus-4-8` / `gpt-5.5`) but otherwise no effort/temperature tuning |
| `problems/base_prompt_vaadin.md` + the "task is in cwd" preamble | inlined as the `prompts:` block in `promptfooconfig.yaml` (kept in sync with the source file) |
| `task.md` + reference PNGs | seeded into each workspace by `seed.js`, read by the agent from its `working_dir` |
| rubric **Structure** + **Vaadin-specific** sections ("verify by reading the source") | **`grade_static.py`** (phase 1) — deterministic source checks: `@Route("basic_layout")`, `HorizontalLayout`/`VerticalLayout`, `Scroller`, no inline styles, no React/TSX leakage. Also emits the solver-trace columns (below). |
| `verify_task.sh` + `verify_prompt.md` (agentic browser grader) | **`verify.yaml`** (phase 2) — the verifier as a **provider per workspace**, prompt inlined (port-agnostic) and verdict returned as `output_format` structured output; **`grade_verdict.py`** normalizes it to the `/21` (or `/24`) score |
| `claude-home.sh` (isolated Claude config + Playwright profile) | **gone** — the verifier is a provider now, so it needs no isolated `CLAUDE_CONFIG_DIR`; Playwright isolation is the provider's own `--isolated` MCP |

Each grader finds its row's workspace from `context['provider']` (`codex` →
`workspaces/codex`, `verify-claude-no-skills` → `workspaces/claude-no-skills`, …).

### What was intentionally skipped (doesn't fit / is redundant in promptfoo)

- **The solver shell** — `solve.sh` / `solve-codex.sh` / `solve-claude.sh` and the
  `CODEX_EFFORT`/`CLAUDE_EFFORT` env machinery are gone; the native providers
  launch and reap the agents. The *model* is still pinned for reproducibility.
- **The subprocess verifier** — `grade_rubric.py`, its retry/timeout/port-freeing
  loop, `VERIFIER_CMD`, and the per-workspace `.claude-home` are gone; the verifier
  is a provider (`verify.yaml`) and promptfoo owns its lifecycle.
- **Docker isolation** — solver and grader run on the host (the harness's local
  runner already does this).
- **`format_stream.py` cost/token summary** — promptfoo tracks cost itself, and now
  for *both* phases; see **Metrics & columns**.
- **`agent-time-breakdown.json` telemetry** — the harness produced it by parsing the
  solver's `agent.log.jsonl` stream-json transcript, which the native providers
  don't write into the workspace. The behavioural trace is instead surfaced as
  **namedScores columns** from the provider response metadata — see below. Per
  [ADR 0002](../../agentic-dx-improvement/docs/adr/0002-rubric-is-a-floor-trace-is-the-signal.md),
  the rubric is a *floor* and the behavioural trace is the real signal — so neither
  the trace columns nor cost/latency gate pass/fail.

## Metrics & columns

Beyond promptfoo's built-in per-row **cost / latency / tokens** (now shown for the
verifier too, as the `verify-*` rows), the graders emit **namedScores**:

| Column(s) | Phase / row | Meaning | Source |
|---|---|---|---|
| `rubric_<section>` | 2 (`verify-*`) | per-section rubric fraction (`rubric_structure`, `rubric_alignment_wide_viewport`, …) | the verifier's structured verdict |
| `skill_calls` | 1 (solvers) | Vaadin skills the solver fired (Claude: plugin; Codex: `.agents/skills/`) | `metadata.skillCalls` |
| `mcp_calls` | 1 | MCP tool calls (`mcp__*`, e.g. Playwright) | `metadata.toolCalls` |
| `tool_calls` / `tool_errors` | 1 | total tool calls / how many errored (backtrack proxy) | `metadata.toolCalls` |
| `api_archaeology_calls` | 1 | Bash calls digging through jars / `javap` / the m2 cache — the "couldn't recall the API" pain signal | `metadata.toolCalls` |
| `num_turns` / `solve_seconds` | 1 | agent turns / solver wall-clock | `metadata.numTurns` / `durationMs` |
| `cache_read_ktokens` / `output_tokens` | 1 | real token throughput | `metadata.modelUsage` |
| `permission_denials` | 1 | denied tool calls (only when > 0) | `metadata.permissionDenials` |

The phase-1 columns read straight from the solver row's provider-response metadata
(`context['metadata']`), which promptfoo's `anthropic:claude-code` and
`openai:codex` providers populate — **no `agent.log.jsonl` needed**.

### Cost & token accuracy

**Verified empirically** (read-only `anthropic:claude-code` probe, 2026-06-02):

- **Cost is accurate — trust the `cost` column.** promptfoo's `anthropic:claude-code`
  provider sets the row cost to the Claude Agent SDK's `total_cost_usd` (verified to
  the cent). This is the same accounting source the bespoke harness's
  `format_stream.py` read from the stream-json `result` event.
- **The built-in token columns understate throughput — don't use them as the
  efficiency signal.** promptfoo's top-level `tokenUsage` records only input +
  output and **drops cache-read / cache-creation**, which dominate agentic runs
  (a real `basic_form` solve was 3.1M cache-read vs 65 input). The truth survives in
  `metadata.modelUsage`, surfaced as the **`cache_read_ktokens` / `output_tokens`**
  columns. Use `cost` (accurate) for efficiency, not the token columns.
- **The verifier's cost IS now counted** — as the `verify-*` rows. (Under the old
  subprocess design it was invisible and you had to budget ~2× the displayed cost;
  that caveat no longer applies. Total cost ≈ the solver row + its `verify-*` row.)

## Prerequisites

- The `agentic-dx-improvement` checkout available (default: sibling of this repo;
  override with `AGENTIC_DX_DIR`). Its `agent-skills` submodule should be populated
  (`git submodule update --init --recursive`) — the `claude` provider loads it as a
  local plugin from `../../agentic-dx-improvement/agent-skills` (the `vaadin-skills`
  plugin: skills + the bundled Vaadin docs MCP). For **parity, the `codex` row gets
  the same skills**: `seed.js` symlinks `workspaces/codex/.agents/skills/` →
  `agent-skills/skills/`, and the Vaadin docs MCP is added to Codex's `cli_config`.
  The **`claude-no-skills`** row deliberately gets neither (it's the baseline).
- **The agentic provider SDKs installed where the eval can resolve them.** promptfoo
  resolves `@anthropic-ai/claude-agent-sdk` / `@openai/codex-sdk` from the *eval's*
  directory (walking up for `node_modules`), so install once in the repo root:
  ```bash
  npm install   # @anthropic-ai/claude-agent-sdk + @openai/codex-sdk (see package.json)
  ```
- **Codex CLI** signed in (`codex login`) — the `codex` solver.
- **Claude auth.** Both phases are `claude-code` / `claude-agent-sdk` providers, so
  by default they authenticate from your **Claude Code login** (macOS Keychain) — no
  token needed. Unlike the old subprocess verifier, nothing here uses an isolated
  `CLAUDE_CONFIG_DIR`, so a credential is **optional**. Provide one (via `run.sh`)
  only to **override** that:
  - **Anthropic API key** (`ANTHROPIC_API_KEY=sk-ant-api...`) — bills against the API
    key (solver **and** verifier); takes precedence over any login. From
    <https://console.anthropic.com/>.
  - **Subscription token** (`CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat...`) — useful on a
    machine/CI with no Keychain login; mint it with `claude setup-token`.

  Source order (first hit wins): `$ANTHROPIC_API_KEY`, `$CLAUDE_CODE_OAUTH_TOKEN`,
  then `basic_layout/.bench-token` (one line; mode auto-detected by prefix). If none
  is found, `run.sh` warns and relies on your login.
- JDK 25 + Maven on `PATH`, Node 20.20+/22.22+, and network access (Maven
  downloads, browser).

> The solvers run with full access (Codex `danger-full-access` / Claude
> `bypassPermissions`) so they can edit files, run Maven, and start a server. Run
> only on a trusted machine.

> **Model pinning (reproducibility).** Every agent pins its model — Claude rows on
> `claude-opus-4-8`, Codex on `gpt-5.5` — so the numbers are comparable across
> machines. Edit the pins to benchmark other models.

## Run it

From the **repo root** (the providers' `working_dir` and the `file://` grader paths
resolve relative to each config's directory):

```bash
# RECOMMENDED — the wrapper warms the Maven cache, runs PHASE 1 (solve) then PHASE 2
# (verify) with --no-cache, and (optionally) injects ONE run-scoped Claude credential
# into the bench PROCESS ONLY. Never touches your rc files.
bash basic_layout/run.sh
npx promptfoo@latest view      # solve rows + verify rows, side by side

# Variance: re-run the whole solve+verify pipeline N times (each iteration re-seeds
# fresh workspaces and shows as its own run in `promptfoo view`). Each row is a
# ~30-min agentic pass, so raise this knowingly.
REPEAT=3 bash basic_layout/run.sh
```

Manual equivalent (run the two phases yourself):

```bash
# Optional: pick an auth override (otherwise your Claude Code / Codex login is used):
#   export ANTHROPIC_API_KEY='sk-ant-api03-...'   # OR  CLAUDE_CODE_OAUTH_TOKEN='sk-ant-oat01-...'
( cd ../agentic-dx-improvement/skeletons/vaadin && mvn -q dependency:go-offline )  # warm ~/.m2 once
# --no-cache is REQUIRED: the agentic providers cache by prompt, so without it a
# re-run replays the first run instead of actually solving/verifying.
npx promptfoo@latest eval -c basic_layout/promptfooconfig.yaml --max-concurrency 3 --no-cache  # PHASE 1
npx promptfoo@latest eval -c basic_layout/verify.yaml          --max-concurrency 3 --no-cache  # PHASE 2
```

`--max-concurrency 3` runs all three rows at once; safe because each has its own
workspace and baked port (Codex `8081`, Claude `8082`, no-skills `8083`). Each run's
workspace (the agent's modified project + logs + `verify-result.json`) lives under
`basic_layout/workspaces/<agent>/` (gitignored, recreated each run).

### Concurrency & isolation

Running the rows at once would otherwise collide on a few shared resources; each is
isolated by `seed.js` up front, statically per provider:

| Shared resource | Collision if not isolated | How it's isolated |
|---|---|---|
| **Server port** | All apps bind `8080` | A fixed port per provider (`8081`/`8082`/`8083`) is baked into each workspace's `application.properties` (`server.port=${PORT:808x}`); `seed_verify.js` frees it before the verifier rebuilds. |
| **Workspace files** | One workspace, many agents | One workspace per provider (`workspaces/<agent>`). |
| **Playwright MCP browser** | Browsers share one persistent profile → singleton-lock deadlock | every Playwright MCP registration (solvers and verifiers) uses `--isolated` (in-memory profile). |
| **`~/.m2`** | concurrent *cold* downloads can race | **not** isolated. Warm it once first; concurrent reads of a warm cache are fine. |

## Configuration (env)

| Variable | Default | Purpose |
|---|---|---|
| `AGENTIC_DX_DIR` | `../agentic-dx-improvement` | Source of the problem, skeleton, base prompt, rubric (used by `seed.js` / `seed_verify.js`). **Note:** the `claude` provider's plugin path in `promptfooconfig.yaml` is the literal sibling default — adjust it there too if you relocate the checkout. |
| `PROBLEM` | `basic_layout` | Problem dir name (the config generalizes to other problems) |
| `TECHSTACK` | `vaadin` | Skeleton + base-prompt stack |
| `RUBRIC_PASS_THRESHOLD` | `0.6` | Floor (fraction of max) for `grade_verdict.py` to pass |
| `REPEAT` | `1` | `run.sh` only: re-run the whole solve+verify pipeline N times |
| `ANTHROPIC_API_KEY` | _(optional override)_ | **API-key auth mode.** Bills against the API key (solver + verifier); precedence over any login. Inject run-scoped via `run.sh`. |
| `CLAUDE_CODE_OAUTH_TOKEN` | _(optional override)_ | **Subscription auth mode.** For a machine/CI with no Keychain login. Inject run-scoped via `run.sh`. |

## Note

This is separate from the repo-root `promptfooconfig.yaml` (a simple one-shot
Vaadin code-gen eval). They don't interact.
