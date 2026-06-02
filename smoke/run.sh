#!/usr/bin/env bash
# Quick auth smoke test — confirms Claude works for BOTH paths the basic_layout
# benchmark needs, in well under a minute (no Maven / server / Playwright):
#   1. EVAL / solver  — the agentic anthropic:claude-code provider (your login)
#   2. VERIFICATION   — `claude` under an isolated CLAUDE_CONFIG_DIR (needs token)
#
# Auth is injected into THIS process only (never your rc): $CLAUDE_CODE_OAUTH_TOKEN,
# else basic_layout/.bench-token. With no token the test still runs — the solver
# passes (via your Keychain login) and the verification assertion fails with a
# clear "provide a token" message, which is itself a useful diagnostic.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TOKEN_FILE="basic_layout/.bench-token"
if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  echo "[smoke] auth: using \$CLAUDE_CODE_OAUTH_TOKEN from env → verification should PASS" >&2
elif [ -f "$TOKEN_FILE" ]; then
  export CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
  echo "[smoke] auth: token from $TOKEN_FILE (run-scoped) → verification should PASS" >&2
else
  echo "[smoke] auth: NO token (no \$CLAUDE_CODE_OAUTH_TOKEN, no $TOKEN_FILE)." >&2
  echo "[smoke]       → solver/eval should PASS (Keychain login); verification should FAIL." >&2
  echo "[smoke]       To test verification too: claude setup-token > $TOKEN_FILE" >&2
fi

exec npx promptfoo@latest eval -c smoke/promptfooconfig.yaml --no-cache "$@"
