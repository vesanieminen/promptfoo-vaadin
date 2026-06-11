# Bench finding: solver `claude-agent-sdk` subprocess hangs after the agent finishes

**Status:** open problem, with a known manual + automatic recovery. Root cause narrowed
to a client-side process-exit/teardown issue (NOT a stuck tool call). First fully
documented from the run on **2026-06-11** (`basic_layout`, phase-1 solve `eval-Q5b`).
The `run.sh` header already references a prior, less-documented sighting ("a solve agent
finished but its SDK subprocess never exited, stalling the run 25 min until killed").

## Symptom (how to recognise it)

During **phase 1 (solve)**, the eval appears stuck:

- `bench/run.sh` log goes quiet right after `Running 3 test cases (up to 3 at a time)...`
  (promptfoo's progress bar doesn't render into a redirected log, so quiet ≠ dead — but
  combined with the signs below it means stuck).
- One `claude-agent-sdk` solver PID is **still alive but idle** (~0% CPU, CPU-time not
  growing), while the *other* rows' PIDs have already exited.
- The hung row's **workspace already has final artifacts** (e.g. `desktop-final.png`,
  `solver-screenshots.html`) and **no file changes for many minutes** — the agent is done.
- In `promptfoo view`, that row shows **`Errors: 1`, `0.00% passing (0/0 cases)`** once it
  finally resolves (or after the timeout), with `Error calling Claude Agent SDK: Error:
  Claude Code process exited with code 143` (143 = 128 + SIGTERM, i.e. the kill that
  unblocked it — not the original cause).

Because phase 1 runs the rows under `--max-concurrency 3`, **one hung row blocks the whole
phase barrier**: attach-screenshots and phase 2 (verify) for that problem can't start until
every row's provider call resolves.

## What actually happened (evidence from 2026-06-11)

Phase-1 eval `eval-Q5b` started 09:02:17, ran the 3 Claude rows concurrently:

| row | Vaadin MCP | last agent activity | process exit | promptfoo result |
|-----|-----------|---------------------|--------------|------------------|
| `claude` | remote (`mcp.vaadin.com`) | ~09:06 | exited on its own | final message captured |
| `claude-no-skills` | none | ~09:07 | exited on its own | final message captured |
| `claude-local-mcp` | **local (`localhost:18080`)** | **09:11:00.999** | **never (killed 09:39)** | **error, code 143** |

SDK transcript for the hung row (`~/.claude/projects/…claude-local-mcp/a88c8382-….jsonl`):

- Final **assistant turn at 09:11:00.999**, then nothing until the SIGTERM artifacts at
  09:39:15 (`queue-operation` ×2 + `user`).
- **No dangling `tool_use`** — every tool call had a matching `tool_result`. The agent was
  **not** blocked waiting on an MCP/Playwright tool response.

So: the agent **completed its turn cleanly at 09:11, then the `claude-agent-sdk` node
subprocess sat idle for ~28 minutes and never exited.** promptfoo's provider call awaits
process exit, so it blocked the entire phase-1 barrier (recorded "Duration: 37m 0s" when only
~9 min was real work). The local MCP server itself was healthy — a stateless Spring-AI HTTP
MCP (`DefaultMcpStatelessServerHandler`); its log shows the agent's `notifications/initialized`
at 09:02:20 and it kept serving later problems fine.

## Root-cause hypothesis

**A process-exit / teardown hang, not a stuck task.** After the final turn the subprocess
should emit its terminal `result` message and exit; it didn't.

### The decisive correlate (two runs): it's the FIRST problem, not a row

Two full runs of the same 3 Claude solvers × 3 problems (`basic_layout` → `basic_form` →
`md_ui_spec`), one graded by Claude, one by Codex:

| run | `basic_layout` (1st) | `basic_form` (2nd) | `md_ui_spec` (3rd) |
|-----|----------------------|--------------------|--------------------|
| 1 (claude grader) | 1 hang (`claude-local-mcp`) | clean | clean |
| 2 (codex grader)  | **2 hangs** (`claude-no-skills` + `claude-local-mcp`) | clean | clean |

**Every hang landed on the first problem; problems 2 and 3 were 100 % clean both times.**
That points at a **cold-start cause**, not a row config — the first problem is when the 3 rows
*concurrently* cold-fetch `@playwright/mcp@latest` via `npx` (racing on the shared npx cache),
launch chromium for the first time, and open their first MCP connections. By problem 2 those
are warm and the subprocess exits cleanly.

Per-row susceptibility is a secondary gradient, not the driver: `claude-local-mcp` hung 2/2,
`claude-no-skills` 1/2, `claude` (remote MCP) 0/2. Crucially **`claude-no-skills` has NO Vaadin
MCP at all** (Playwright only) — which **kills the earlier "local `:18080` socket" theory.**
The handle keeping node alive is more likely the **Playwright MCP / `npx` child**, common to
every row and aggravated by the cold-start race. (Run 1's lone hang happened to be the
local-MCP row, which is why the first writeup over-fit to it.)

**Still unconfirmed at the handle level.** Capture the `lsof`/`sample` evidence below the next
time a row hangs to see exactly which fd keeps the loop alive. Note run 2 was unattended, so
the 45-min auto-timeout recovered both hung rows on its own — which is *why* there was no live
process to inspect; to get the evidence, watch the first problem of a run live.

## Recovery

**Manual (used 2026-06-11, works):** `kill -TERM <hung-pid>`. The parent exits cleanly and
**reaps its `playwright-mcp` children** (verified — no orphans). promptfoo then records the
row as a code-143 error and proceeds: attach-screenshots → phase 2 (verify) → next problem.

Identify the hung row first:
```bash
lsof -a -p <pid> -d cwd -Fn | sed -n 's/^n//p'   # → workspaces/<problem>/<which-row>
```

**Automatic (already in place):** `PROMPTFOO_EVAL_TIMEOUT_MS=2700000` (45 min/row) in
`run.sh` auto-kills the hung row and moves on — same end state, just slower.

**Impact is limited:** the on-disk solve is intact, so the **phase-2 rubric verdict (graded
from disk) is unaffected** and remains the valid benchmark score for that row. The only loss
is that row's **phase-1 trace columns** (skill/mcp call counts, solve seconds) — and those are
lost on the auto-timeout path too.

## Diagnostics to capture NEXT time (to nail the root cause)

Before killing the hung PID:
```bash
lsof -nP -p <pid> | grep -iE 'TCP|PIPE|KQUEUE'   # which fd keeps the loop alive? (playwright-mcp pipe/socket is the suspect)
sample <pid> 3 -mayDie                            # macOS: node stack — where is it parked?
```
Also check whether promptfoo captured a `response` for the row (result emitted but process
didn't exit → pure exit/handle bug) vs no response at all.

## Fix options (ranked)

0. **Pre-warm the cold-start (most targeted — addresses the first-problem correlate).** Before
   the problem loop, do once what the first problem currently does under concurrent contention:
   prime the `npx` cache + browser so the solvers don't race on them. e.g. alongside the
   existing Maven warm in `run.sh`: `npx --yes @playwright/mcp@latest --version` and
   `npx --yes playwright install chromium` (chromium is already installed, but this forces the
   npx package fetch/extract to happen serially). If the hang then disappears from problem 1,
   the cold-start race is confirmed as the cause.
1. **Idle-watchdog in `run.sh`** — detect a solver PID with ~0% CPU **and** no
   workspace/transcript file changes for N min (e.g. 8–10), then `kill -TERM` it. Automates
   today's manual fix; recovers in minutes instead of 45. Low risk with a generous N. (Belt-and-
   braces with #0, since it catches any hang, not just cold-start ones.)
2. **Tighten `PROMPTFOO_EVAL_TIMEOUT_MS`** — real solves here finished in ≤ ~9–12 min, so
   45 min is very loose. Trade-off: risk killing a genuinely long solve.
3. **SDK angle** — bump `@anthropic-ai/claude-agent-sdk` (currently `^0.3.160`) and scan
   release notes for MCP-transport teardown / process-exit fixes; look for an option to
   force-close MCP transports on completion. File upstream with the `lsof`/`sample` evidence.
4. **Playwright-MCP / `npx` angle** — the common factor across hung rows (incl. the
   Vaadin-MCP-less `claude-no-skills`). Pin `@playwright/mcp` to a fixed version (drop
   `@latest`) so `npx` resolves from cache without a network round-trip, and/or give each row
   its own `npx` cache dir to remove the shared-cache race. (Supersedes the old `:18080`-socket
   theory, which run 2 refuted.)
5. **Determinism — largely confirmed.** Two runs both hung only on the *first* problem; no need
   to re-test that. Open question is the exact handle — get it via the `lsof`/`sample` capture
   above while watching problem 1 live.
