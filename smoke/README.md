# Claude auth smoke test

A 30-second check that Claude auth works for the `basic_layout` benchmark — without
any of its weight (no Maven, no server, no Playwright, no rubric). It exercises two
checks, both on **whichever auth path you're about to run the benchmark on**:

| Check | What it is | What it authenticates with |
|---|---|---|
| **Solver / eval** | the agentic `anthropic:claude-code` provider answers a trivial prompt (`SOLVER_OK`) | a token if one is set, else your Claude Code login (macOS Keychain) |
| **Verifier CLI** | `verify_auth.py` runs a trivial `claude -p` | **no token →** the **default** config dir (your Keychain login — the path the provider-based verifier now uses); **token set →** an **isolated `CLAUDE_CONFIG_DIR`** (no Keychain), asserting the token itself works |

> **Note.** The benchmark's rubric verifier *used to* run under an isolated
> `CLAUDE_CONFIG_DIR` (the old `grade_rubric.py` subprocess), which always needed a
> token. That's no longer how it works — the verifier is now a promptfoo **provider**
> that authenticates like the solver (Keychain login or an env token), so a token is
> **optional**. See [`../docs/ADR-verifier-as-provider.md`](../docs/ADR-verifier-as-provider.md).
> `verify_auth.py` therefore tests the *login* path when no token is set, and only
> falls back to the strict isolated-config *token* path when you actually supply one.

## Run it

```bash
bash smoke/run.sh
```

The wrapper injects a token into the bench process only — and only if you have one
(from `$CLAUDE_CODE_OAUTH_TOKEN`, else `basic_layout/.bench-token`), never your rc
files. With no token it tests your login.

### Reading the result

- **Both assertions PASS** → Claude auth works the way you're about to run it
  (Keychain login if no token, the token if one is set). The full benchmark will
  authenticate end-to-end.
- **Both FAIL** → you're not authenticated for that path.
  - *No token:* you're not logged into Claude Code — run `claude /login`.
  - *Token set:* the token was rejected (expired/invalid) — re-mint it (below), or
    unset it to fall back to your login.
- **Solver PASSES, verifier FAILS** → almost always a **token set but rejected** while
  your Keychain login still covers the solver. Re-mint the token, or unset it.

To run in **token mode** (e.g. API-key/subscription billing, or a login-less CI box):

```bash
# Run setup-token INTERACTIVELY (it opens a browser), then copy the printed
# sk-ant-oat01-... value and write ONLY that into the file. Do NOT redirect
# setup-token with `>` — its UI prints to stdout, so the file would capture the
# whole UI (and leak the token), not just the token.
claude setup-token
printf %s 'sk-ant-oat01-...' > basic_layout/.bench-token   # gitignored, one time
bash smoke/run.sh
```

`verify_auth.py` prints a mode-tagged reason in the results table (and
`npx promptfoo@latest view`), e.g. *"VERIFICATION auth OK [login / default config
(Keychain)]"* or a *"VERIFICATION auth FAILED [...]"* message with the fix.

## What this still surfaces

The macOS gotcha worth knowing: an **isolated** `CLAUDE_CONFIG_DIR` does not read the
Keychain, so anything running under one needs an explicit token. The benchmark's
solver and provider-based verifier both use the **default** config dir, so they read
the Keychain and a token is optional — which is why, with no token, this smoke test
checks the default-config login path rather than the isolated one.
