# `basic_layout` — promptfoo configuration

A [promptfoo](https://www.promptfoo.dev/) port of the **`basic_layout`** benchmark
from the [`agentic-dx-improvement`](../../agentic-dx-improvement) harness.

The task: implement a responsive Vaadin Flow view at `/basic_layout` (top + bottom
toolbars with left/right component groups, a middle scrolling content area, and
specific wide vs `<380px` behaviour), starting from the Vaadin skeleton, then grade
the result against `rubric.md`.

This expresses that task as a promptfoo eval, using promptfoo's **built-in agentic
providers** as the solvers — the same way the repo-root `promptfooconfig.yaml` uses
native providers — instead of bespoke shell. **Two solvers are compared — the
Codex CLI and the agentic Claude Code provider** — and the existing **Claude +
Playwright** verifier grades both.

> ⚠️ **Self-grading caveat.** The grader is a Claude agent. When the **Claude**
> solver's output is graded, Claude is judging Claude's own work. The rubric is
> largely *measurement*-based (viewport positions, scroll behaviour the verifier
> physically observes), so the bias is limited — but treat the Claude row's score
> with that in mind, or set `VERIFIER_CMD` to grade with a different agent.

## How it maps to the harness

| agentic-dx-improvement | promptfoo here |
|---|---|
| `run_task_local.sh` seeds a workspace and runs the solver agent | split in two: **`seed.js`** (a `beforeAll` extension hook) seeds the workspaces; the **native agentic providers** run the agents |
| the solver CLIs (`codex` / `claude` with `--dangerously-…`) | promptfoo's **`openai:codex:gpt-5.5`** and **`anthropic:claude-code`** providers — agentic, full file/command access, Playwright + Vaadin-docs MCP, the Vaadin skills (Claude via the agent-skills plugin, Codex via `.agents/skills/`), subscription auth, **model pinned** (Claude `claude-opus-4-8`, Codex `gpt-5.5`) but otherwise no effort/temperature tuning |
| `problems/base_prompt_vaadin.md` + the "task is in cwd" preamble | inlined as the `prompts:` block in `promptfooconfig.yaml` (kept in sync with the source file) |
| `task.md` + reference PNGs | seeded into each workspace by `seed.js`, read by the agent from its `working_dir` |
| `claude-home.sh` (isolated Claude config + Playwright profile) | folded into `seed.js` — it builds `workspaces/<agent>/.claude-home` with an `--isolated` Playwright MCP for the verifier |
| rubric **Structure** + **Vaadin-specific** sections ("verify by reading the source") | **`grade_static.py`** — deterministic source checks: `@Route("basic_layout")`, `HorizontalLayout`/`VerticalLayout`, `Scroller`, no inline styles, no React/TSX leakage |
| `verify_task.sh` + `verify_prompt.md` (agentic browser grader) | **`grade_rubric.py`** — a custom assertion that runs the same Claude + Playwright verifier in the workspace, parses `verify-result.json`, and returns the normalized `/21` (or `/24`) score |

Each grader finds its row's workspace from `context['provider']` (`codex` →
`workspaces/codex`, `claude` → `workspaces/claude`).

### What was intentionally skipped (doesn't fit / is redundant in promptfoo)

- **The solver shell** — `solve.sh` / `solve-codex.sh` / `solve-claude.sh` and the
  `CODEX_EFFORT`/`CLAUDE_EFFORT` env machinery are gone; the native providers
  launch and reap the agents. The *model* is still pinned (Claude
  `claude-opus-4-8`, Codex `gpt-5.5`) — see the model-defaulting note above.
- **Docker isolation** — solver and grader run on the host (the harness's local
  runner already does this).
- **`format_stream.py` cost/token summary** (the bespoke transcript-parsing
  summary) — promptfoo tracks cost itself; see **Metrics & columns** below for
  what's accurate and what isn't. The watchdog's *intent* is kept:
  `grade_rubric.py` frees the run's port before and after the verifier, so a
  backgrounded dev server can't block `run.sh`.
- **`agent-time-breakdown.json` telemetry** — the verifier produces it by parsing
  the solver's `agent.log.jsonl` stream-json transcript. **The native agentic
  providers don't write that transcript into the workspace**, so under this config
  it comes out empty. The behavioural trace is instead surfaced as **namedScores
  columns** read from the provider response metadata — see below. Per
  [ADR 0002](../../agentic-dx-improvement/docs/adr/0002-rubric-is-a-floor-trace-is-the-signal.md),
  the rubric is a *floor* and the behavioural trace is the real signal — so the
  trace columns are diagnostics, not part of pass/fail.

## Metrics & columns

`grade_rubric.py` emits promptfoo **namedScores** (per-row columns in
`promptfoo view`) in addition to the pass/fail. They don't affect the score or the
threshold — they're the behavioural-trace diagnostics ADR 0002 calls the real
signal:

| Column(s) | Meaning | Source |
|---|---|---|
| `rubric_<section>` | per-section rubric fraction (e.g. `rubric_structure`, `rubric_layout_wide_viewport`) | `verify-result.json` |
| `skill_calls` | Vaadin skills the solver fired (Claude: agent-skills plugin; Codex: `.agents/skills/`) | provider `metadata.skillCalls` |
| `mcp_calls` | MCP tool calls (`mcp__*`, e.g. Playwright) | provider `metadata.toolCalls` |
| `tool_calls` / `tool_errors` | total tool calls / how many returned an error (backtrack proxy) | provider `metadata.toolCalls` |
| `api_archaeology_calls` | Bash calls digging through jars / `javap` / the m2 cache — the "couldn't recall the API" pain signal | provider `metadata.toolCalls` |
| `num_turns` / `solve_seconds` | agent turns / solver wall-clock | provider `metadata.numTurns` / `durationMs` |
| `cache_read_ktokens` / `output_tokens` | real token throughput | provider `metadata.modelUsage` |
| `permission_denials` | denied tool calls (only when > 0) | provider `metadata.permissionDenials` |

These read straight from the row's provider-response metadata
(`context['metadata']`), which promptfoo's `anthropic:claude-code` and
`openai:codex` providers populate — **no `agent.log.jsonl` needed**. A provider
that exposes none of this degrades to just the `rubric_*` columns.

### Cost & token accuracy

**Verified empirically** (read-only `anthropic:claude-code` probe, 2026-06-02 — a
`What is 2+2?` call, comparing promptfoo's reported numbers against the raw SDK
result it wraps):

- **Cost is accurate — trust the `cost` column.** promptfoo's `anthropic:claude-code`
  provider sets the row cost to the Claude Agent SDK's `total_cost_usd` (verified:
  `cost` = `$0.05809475` = raw `total_cost_usd` = `$0.05809475`, to the cent). This
  is the *same* number the bespoke harness's `format_stream.py` reads from the
  stream-json `result` event — same accounting source, structurally identical (an
  empirical "diff" of two *solve* runs can't prove this, since they're stochastic
  and cost different amounts; the probe proves the passthrough directly).
- **The built-in token columns understate throughput — don't use them as the
  efficiency signal.** promptfoo's top-level `tokenUsage` records only input +
  output and **drops cache-read / cache-creation**. In the probe it reported
  **7,597** tokens (`7,594` prompt + `3` completion) while the real usage was
  **~27,094** (`7,594` input + **`17,794` cache-read** + **`1,703` cache-creation** +
  `3` output) — ~72% hidden on a *trivial* call; on a long agentic solve (a real
  basic_form run was 3.1M cache-read vs 65 input) the gap is far larger. The truth
  survives in `metadata.modelUsage`, which the **`cache_read_ktokens` /
  `output_tokens`** columns above surface. Use `cost` (accurate) for efficiency,
  not the token columns.
- **The grader's cost is not counted.** `grade_rubric.py` runs the agentic
  verifier as a subprocess, invisible to promptfoo, so the row cost is the
  **solver only**. The verification pass is a second agentic run of comparable
  cost that the dashboard does not show — budget for ~2× the displayed cost.

## Prerequisites

- The `agentic-dx-improvement` checkout available (default: sibling of this repo;
  override with `AGENTIC_DX_DIR`). Its `agent-skills` submodule
  (`vaadin/agent-skills`) should be populated (`git submodule update --init
  --recursive`) — the Claude provider loads it as a local plugin from
  `../../agentic-dx-improvement/agent-skills` (the `vaadin-skills` plugin: 15
  skills + the bundled Vaadin docs MCP). For **parity, the Codex row gets the same
  skills**: `seed.js` symlinks `workspaces/codex/.agents/skills/` → `agent-skills/
  skills/` (Codex's own skill-discovery location, so submodule edits are always
  live), and the Vaadin docs MCP is added to Codex's `cli_config`. So both agents
  solve with identical Vaadin tooling.
- **The agentic provider SDKs installed where the eval can resolve them.** This is
  easy to miss: promptfoo resolves `@anthropic-ai/claude-agent-sdk` /
  `@openai/codex-sdk` from the *eval's* directory (walking up for `node_modules`),
  **not** from its own bundled copy — so `npx promptfoo` from a repo with no
  `node_modules` errors with *"… could not be resolved from …"*. They're declared
  in the repo-root `package.json`, so install once in the repo root:
  ```bash
  npm install   # installs @anthropic-ai/claude-agent-sdk + @openai/codex-sdk (see package.json)
  ```
- **Codex CLI** signed in (`codex login`) — the Codex solver.
- **Claude auth** — both the solver and the rubric verifier need it, and on macOS
  the verifier's *isolated* `CLAUDE_CONFIG_DIR` (each workspace's `.claude-home`,
  for concurrent-run isolation) can **not** read the Keychain login. So
  `basic_layout/run.sh` resolves **one run-scoped credential** and injects it into
  the bench process only (not your rc files). **You choose the mode** by which
  credential you supply:
  - **Anthropic API key** (`ANTHROPIC_API_KEY=sk-ant-api...`) — bills against the
    API key; the solver **and** the verifier both use it (it takes precedence over
    any Keychain login). Get one at <https://console.anthropic.com/>.
  - **Subscription token** (`CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat...`) — bills against
    your Claude subscription; mint it with `claude setup-token` (interactive).

  Source order (first hit wins): `$ANTHROPIC_API_KEY`, then
  `$CLAUDE_CODE_OAUTH_TOKEN`, then `basic_layout/.bench-token` (one line; the mode
  is auto-detected from its `sk-ant-api` / `sk-ant-oat` prefix). Without any of
  these the rubric assertion scores 0 (*"Verifier did not produce
  verify-result.json"*) while the solver may still succeed off your Keychain login.

  The bench Claude home `.bench-claude-home` must be present (the Playwright MCP
  source `seed.js` copies per-workspace for the verifier).
- JDK 25 + Maven on `PATH`, Node 20.20+/22.22+, and network access (Maven
  downloads, browser).

> The solvers run with full access (Codex `danger-full-access` / Claude
> `bypassPermissions`) so they can edit files, run Maven, and start a server. Run
> only on a trusted machine.

> **Model pinning (reproducibility).** Both solvers pin their model — Claude on
> `claude-opus-4-8` (`config.model`), Codex on `gpt-5.5` (in its provider id) — so
> the numbers are comparable across machines. Without the pin the Claude provider
> would fall back to the *ambient* default model, which varies by machine/login
> (a probe ran on `claude-opus-4-8`, not the `claude-sonnet-4-6` the old shell
> harness used). Edit the pins to benchmark other models.

## Run it

From the **repo root** (the providers' `working_dir` and the `file://` grader paths
resolve relative to this config's directory):

```bash
# RECOMMENDED — the wrapper warms the Maven cache, runs with --no-cache, and injects
# ONE run-scoped Claude credential into the bench PROCESS ONLY (solver + verifier;
# see Prerequisites). Credential source: $ANTHROPIC_API_KEY, else
# $CLAUDE_CODE_OAUTH_TOKEN, else basic_layout/.bench-token (gitignored; either kind,
# detected by prefix). Never touches your rc files.
bash basic_layout/run.sh
npx promptfoo@latest view      # side-by-side: codex vs claude, with rubric scores
```

Manual equivalent (credential still run-scoped — this shell only, not your rc):

```bash
# Pick ONE auth mode:
#   API key  → export ANTHROPIC_API_KEY='sk-ant-api03-...'      # from console.anthropic.com
#   or subscription → `claude setup-token` (interactive; opens a browser), then export
#   the printed sk-ant-oat01-... value. Do NOT redirect setup-token to a file — its UI
#   prints to stdout, so a redirect captures the whole UI, not just the token.
export ANTHROPIC_API_KEY='sk-ant-api03-...'         # OR: export CLAUDE_CODE_OAUTH_TOKEN='sk-ant-oat01-...'
( cd ../agentic-dx-improvement/skeletons/vaadin && mvn -q dependency:go-offline )  # warm ~/.m2 once
# --no-cache is REQUIRED: the agentic providers cache by prompt, so without it a
# second run returns the first run's agent output instead of actually solving.
npx promptfoo@latest eval -c basic_layout/promptfooconfig.yaml --max-concurrency 2 --no-cache
```

`--max-concurrency 2` runs **Codex and Claude at the same time**; this is safe
because each row has its own workspace and port (see below). `AGENTIC_DX_DIR`
defaults to `../agentic-dx-improvement` (correct for a sibling checkout). Each
run's workspace (the agent's modified project + logs + `verify-result.json`) lives
under `basic_layout/workspaces/<agent>/` (gitignored, recreated each run).

### Concurrency & isolation

Running both solvers at once would otherwise collide on a few shared resources;
each is isolated by `seed.js` up front, statically per provider (no per-run
randomness):

| Shared resource | Collision if not isolated | How it's isolated |
|---|---|---|
| **Server port** | Both apps bind `8080` | A fixed port per provider (Codex `8081`, Claude `8082`) is baked into each workspace's `application.properties` (`server.port=${PORT:808x}`); the grader reads it from `.run-port`. |
| **Workspace files** | One workspace, two agents | One workspace per provider (`workspaces/codex`, `workspaces/claude`). |
| **Playwright MCP browser** | Two browsers share one persistent profile → singleton-lock deadlock | every Playwright MCP registration (both solvers and both verifiers) uses `--isolated` (in-memory profile). |
| **Claude config dir** | Concurrent session writes in one config dir | the verifier gets a per-workspace `.claude-home`; the Claude solver uses `setting_sources: []` + an isolated MCP, so it doesn't share state with the verifiers. |
| **`~/.m2`** | concurrent *cold* downloads can race | **not** isolated. Warm it once first, as above; concurrent reads of a warm cache are fine. |

## Configuration (env)

| Variable | Default | Purpose |
|---|---|---|
| `AGENTIC_DX_DIR` | `../agentic-dx-improvement` | Source of the problem, skeleton, base prompt, rubric, verify prompt (used by `seed.js` and the graders). **Note:** the Claude provider's plugin path in `promptfooconfig.yaml` is the literal sibling default — adjust it there too if you relocate the checkout. |
| `PROBLEM` | `basic_layout` | Problem dir name (the config generalizes to other problems) |
| `TECHSTACK` | `vaadin` | Skeleton + base-prompt stack |
| `BENCH_CLAUDE_HOME` | `$AGENTIC_DX_DIR/.bench-claude-home` | Source Claude home (Playwright MCP) `seed.js` copies per-workspace for the verifier |
| `RUBRIC_PASS_THRESHOLD` | `0.6` | Floor (fraction of max) for the rubric assertion to pass |
| `VERIFIER_CMD` | _(unset)_ | Override the grader command (e.g. point at Docker `verify_task.sh`) |
| `ANTHROPIC_API_KEY` | _(one of these two required for the verifier on macOS)_ | **API-key auth mode.** Bills against the API key; both the solver and the rubric verifier use it (precedence over any Keychain login). Inject run-scoped via `run.sh` (env, or an `sk-ant-api...` line in `basic_layout/.bench-token`), not your rc files. |
| `CLAUDE_CODE_OAUTH_TOKEN` | _(the other option)_ | **Subscription auth mode.** What the rubric verifier needs when not using an API key — its isolated `CLAUDE_CONFIG_DIR` can't read the Keychain login. Inject run-scoped via `run.sh` (env, or an `sk-ant-oat...` line in `basic_layout/.bench-token`), not your rc files. |

## Note

This is separate from the repo-root `promptfooconfig.yaml` (a simple one-shot
Vaadin code-gen eval). They don't interact.
