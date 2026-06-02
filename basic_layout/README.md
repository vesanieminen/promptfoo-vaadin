# `basic_layout` — promptfoo configuration

A [promptfoo](https://www.promptfoo.dev/) port of the **`basic_layout`** benchmark
from the [`agentic-dx-improvement`](../../agentic-dx-improvement) harness.

The task: implement a responsive Vaadin Flow view at `/basic_layout` (top + bottom
toolbars with left/right component groups, a middle scrolling content area, and
specific wide vs `<380px` behaviour), starting from the Vaadin skeleton, then grade
the result against `rubric.md`.

This expresses that task as a promptfoo eval so it can be run/compared with
promptfoo instead of the bespoke shell harness. **Two solvers are compared —
Codex CLI and Claude Code CLI** — and the existing **Claude + Playwright** verifier
grades both.

> ⚠️ **Self-grading caveat.** The grader is a Claude agent. When the **Claude**
> solver's output is graded, Claude is judging Claude's own work. The rubric is
> largely *measurement*-based (viewport positions, scroll behaviour the verifier
> physically observes), so the bias is limited — but treat the Claude row's score
> with that in mind, or set `VERIFIER_CMD` to grade with a different agent.

## How it maps to the harness

| agentic-dx-improvement | promptfoo here |
|---|---|
| `run_task_local.sh` seeds a workspace and runs the solver agent | **`solve.sh`** (driven by `SOLVER_AGENT=codex\|claude`): copies the skeleton + problem files into a fresh writable workspace, strips `rubric.md`, runs `codex exec` **or** `claude` in it, and prints `{workspace, app, final}` JSON — the provider output. The thin wrappers **`solve-codex.sh`** / **`solve-claude.sh`** are the two `exec:` providers |
| `problems/base_prompt_vaadin.md` + the "task is in cwd" preamble | inlined as the `prompts:` block in `promptfooconfig.yaml` (kept in sync with the source file) |
| `task.md` + reference PNGs | seeded into the workspace by `solve.sh`, read by the agent from its cwd |
| rubric **Structure** + **Vaadin-specific** sections ("verify by reading the source") | **`grade_static.py`** — deterministic source checks: `@Route("basic_layout")`, `HorizontalLayout`/`VerticalLayout`, `Scroller`, no inline styles, no React/TSX leakage |
| `verify_task.sh` + `verify_prompt.md` (agentic browser grader) | **`grade_rubric.py`** — a custom assertion that runs the same Claude + Playwright verifier in the workspace, parses `verify-result.json`, and returns the normalized `/21` (or `/24`) score |

### What was intentionally skipped (doesn't fit / is redundant in promptfoo)

- **Docker isolation** — promptfoo runs the provider/grader directly. Solver and
  grader run on the host (the harness's local runner already does this).
- **Keychain / credential plumbing** — `codex` uses its own `codex login`; the
  Claude verifier uses `CLAUDE_CODE_OAUTH_TOKEN` / its config dir.
- **`format_stream.py` cost/token summary** — promptfoo tracks cost itself. (The
  watchdog's *intent* is kept: each solver runs as its own process group and is
  reaped — and its per-run port freed — on exit, so a backgrounded dev server can't
  block the grader's `run.sh`.)
- **`agent-time-breakdown.json` telemetry** — the verifier still produces it (it's
  in `verify_prompt.md`); it's preserved in the workspace as an artifact but is
  **not** part of the promptfoo pass/fail. Per
  [ADR 0002](../../agentic-dx-improvement/docs/adr/0002-rubric-is-a-floor-trace-is-the-signal.md),
  the rubric is a *floor* and the behavioural trace is the real signal — the full
  run lives under `runs/…` for that analysis.

## Prerequisites

- The `agentic-dx-improvement` checkout available (default: sibling of this repo;
  override with `AGENTIC_DX_DIR`). Its Vaadin plugin submodule should be populated
  (`git submodule update --init --recursive`).
- **Codex CLI** signed in (`codex login`) — the Codex solver.
- **Claude CLI** + the harness's isolated config dir `.bench-claude-home` (with the
  Playwright MCP + Vaadin plugin registered, as `run_task_local.sh` sets up) — used
  by **both** the Claude solver and the grader. Auth via `CLAUDE_CODE_OAUTH_TOKEN`
  (`claude setup-token`).
- JDK 25 + Maven on `PATH`, and network access (Maven downloads, browser).

> The solvers run with full access (`codex --dangerously-bypass-approvals-and-sandbox`
> / `claude --dangerously-skip-permissions`) so they can edit files, run Maven, and
> start a server. Run only on a trusted machine.

## Run it

From the **repo root** (the `exec:` provider paths are relative to where you launch
promptfoo; the `file://` grader paths are relative to this config):

```bash
# Needed for both the Claude solver and the Claude grader:
export CLAUDE_CODE_OAUTH_TOKEN="$(claude setup-token)"

# Warm the Maven cache ONCE first (shared ~/.m2 is the one un-isolated resource —
# concurrent cold downloads can race). Skip if you've built this skeleton before:
( cd ../agentic-dx-improvement/skeletons/vaadin && mvn -q dependency:go-offline )

npx promptfoo@latest eval -c basic_layout/promptfooconfig.yaml --max-concurrency 2
npx promptfoo@latest view      # side-by-side: codex vs claude, with rubric scores
```

`--max-concurrency 2` runs **Codex and Claude at the same time**. This is safe
because every run is isolated (see below). `AGENTIC_DX_DIR` defaults to
`../agentic-dx-improvement` (correct for a sibling checkout). Each run's workspace
(the agent's modified project + logs + `verify-result.json`) is written under
`basic_layout/runs/basic_layout/vaadin/<agent>/<timestamp>/` (gitignored).

### Concurrency & isolation

Running both solvers at once means several things would otherwise collide. Each is
isolated per run:

| Shared resource | Collision if not isolated | How it's isolated |
|---|---|---|
| **Server port** | Both apps bind `8080` | A free port is picked per run and exported as `PORT`; the skeleton's `application.properties` already does `server.port=${PORT:8080}`, so `dev.sh`/`run.sh` move off 8080. The port is recorded in `<workspace>/.run-port` and passed to both the solver (prompt note) and the grader (`PORT` env + a verify-prompt override). |
| **Claude config dir** | Concurrent `.claude.json` / session writes in one `.bench-claude-home` | `claude-home.sh` copies it to `<workspace>/.claude-home` per run. |
| **Playwright MCP browser** | Two browsers share one persistent profile → singleton-lock deadlock | the per-workspace MCP is re-registered with `--isolated` (in-memory profile) + a per-workspace `--output-dir`. |
| **Workspace files** | — | already unique per run (`<agent>/<timestamp>-<pid>`). |
| **`~/.m2`** | concurrent *cold* downloads can race | **not** isolated (isolating would mean re-downloading per run). Warm it once first, as above; concurrent reads of a warm cache are fine. |

After each solver finishes, its process group is reaped and its port freed (before
grading); the grader likewise reaps its verifier's app server and frees the port.

## Configuration (env)

| Variable | Default | Purpose |
|---|---|---|
| `AGENTIC_DX_DIR` | `../agentic-dx-improvement` | Source of the problem, skeleton, base prompt, rubric, verify prompt |
| `PROBLEM` | `basic_layout` | Problem dir name (the config generalizes to other problems) |
| `TECHSTACK` | `vaadin` | Skeleton + base-prompt stack |
| `SOLVER_AGENT` | `codex` | Which agent solves (`codex`\|`claude`); set by the `solve-*.sh` wrappers |
| `CODEX_MODEL` | _(CLI default)_ | Pin the Codex solver model for reproducibility |
| `CODEX_EFFORT` | `medium` | `model_reasoning_effort` for the Codex solver |
| `CLAUDE_MODEL` | _(CLI default)_ | Pin the Claude solver model (full id preferred over an alias) |
| `CLAUDE_EFFORT` | _(CLI default)_ | `--effort` for the Claude solver (Opus-family) |
| `RUBRIC_PASS_THRESHOLD` | `0.6` | Floor (fraction of max) for the rubric assertion to pass |
| `VERIFIER_CMD` | _(unset)_ | Override the grader command (e.g. point at Docker `verify_task.sh`) |
| `BENCH_CLAUDE_HOME` | `$AGENTIC_DX_DIR/.bench-claude-home` | Source Claude home (Vaadin plugin + Playwright MCP) copied per-run by `claude-home.sh` |

> Note: `CLAUDE_CONFIG_DIR` is **derived per run** (`<workspace>/.claude-home`), not
> set by you — that's what makes parallel Claude runs safe. Override the *source* it
> copies from with `BENCH_CLAUDE_HOME`.

## Note

This is separate from the repo-root `promptfooconfig.yaml` (a simple one-shot
Vaadin code-gen eval). They don't interact.
