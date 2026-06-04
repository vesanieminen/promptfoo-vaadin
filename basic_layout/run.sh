#!/usr/bin/env bash
# Run the basic_layout benchmark with RUN-SCOPED Claude auth.
#
# Why this wrapper exists:
#   Two pieces need Claude auth, and on macOS one of them can't read your Keychain
#   login:
#     • The SOLVER (anthropic:claude-code provider) — by default authenticates via
#       your Claude Code login (macOS Keychain).
#     • The RUBRIC VERIFIER (grade_rubric.py) — shells out to `claude` with an
#       ISOLATED CLAUDE_CONFIG_DIR (each workspace's .claude-home, for concurrent-
#       run isolation). On macOS a NON-DEFAULT CLAUDE_CONFIG_DIR does NOT read the
#       Keychain login, so the verifier needs an explicit credential in the env —
#       without it the rubric assertion scores 0 ("Verifier did not produce
#       verify-result.json").
#
# This script resolves ONE credential and injects it into the bench PROCESS ONLY
# (never exported to your interactive shell or written to your rc files). Both the
# solver and the verifier then authenticate with it.
#
# TWO AUTH MODES — YOU CHOOSE which to use by which credential you provide:
#   • Anthropic API key   sk-ant-api...  → exported as ANTHROPIC_API_KEY  (NEW)
#       Bills against the API key (NOT a subscription). It takes precedence over any
#       Keychain/subscription login, so BOTH the solver and the verifier bill via the
#       API key. Get one at https://console.anthropic.com/.
#   • Subscription token  sk-ant-oat...  → exported as CLAUDE_CODE_OAUTH_TOKEN (OLD)
#       Bills against your Claude subscription. Mint it with `claude setup-token`
#       (interactive; opens a browser) and copy the printed sk-ant-oat01-... value.
#   The chosen var is set and the OTHER is unset for the bench process, so exactly
#   one credential is live (deterministic — no auth-precedence surprises).
#
# Credential source (first hit wins):
#   1. $ANTHROPIC_API_KEY        already set in this shell  → API-key mode
#   2. $CLAUDE_CODE_OAUTH_TOKEN  already set in this shell  → subscription mode
#   3. basic_layout/.bench-token (gitignored; ONE line — just the sk-ant-... value;
#      EITHER kind, mode auto-detected by its sk-ant-api / sk-ant-oat prefix)
#
# Create .bench-token by writing ONLY the bare value, e.g.:
#     printf %s 'sk-ant-api03-...' > basic_layout/.bench-token   # API key  (NEW)
#     printf %s 'sk-ant-oat01-...' > basic_layout/.bench-token   # subscription (OLD)
# Do NOT redirect `claude setup-token` into the file — its interactive UI prints to
# stdout, so the redirect captures the whole UI (and leaks the token into the file).
#
# Usage:
#   bash basic_layout/run.sh                 # run the benchmark
#   bash basic_layout/run.sh --filter-first-n 1   # extra args pass through to promptfoo
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TOKEN_FILE="basic_layout/.bench-token"

# 1) Resolve ONE credential and its source label (first hit wins). The user picks
#    the auth mode by which credential they supply (see header).
TOK=""; SRC=""
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  TOK="$(printf '%s' "$ANTHROPIC_API_KEY" | tr -d '[:space:]')"; SRC="\$ANTHROPIC_API_KEY (env)"
  if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    echo "[run] note: both ANTHROPIC_API_KEY and CLAUDE_CODE_OAUTH_TOKEN are set; using the" >&2
    echo "[run]   API key. Unset ANTHROPIC_API_KEY (in this shell) to use the OAuth token." >&2
  fi
elif [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  TOK="$(printf '%s' "$CLAUDE_CODE_OAUTH_TOKEN" | tr -d '[:space:]')"; SRC="\$CLAUDE_CODE_OAUTH_TOKEN (env)"
elif [ -f "$TOKEN_FILE" ]; then
  TOK="$(tr -d '[:space:]' < "$TOKEN_FILE")"; SRC="$TOKEN_FILE"
else
  echo "[run] ERROR: no credential found." >&2
  echo "[run]   The verifier's isolated CLAUDE_CONFIG_DIR can't read the macOS Keychain," >&2
  echo "[run]   so it needs an explicit credential. Provide ONE (this is your auth choice):" >&2
  echo "[run]     • API key (bills the API):  export ANTHROPIC_API_KEY=sk-ant-api...  (or put it in $TOKEN_FILE)" >&2
  echo "[run]     • Subscription token (OLD): claude setup-token  then  printf %s 'sk-ant-oat01-...' > $TOKEN_FILE" >&2
  exit 1
fi

# 2) Classify the credential by prefix → export the matching var and unset the
#    OTHER, so the bench process carries exactly ONE credential. The bare-token
#    guard also rejects a redirected setup-token UI dump (multi-line) or stray
#    quoting/spaces.
case "$TOK" in
  sk-ant-api*)
    if ! printf '%s' "$TOK" | grep -Eq '^sk-ant-api[A-Za-z0-9_-]+$'; then
      echo "[run] ERROR: $SRC is not a bare Anthropic API key (expected just sk-ant-api...)." >&2
      exit 1
    fi
    export ANTHROPIC_API_KEY="$TOK"; unset CLAUDE_CODE_OAUTH_TOKEN || true
    echo "[run] auth: Anthropic API key from $SRC (run-scoped; solver + verifier bill via the API key)" >&2
    ;;
  sk-ant-oat*)
    if ! printf '%s' "$TOK" | grep -Eq '^sk-ant-oat[A-Za-z0-9_-]+$'; then
      echo "[run] ERROR: $SRC is not a bare subscription token (expected just sk-ant-oat...)." >&2
      echo "[run]   Don't redirect 'claude setup-token' into $TOKEN_FILE — that captures its" >&2
      echo "[run]   interactive UI. Put ONLY the sk-ant-oat01-... value in the file." >&2
      exit 1
    fi
    export CLAUDE_CODE_OAUTH_TOKEN="$TOK"; unset ANTHROPIC_API_KEY || true
    echo "[run] auth: subscription OAuth token from $SRC (run-scoped)" >&2
    ;;
  *)
    echo "[run] ERROR: $SRC is not a recognized credential (expected sk-ant-api... or sk-ant-oat...)." >&2
    exit 1
    ;;
esac

# Warm the shared Maven cache once (cheap if already warm; avoids cold-download races
# between the two concurrent solvers). ~/.m2 is the one un-isolated resource.
( cd ../agentic-dx-improvement/skeletons/vaadin && mvn -q dependency:go-offline ) || true

# --no-cache is REQUIRED, or the agentic providers replay cached output instead of
# actually solving. --max-concurrency 2 runs both solvers (and verifiers) in parallel;
# each has its own workspace, port, and isolated browser/config, so this is safe.
exec npx promptfoo@latest eval -c basic_layout/promptfooconfig.yaml \
  --max-concurrency 2 --no-cache "$@"
