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
| the solver CLIs (`codex` / `claude` with `--dangerously-…`) | promptfoo's **`openai:codex:gpt-5.5`** and **`anthropic:claude-code`** providers — agentic, full file/command access, Playwright MCP, subscription auth, **no model env knobs** (config is operational only) |
| `problems/base_prompt_vaadin.md` + the "task is in cwd" preamble | inlined as the `prompts:` block in `promptfooconfig.yaml` (kept in sync with the source file) |
| `task.md` + reference PNGs | seeded into each workspace by `seed.js`, read by the agent from its `working_dir` |
| `claude-home.sh` (isolated Claude config + Playwright profile) | folded into `seed.js` — it builds `workspaces/<agent>/.claude-home` with an `--isolated` Playwright MCP for the verifier |
| rubric **Structure** + **Vaadin-specific** sections ("verify by reading the source") | **`grade_static.py`** — deterministic source checks: `@Route("basic_layout")`, `HorizontalLayout`/`VerticalLayout`, `Scroller`, no inline styles, no React/TSX leakage |
| `verify_task.sh` + `verify_prompt.md` (agentic browser grader) | **`grade_rubric.py`** — a custom assertion that runs the same Claude + Playwright verifier in the workspace, parses `verify-result.json`, and returns the normalized `/21` (or `/24`) score |

Each grader finds its row's workspace from `context['provider']` (`codex` →
`workspaces/codex`, `claude` → `workspaces/claude`).

### What was intentionally skipped (doesn't fit / is redundant in promptfoo)

- **The solver shell** — `solve.sh` / `solve-codex.sh` / `solve-claude.sh` and the
  `CODEX_MODEL`/`CODEX_EFFORT`/`CLAUDE_MODEL`/`CLAUDE_EFFORT` env machinery are gone;
  the native providers launch and reap the agents and use their default models.
- **Docker isolation** — solver and grader run on the host (the harness's local
  runner already does this).
- **`format_stream.py` cost/token summary** — promptfoo tracks cost itself. The
  watchdog's *intent* is kept: `grade_rubric.py` frees the run's port before and
  after the verifier, so a backgrounded dev server can't block `run.sh`.
- **`agent-time-breakdown.json` telemetry** — the verifier still produces it; it's
  preserved in the workspace as an artifact but is **not** part of the promptfoo
  pass/fail. Per
  [ADR 0002](../../agentic-dx-improvement/docs/adr/0002-rubric-is-a-floor-trace-is-the-signal.md),
  the rubric is a *floor* and the behavioural trace is the real signal.

## Prerequisites

- The `agentic-dx-improvement` checkout available (default: sibling of this repo;
  override with `AGENTIC_DX_DIR`). Its Vaadin plugin submodule should be populated
  (`git submodule update --init --recursive`) — the Claude provider loads it from
  `../../agentic-dx-improvement/claude-plugin`.
- **Codex CLI** signed in (`codex login`) — the Codex solver.
- **Claude CLI** signed in, with the bench Claude home `.bench-claude-home` present
  (the Playwright MCP source `seed.js` copies for the verifier). Auth via
  `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`) — used by the Claude solver and
  the grader.
- JDK 25 + Maven on `PATH`, Node 20.20+/22.22+ (for the bundled agentic SDKs), and
  network access (Maven downloads, browser).

> The solvers run with full access (Codex `danger-full-access` / Claude
> `bypassPermissions`) so they can edit files, run Maven, and start a server. Run
> only on a trusted machine.

## Run it

From the **repo root** (the providers' `working_dir` and the `file://` grader paths
resolve relative to this config's directory):

```bash
# Needed for both the Claude solver and the Claude grader:
export CLAUDE_CODE_OAUTH_TOKEN="$(claude setup-token)"

# Warm the Maven cache ONCE first (shared ~/.m2 is the one un-isolated resource —
# concurrent cold downloads can race). Skip if you've built this skeleton before:
( cd ../agentic-dx-improvement/skeletons/vaadin && mvn -q dependency:go-offline )

# --no-cache is REQUIRED: the agentic providers cache by prompt, so without it a
# second run returns the first run's agent output instead of actually solving.
npx promptfoo@latest eval -c basic_layout/promptfooconfig.yaml --max-concurrency 2 --no-cache
npx promptfoo@latest view      # side-by-side: codex vs claude, with rubric scores
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
| `CLAUDE_CODE_OAUTH_TOKEN` | _(required)_ | Subscription auth for the Claude solver + grader |

## Note

This is separate from the repo-root `promptfooconfig.yaml` (a simple one-shot
Vaadin code-gen eval). They don't interact.
