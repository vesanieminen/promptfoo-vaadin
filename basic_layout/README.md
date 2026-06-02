# `basic_layout` — promptfoo configuration

A [promptfoo](https://www.promptfoo.dev/) port of the **`basic_layout`** benchmark
from the [`agentic-dx-improvement`](../../agentic-dx-improvement) harness.

The task: implement a responsive Vaadin Flow view at `/basic_layout` (top + bottom
toolbars with left/right component groups, a middle scrolling content area, and
specific wide vs `<380px` behaviour), starting from the Vaadin skeleton, then grade
the result against `rubric.md`.

This expresses that task as a promptfoo eval so it can be run/compared with
promptfoo instead of the bespoke shell harness. The **Codex CLI** solves the task;
the existing **Claude + Playwright** verifier grades it.

## How it maps to the harness

| agentic-dx-improvement | promptfoo here |
|---|---|
| `run_task_local.sh` seeds a workspace and runs the solver agent | **`solve.sh`** (an `exec:` provider): copies the skeleton + problem files into a fresh writable workspace, strips `rubric.md`, runs `codex exec` in it, and prints `{workspace, app, final}` JSON — the provider output |
| `problems/base_prompt_vaadin.md` + the "task is in cwd" preamble | inlined as the `prompts:` block in `promptfooconfig.yaml` (kept in sync with the source file) |
| `task.md` + reference PNGs | seeded into the workspace by `solve.sh`, read by the agent from its cwd |
| rubric **Structure** + **Vaadin-specific** sections ("verify by reading the source") | **`grade_static.py`** — deterministic source checks: `@Route("basic_layout")`, `HorizontalLayout`/`VerticalLayout`, `Scroller`, no inline styles, no React/TSX leakage |
| `verify_task.sh` + `verify_prompt.md` (agentic browser grader) | **`grade_rubric.py`** — a custom assertion that runs the same Claude + Playwright verifier in the workspace, parses `verify-result.json`, and returns the normalized `/21` (or `/24`) score |

### What was intentionally skipped (doesn't fit / is redundant in promptfoo)

- **Docker isolation** — promptfoo runs the provider/grader directly. Solver and
  grader run on the host (the harness's local runner already does this).
- **Keychain / credential plumbing** — `codex` uses its own `codex login`; the
  Claude verifier uses `CLAUDE_CODE_OAUTH_TOKEN` / its config dir.
- **`format_stream.py` cost/token summary + watchdog** — promptfoo tracks cost and
  manages process lifecycle itself.
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
- **Codex CLI** signed in (`codex login`) — the solver.
- **Claude CLI** + the harness's isolated config dir `.bench-claude-home` (with the
  Playwright MCP + Vaadin plugin registered, as `run_task_local.sh` sets up) — the
  grader. Auth via `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`).
- JDK 25 + Maven on `PATH`, and network access (Maven downloads, browser).

> `solve.sh` runs Codex with `--dangerously-bypass-approvals-and-sandbox` (the
> analog of the harness's `claude --dangerously-skip-permissions`) so it can edit
> files, run Maven, and start a server. Run only on a trusted machine.

## Run it

From the **repo root** (the `exec:` provider path is relative to where you launch
promptfoo; the `file://` grader paths are relative to this config):

```bash
AGENTIC_DX_DIR=../agentic-dx-improvement \
  npx promptfoo@latest eval -c basic_layout/promptfooconfig.yaml --max-concurrency 1
npx promptfoo@latest view
```

Each run's workspace (the agent's modified project + logs + `verify-result.json`)
is written under `basic_layout/runs/basic_layout/vaadin/<timestamp>/` (gitignored).

## Configuration (env)

| Variable | Default | Purpose |
|---|---|---|
| `AGENTIC_DX_DIR` | `../agentic-dx-improvement` | Source of the problem, skeleton, base prompt, rubric, verify prompt |
| `PROBLEM` | `basic_layout` | Problem dir name (the config generalizes to other problems) |
| `TECHSTACK` | `vaadin` | Skeleton + base-prompt stack |
| `CODEX_MODEL` | _(CLI default)_ | Pin the solver model for reproducibility |
| `CODEX_EFFORT` | `medium` | `model_reasoning_effort` for the solver |
| `RUBRIC_PASS_THRESHOLD` | `0.6` | Floor (fraction of max) for the rubric assertion to pass |
| `VERIFIER_CMD` | _(unset)_ | Override the grader command (e.g. point at Docker `verify_task.sh`) |
| `CLAUDE_CONFIG_DIR` | `$AGENTIC_DX_DIR/.bench-claude-home` | Isolated Claude home with Playwright MCP for the grader |

## Note

This is separate from the repo-root `promptfooconfig.yaml` (a simple one-shot
Vaadin code-gen eval). They don't interact.
