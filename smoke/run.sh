#!/usr/bin/env bash
# Quick auth smoke test — confirms Claude works for BOTH paths the basic_layout
# benchmark needs, in well under a minute (no Maven / server / Playwright):
#   1. EVAL / solver  — the agentic anthropic:claude-code provider (your login or token)
#   2. VERIFICATION   — `claude` on the path you'll actually run on: the DEFAULT
#                       config dir (Keychain login) when no token is set, else an
#                       isolated CLAUDE_CONFIG_DIR that exercises the token.
#
# Auth is injected into THIS process only (never your rc): $CLAUDE_CODE_OAUTH_TOKEN,
# else bench/.bench-token. A token is OPTIONAL — with none, both assertions
# pass via your Keychain login (the verifier is a provider now, not an isolated-config
# subprocess; see docs/ADR-verifier-as-provider.md).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TOKEN_FILE="bench/.bench-token"
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
  echo "[smoke] auth: NO token → testing your Claude Code login (Keychain). BOTH assertions" >&2
  echo "[smoke]       should PASS if you're logged in ('claude /login'). To exercise the token" >&2
  echo "[smoke]       path instead: 'claude setup-token' (interactive), copy the sk-ant-oat01-..." >&2
  echo "[smoke]       value, then: printf %s 'sk-ant-oat01-...' > $TOKEN_FILE" >&2
fi

exec npx promptfoo@latest eval -c smoke/promptfooconfig.yaml --no-cache "$@"
