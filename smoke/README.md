# Claude auth smoke test

A 30-second check that Claude auth works for the `basic_layout` benchmark — without
any of its weight (no Maven, no server, no Playwright, no rubric). It exercises two
paths:

| Path | What it is | How it authenticates |
|---|---|---|
| **Solver login** | the agentic `anthropic:claude-code` provider answers a trivial prompt (`SOLVER_OK`) | your default Claude Code login (macOS Keychain) — **no token needed** |
| **Token auth** | `verify_auth.py` shells out to `claude` under an **isolated `CLAUDE_CONFIG_DIR`** — the strictest case, forcing token-only auth | a **run-scoped `CLAUDE_CODE_OAUTH_TOKEN`** — an isolated config dir can't read the Keychain on macOS |

> **Note.** The benchmark's rubric verifier *used to* run under an isolated
> `CLAUDE_CONFIG_DIR` (the old `grade_rubric.py` subprocess), which is what the token
> path mirrors. That's no longer how it works — the verifier is now a promptfoo
> **provider** that authenticates like the solver (Keychain login or an env token),
> so a token is **optional** for the benchmark. See
> [`../docs/ADR-verifier-as-provider.md`](../docs/ADR-verifier-as-provider.md). The
> token check is kept as a defensive test of the token path — useful for API-key /
> token billing or a login-less CI box.

## Run it

```bash
bash smoke/run.sh
```

The wrapper injects the token into the bench process only (from `$CLAUDE_CODE_OAUTH_TOKEN`,
else `basic_layout/.bench-token`) — never your rc files.

### Reading the result

- **Both assertions PASS** → Claude works for the solver login *and* the token path.
  The full benchmark will authenticate end-to-end, with or without a token.
- **Solver PASSES, token check FAILS** → you have no token. That's **fine for the
  benchmark** — both phases now use your Keychain login. Provide a token only if you
  want token / API-key billing or run on a box with no login:
  ```bash
  # Run setup-token INTERACTIVELY (it opens a browser), then copy the printed
  # sk-ant-oat01-... value and write ONLY that into the file. Do NOT redirect
  # setup-token with `>` — its UI prints to stdout, so the file would capture the
  # whole UI (and leak the token), not just the token.
  claude setup-token
  printf %s 'sk-ant-oat01-...' > basic_layout/.bench-token   # gitignored, one time
  bash smoke/run.sh
  ```
- **Both FAIL** → you're not logged into Claude Code at all. Run `claude /login`.

`verify_auth.py` prints a specific reason in the results table (and `npx promptfoo@latest view`),
e.g. *"VERIFIER_OK"* or a *"token auth FAILED — … provide a token"* message.

## What this still surfaces

The macOS gotcha worth knowing: an **isolated** `CLAUDE_CONFIG_DIR` does not read the
Keychain, so anything running under one needs an explicit token. The benchmark's
solver and (now) provider-based verifier both use the **default** config dir, so they
read the Keychain and a token is optional. If the token path is green, then both
token-based and login-based auth work on this machine.
