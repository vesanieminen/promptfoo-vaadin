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
TOK=""; SRC=""
if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  TOK="$(printf '%s' "$CLAUDE_CODE_OAUTH_TOKEN" | tr -d '[:space:]')"; SRC="\$CLAUDE_CODE_OAUTH_TOKEN (env)"
elif [ -f "$TOKEN_FILE" ]; then
  TOK="$(tr -d '[:space:]' < "$TOKEN_FILE")"; SRC="$TOKEN_FILE"
fi
if [ -n "$TOK" ]; then
  # Reject anything that isn't a bare token (e.g. a redirected setup-token UI dump).
  if printf '%s' "$TOK" | grep -Eq '^sk-ant-[A-Za-z0-9_-]+$'; then
    export CLAUDE_CODE_OAUTH_TOKEN="$TOK"
    echo "[smoke] auth: token from $SRC (run-scoped) → verification should PASS" >&2
  else
    echo "[smoke] ERROR: $SRC is not a bare token (expected just sk-ant-...)." >&2
    echo "[smoke]   Don't redirect 'claude setup-token' into $TOKEN_FILE — it captures the UI." >&2
    echo "[smoke]   Put ONLY the sk-ant-oat01-... value in it:" >&2
    echo "[smoke]     printf %s 'sk-ant-oat01-...' > $TOKEN_FILE" >&2
    exit 1
  fi
else
  echo "[smoke] auth: NO token → solver/eval should PASS (Keychain); verification should FAIL." >&2
  echo "[smoke]       To test verification: run 'claude setup-token' (interactive), copy the" >&2
  echo "[smoke]       sk-ant-oat01-... value, then: printf %s 'sk-ant-oat01-...' > $TOKEN_FILE" >&2
fi

exec npx promptfoo@latest eval -c smoke/promptfooconfig.yaml --no-cache "$@"
