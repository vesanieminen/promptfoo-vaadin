# agentic-dx benchmark — promptfoo configuration

A [promptfoo](https://www.promptfoo.dev/) port of the
[`agentic-dx-improvement`](../../agentic-dx-improvement) benchmark.

> **Directory.** Lives in `bench/` (renamed from `basic_layout/`, which it outgrew
> once it hosted all three problems). `basic_layout` lives on as one of those problems.

It runs **three problems** (each a Vaadin Flow task, starting from the same Vaadin
skeleton, graded against its own `rubric.md`):

| `PROBLEM` | Task | Rubric max (Vaadin) |
|---|---|---|
| `basic_layout` | responsive view at `/basic_layout` — top/bottom toolbars, scrolling content area, wide vs `<380px` behaviour | 21 (24) |
| `basic_form` | responsive onboarding form at `/basic_form` — 7 sections, 2-col@≥800px / 1-col@<380px, reusable component | 23 (31) |
| `md_ui_spec` | Employees CRUD at `/employees` from a markdown UI spec — grid + drawer, add/edit/delete flows, validation, in-memory service | 41 (48) |

Each problem runs in **two phases**, both as ordinary promptfoo evals. The configs
are PROBLEM-parameterized JavaScript (`.js`, not `.yaml`) so one config set serves
all problems — `run.sh` runs them once per `PROBLEM` (default: all three):

1. **Solve** (`promptfooconfig.js`) — three solvers, as promptfoo's **built-in
   agentic providers**, each edit a fresh workspace:
   - **`codex`** — the Codex CLI (`gpt-5.5`), with the Vaadin skills + docs MCP;
   - **`claude`** — the agentic Claude Code provider (`claude-opus-4-8`), with the
     Vaadin agent-skills plugin + docs MCP;
   - **`claude-no-skills`** — the **baseline**: same `claude` solver, *without* the
     Vaadin skills/MCP, to isolate how much the skills move the rubric.
2. **Verify** (`verify.js`) — one **verifier provider per solved workspace**
   (`anthropic:claude-agent-sdk` + Playwright) runs the app, inspects it across
   viewports, and returns a structured rubric verdict. This phase is
   problem-agnostic: the verifier reads whatever `rubric.md` it's given and
   `grade_verdict.py` normalizes the verdict (21/24, 23/31, or 41/48 all just work).

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
| `problems/base_prompt_vaadin.md` + the "task is in cwd" preamble | inlined as the `prompts:` block in `promptfooconfig.js` (kept in sync with the source file); shared by all problems (all use the Vaadin skeleton) |
| `task.md` + reference PNGs | seeded into each workspace by `seed.js`, read by the agent from its `working_dir` |
| rubric source-verifiable bullets (**Structure** + **Vaadin-specific**, "verify by reading the source") | **`grade_static.py`** (phase 1) — a problem-agnostic harness that dispatches to **`checks/<problem>.py`** for the deterministic source checks (e.g. the route, `FormLayout`/`EmailField`/`Binder`/`ConfirmDialog`, no inline styles, no React/TSX leakage). Also emits the solver-trace columns (below). |
| `verify_task.sh` + `verify_prompt.md` (agentic browser grader) | **`verify.js`** (phase 2) — the verifier as a **provider per workspace**, prompt inlined (port-agnostic) and verdict returned as `output_format` structured output; **`grade_verdict.py`** normalizes it to the per-problem `/max` score |
| `claude-home.sh` (isolated Claude config + Playwright profile) | **gone** — the verifier is a provider now, so it needs no isolated `CLAUDE_CONFIG_DIR`; Playwright isolation is the provider's own `--isolated` MCP |

`bench.js` is the single source of truth for the problem list, the agent list, and
the per-`(problem, agent)` port / workspace layout — imported by both configs and
both seed hooks (the Python graders re-derive the same paths from `PROBLEM`). Each
grader finds its row's workspace from `context['provider']` + `PROBLEM` (`codex` on
`basic_form` → `workspaces/basic_form/codex`, `verify-claude-no-skills` →
`workspaces/<problem>/claude-no-skills`, …).

### Adding a new problem

A new problem is a **drop-in** — no edits to the configs, the seed hooks, or
`grade_verdict.py`. Three required steps (a fourth to run it):

1. **Add the source** to the `agentic-dx-improvement` checkout: a
   `problems/<name>/` dir with `task.md` and `rubric.md` (plus any reference PNGs the
   rubric refers to — `md_ui_spec` ships none, that's fine). The rubric's point total
   can be anything; phase 2 normalizes it.

2. **Register it in `bench.js`** — append `'<name>'` to the `PROBLEMS` array. That is
   all the configs, ports, and workspace paths need. Order matters only for ports:
   each problem reserves 3 consecutive ports from `8081`, and *appending* keeps the
   existing problems' ports stable.

3. **Add `checks/<name>.py`** — the phase-1 static source checks. Export
   `run_checks(ctx)` returning a list of `(name, ok, critical)` tuples (see the API
   and example below). *Optional:* skip it and phase 1 degrades to just the shared
   hygiene checks (with a note) — phase-2 rubric grading still works fully.

4. **Run it:** `PROBLEM=<name> bash bench/run.sh` (or add `<name>` to a
   comma-list, or just run with no `PROBLEM` to include it in the all-problems sweep).

**The `CheckCtx` your `run_checks(ctx)` receives** (built by `grade_static.py` from
the solved `app/`):

| `ctx` member | Returns |
|---|---|
| `ctx.java_src` | all `src/main/java/**/*.java` concatenated (str) |
| `ctx.jhas(substr)` | `True` if the substring appears in the Java source |
| `ctx.jre(pattern)` | `True` if the regex (`re.search`) matches the Java source |
| `ctx.glob_app(pattern)` | solver-authored files matching `pattern` under `app/` (recursive; framework-generated `generated/` and `node_modules/` already filtered out) |
| `ctx.read(path)` | a file's text (or `""`) |
| `ctx.common_hygiene()` | the shared `[(name, ok, critical), …]` Vaadin-hygiene bullets — no inline styles in Java, no inline `style=` in templates, no React/TSX view files — to append to your list |

Each tuple is `(name: str, ok: bool, critical: bool)`. **`critical=True` gates the
row's pass/fail** — keep that to the bare "did the agent produce the required
artifact?" check (e.g. the `@Route`); everything else only contributes to the static
score and shows as PASS/FAIL in the breakdown. (This mirrors the source benchmark and
the phase-2 rubric, where missing a Vaadin idiom is a *deduction*, not a hard fail.)

**Minimal `checks/<name>.py`:**

```python
"""Static source checks for the <name> problem (PHASE 1 gate)."""
def run_checks(ctx):
    checks = [
        ('@Route("<name>") present', ctx.jre(r'@Route\(\s*"<name>"'), True),  # the only gate
        ("uses SomeVaadinComponent",  ctx.jhas("SomeVaadinComponent"),  False),
        ("binds via method references", ctx.jre(r'bind\([^)]*::'),       False),
    ]
    checks += ctx.common_hygiene()   # shared no-inline-styles / no-TSX bullets
    return checks
```

**What's automatic (no edits):** per-`(problem, agent)` ports + namespaced
`workspaces/<name>/<agent>` (`bench.js`); the solve/verify configs, the shared Vaadin
prompt, seeding + rubric strip/restore + the `.reference-images.json` manifest
(`seed.js` / `seed_verify.js`); and **all of phase 2** — the verifier reads your
`rubric.md` and `grade_verdict.py` sums + normalizes whatever sections it returns, so
a 21/24, 23/31, or 41/48 rubric all grade with zero code change.

**Notes:** reference PNGs are auto-excluded from the screenshot galleries (recorded
per workspace in `.reference-images.json`, no hardcoded filenames). All current
problems use the Vaadin skeleton (`TECHSTACK=vaadin`); a different stack would need a
`skeletons/<stack>/` + `base_prompt_<stack>.md` in the checkout (and the shared prompt
revisited).

### What was intentionally skipped (doesn't fit / is redundant in promptfoo)

- **The solver shell** — `solve.sh` / `solve-codex.sh` / `solve-claude.sh` and the
  `CODEX_EFFORT`/`CLAUDE_EFFORT` env machinery are gone; the native providers
  launch and reap the agents. The *model* is still pinned for reproducibility.
- **The subprocess verifier** — `grade_rubric.py`, its retry/timeout/port-freeing
  loop, `VERIFIER_CMD`, and the per-workspace `.claude-home` are gone; the verifier
  is a provider (`verify.js`) and promptfoo owns its lifecycle.
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
  local plugin from `$AGENTIC_DX_DIR/agent-skills` (the `vaadin-skills` plugin:
  skills + the bundled Vaadin docs MCP) — an **absolute** path derived from
  `AGENTIC_DX_DIR`, so it resolves even from a git worktree. For **parity, the `codex` row gets
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
  then `bench/.bench-token` (one line; mode auto-detected by prefix). If none
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

From the **repo root** — or a git worktree (set `AGENTIC_DX_DIR` to an absolute path).
The providers' `working_dir` and the `file://` grader paths resolve relative to each
config's directory:

```bash
# RECOMMENDED — the wrapper warms the Maven cache, then for each PROBLEM runs PHASE 1
# (solve) then PHASE 2 (verify) with --no-cache, and (optionally) injects ONE
# run-scoped Claude credential into the bench PROCESS ONLY. Never touches your rc files.
bash bench/run.sh                          # ALL problems × all agents
npx promptfoo@latest view                         # every problem's solve + verify rows, side by side

PROBLEM=basic_form bash bench/run.sh        # just one problem
PROBLEM=basic_form,md_ui_spec bash bench/run.sh
AGENT=claude,claude-no-skills bash bench/run.sh   # narrow the agent rows (the skills A/B)
VERIFIER=codex bash bench/run.sh                  # grade phase 2 with Codex (default: claude)

# Variance: re-run the whole thing N times (each iteration re-seeds fresh workspaces
# and shows as its own run in `promptfoo view`). Each row is a ~30-min agentic pass,
# and the default is 3 problems × 3 agents × 2 phases — so raise REPEAT knowingly.
REPEAT=3 bash bench/run.sh
```

Seed-only smoke test (no agents / auth / Maven / Playwright, ~2s) — re-seeds a
problem's workspaces and prints its availability manifest
(`workspaces/<problem>/available.json`: agent-skills SHA + skill list +
plugin-declared MCP servers + reachability). Sanity-checks that the
`agentic-dx-improvement` checkout is wired up and shows what skills/MCP **source** a
run will use:

```bash
bash bench/seed.sh                       # default problem (basic_layout)
PROBLEM=md_ui_spec bash bench/seed.sh    # a specific problem
```

Manual equivalent (run one problem's two phases yourself — set `PROBLEM` so the
configs/seed/graders all target the same problem):

```bash
# Optional: pick an auth override (otherwise your Claude Code / Codex login is used):
#   export ANTHROPIC_API_KEY='sk-ant-api03-...'   # OR  CLAUDE_CODE_OAUTH_TOKEN='sk-ant-oat01-...'
( cd "${AGENTIC_DX_DIR:-../agentic-dx-improvement}/skeletons/vaadin" && mvn -q dependency:go-offline )  # warm ~/.m2 once
# --no-cache is REQUIRED: the agentic providers cache by prompt, so without it a
# re-run replays the first run instead of actually solving/verifying.
PROBLEM=basic_form npx promptfoo@latest eval -c bench/promptfooconfig.js --max-concurrency 3 --no-cache  # PHASE 1
PROBLEM=basic_form npx promptfoo@latest eval -c bench/verify.js          --max-concurrency 3 --no-cache  # PHASE 2
```

`--max-concurrency 3` runs all three agent rows at once; safe because each has its
own workspace and baked port. Ports are assigned per `(problem, agent)` from
`bench.js` (`8081..8089`): `basic_layout` `8081/8082/8083`, `basic_form`
`8084/8085/8086`, `md_ui_spec` `8087/8088/8089`. Each run's workspace (the agent's
modified project + logs + `verify-result.json`) lives under
`bench/workspaces/<problem>/<agent>/` (gitignored, recreated each run).

### Concurrency & isolation

Running the rows at once would otherwise collide on a few shared resources; each is
isolated by `seed.js` up front, statically per provider:

| Shared resource | Collision if not isolated | How it's isolated |
|---|---|---|
| **Server port** | All apps bind `8080` | A fixed port per `(problem, agent)` (`bench.portFor` → `8081..8089`) is baked into each workspace's `application.properties` (`server.port=${PORT:808x}`); `seed_verify.js` frees it before the verifier rebuilds. |
| **Workspace files** | One workspace, many agents/problems | One workspace per `(problem, agent)` (`workspaces/<problem>/<agent>`). |
| **Playwright MCP browser** | Browsers share one persistent profile → singleton-lock deadlock | every Playwright MCP registration (solvers and verifiers) uses `--isolated` (in-memory profile). |
| **`~/.m2`** | concurrent *cold* downloads can race | **not** isolated. Warm it once first; concurrent reads of a warm cache are fine. |

## Configuration (env)

| Variable | Default | Purpose |
|---|---|---|
| `AGENTIC_DX_DIR` | _(sibling of the repo)_ | Source of the problems, skeleton, base prompt, rubrics, **and** the `claude` row's agent-skills plugin — all derived from it (`seed.js` / `seed_verify.js` / `promptfooconfig.js`). Set it to an **absolute path** to run from anywhere (e.g. a git worktree); relocating the checkout needs **only** this var — no config edit. |
| `PROBLEM` | _(all)_ | **`run.sh`:** which problem(s) to run — one or a comma-list (`basic_layout`, `basic_form`, `md_ui_spec`); default all. **A bare `eval -c …`:** the single problem this eval targets (default `basic_layout`). |
| `TECHSTACK` | `vaadin` | Skeleton + base-prompt stack |
| `RUBRIC_PASS_THRESHOLD` | `0.6` | Floor (fraction of max) for `grade_verdict.py` to pass |
| `AGENT` | _(all)_ | `run.sh` only: which agent row(s) to run — `codex`, `claude`, `claude-no-skills`, `claude-local-mcp` (comma-list ok) |
| `VERIFIER` | `claude` | PHASE-2 grader: `claude` (`anthropic:claude-agent-sdk`, pinned `claude-opus-4-8`) or `codex` (`openai:codex:gpt-5.5`). Global per run; row labels stay `verify-<solver>`. `codex` grades via its **own** Codex login (`~/.codex/auth.json` / `OPENAI_API_KEY`), needed in addition to the solvers' Claude auth. Phase 1 ignores it. |
| `REPEAT` | `1` | `run.sh` only: re-run the whole solve+verify pipeline N times |
| `MAX_CONCURRENCY` | `3` | `run.sh` only: per-phase `--max-concurrency` (3 = all agent rows at once). Lower it (e.g. `2`) to ease load on the machine / browsers / shared `~/.m2`. |
| `PROMPTFOO_EVAL_TIMEOUT_MS` | `2700000` (45 min/row) | `run.sh` only: per-row wall-clock ceiling — a wedged agentic subprocess is recorded as a timeout and the run moves on (promptfoo's own default is `0` = OFF, which can hang a run indefinitely). Set `=0` to disable. |
| `ANTHROPIC_API_KEY` | _(optional override)_ | **API-key auth mode.** Bills against the API key (solver + verifier); precedence over any login. Inject run-scoped via `run.sh`. |
| `CLAUDE_CODE_OAUTH_TOKEN` | _(optional override)_ | **Subscription auth mode.** For a machine/CI with no Keychain login. Inject run-scoped via `run.sh`. |

## Note

This is separate from the repo-root `promptfooconfig.yaml` (a simple one-shot
Vaadin code-gen eval). They don't interact.
