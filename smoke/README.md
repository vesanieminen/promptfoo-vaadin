# Claude auth smoke test

A 30-second check that Claude works for **both** paths the `basic_layout` benchmark
relies on — without any of its weight (no Maven, no server, no Playwright, no rubric).

| Path | What it is | How it authenticates |
|---|---|---|
| **Eval / solver** | the agentic `anthropic:claude-code` provider answers a trivial prompt (`SOLVER_OK`) | your default Claude Code login (macOS Keychain) — **no token needed** |
| **Verification** | `verify_auth.py` shells out to `claude` with an **isolated `CLAUDE_CONFIG_DIR`**, exactly like `basic_layout/grade_rubric.py` | a **run-scoped `CLAUDE_CODE_OAUTH_TOKEN`** — the isolated config dir can't read the Keychain on macOS |

## Run it

```bash
bash smoke/run.sh
```

The wrapper injects the token into the bench process only (from `$CLAUDE_CODE_OAUTH_TOKEN`,
else `basic_layout/.bench-token`) — never your rc files.

### Reading the result

- **Both assertions PASS** → Claude works for eval *and* verification. The full
  benchmark will authenticate end-to-end.
- **Solver PASSES, verification FAILS** → you have no token. The eval path works
  (Keychain login), but the verifier needs a token. Provide one and re-run:
  ```bash
  claude setup-token > basic_layout/.bench-token   # gitignored, one time
  bash smoke/run.sh
  ```
- **Both FAIL** → you're not logged into Claude Code at all. Run `claude /login`.

`verify_auth.py` prints a specific reason in the results table (and `npx promptfoo@latest view`),
e.g. *"VERIFICATION auth OK"* or *"VERIFICATION auth FAILED — … provide a token"*.

## Why this mirrors the real benchmark

The distinction this surfaces is the one that bit the `basic_layout` run: the
**solver** runs with the default config dir (→ Keychain, works on your login), but
the **verifier** sets `CLAUDE_CONFIG_DIR` to an isolated home, and on macOS a
non-default config dir does not read the Keychain — so it needs the token. If this
smoke test is green, `bash basic_layout/run.sh` will authenticate the same way.
