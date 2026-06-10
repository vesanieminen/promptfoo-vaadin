# ADR: The rubric verifier is a provider, not an assertion

**Status:** accepted · **Date:** 2026-06-08 · **Scope:** `bench/`

## Context

The `basic_layout` benchmark has two agentic stages: a **solver** produces a
Vaadin app in a workspace, and a **verifier** runs that app, drives Playwright
across viewports, and scores it against `rubric.md`.

The first promptfoo port modelled the solver correctly — as a native agentic
provider (`anthropic:claude-code`, `openai:codex`) — but modelled the **verifier
as a Python assertion** (`grade_rubric.py`) that shelled out to a `claude`
subprocess inside the workspace. That inverts promptfoo's model, where *providers*
do agentic work and *assertions* are cheap checks on what a provider returned.

Consequences of the inversion:

- **The verifier's cost/tokens/latency were invisible.** promptfoo can't see into
  a subprocess spawned from an assertion, so ~half of every run's cost was off the
  books — a real measurement gap for a benchmark whose point *is* DX cost.
- **~400 lines re-implemented the provider runner** — timeout, retries, port
  freeing, isolated `CLAUDE_CONFIG_DIR`, stream-json log capture.
- **A class of silent-zero failures** ("did the verifier write
  `verify-result.json`?") we had to harden against more than once.
- The verdict was a **disk round-trip** instead of a return value.

## Decision

Model the verifier as what it is: a **provider**. Split the eval into two phases:

| Phase | Config | What runs |
|---|---|---|
| 1 — solve | `promptfooconfig.yaml` | solver providers → `workspaces/<agent>/app` |
| 2 — verify | `verify.yaml` | one `claude-agent-sdk` **verifier provider per workspace** → structured verdict |

- One verifier provider per solved workspace (`verify-codex`, `verify-claude`,
  `verify-claude-no-skills`), each with a fixed `working_dir`. The "which workspace
  am I grading?" question is answered by *which provider row it is* — no per-row
  dynamic `working_dir` needed.
- The verdict comes back as **structured output** (`output_format`, the rubric JSON
  schema), parsed in the response. `grade_verdict.py` shrank to a ~30-line score
  check (with a `verify-result.json` fallback the prompt still writes, for a
  human-readable trail and belt-and-suspenders).
- `run.sh` runs phase 1 then phase 2; `seed_verify.js` (a phase-2 `beforeAll`)
  restores `rubric.md` into each workspace and frees the baked port.

### Why not `llm-rubric` + a custom grading provider?

`llm-rubric` feeds its grader plain *text* via the Messages API — it can't start a
server or drive Playwright — and a grading provider's `working_dir` is static, so
it can't vary per row. "Verifier as its own provider, one per workspace" sidesteps
both. Verification here is provider-shaped work; it doesn't belong on the grader
side of the line.

## Consequences

- **Verifier cost/tokens/latency are now native promptfoo columns** (the `verify-*`
  rows) — the hidden-cost gap is closed.
- promptfoo owns retries/timeout/concurrency; `grade_rubric.py` is **deleted**.
- The per-workspace `.claude-home` (isolated `CLAUDE_CONFIG_DIR` for the subprocess)
  is **gone** — the provider authenticates from the Claude Code login or an env
  token, so `run.sh`'s credential injection is now **optional** (only for API-key
  billing or login-less CI), not required.
- The SOLVER's behavioural-trace columns moved to `grade_static.py` (phase 1),
  since the phase-2 rows' metadata describes the verifier, not the solver.

Unchanged: ADR 0002 still holds — the rubric is a **floor**, the behavioural trace
is the real signal. Neither cost nor trajectory gates pass/fail.

### Not done (deliberately)

- A plain-LLM "Tier-0" baseline doesn't fit — a text-only model produces no
  workspace to grade. The meaningful baseline (`claude-no-skills`) is wired instead.
- `--repeat` is exposed as `REPEAT=<n>` on `run.sh` (default 1) rather than baked
  in, because each row is a ~30-min agentic pass.
