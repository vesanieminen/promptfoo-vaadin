#!/usr/bin/env bash
# Run the basic_layout benchmark with RUN-SCOPED Claude auth for the verifier.
#
# Why this wrapper exists:
#   The SOLVER (anthropic:claude-code provider) authenticates via your default
#   Claude Code login (macOS Keychain) — no token needed.
#   The RUBRIC VERIFIER (grade_rubric.py) instead shells out to `claude` with an
#   ISOLATED CLAUDE_CONFIG_DIR (each workspace's .claude-home, for concurrent-run
#   isolation). On macOS a NON-DEFAULT CLAUDE_CONFIG_DIR does NOT read the Keychain
#   login, so the verifier needs CLAUDE_CODE_OAUTH_TOKEN — without it the rubric
#   assertion scores 0 ("Verifier did not produce verify-result.json").
#
# This script injects the token into the bench PROCESS ONLY. It is never exported
# to your interactive shell or written to your rc files.
#
# Token source (first hit wins):
#   1. $CLAUDE_CODE_OAUTH_TOKEN already set in this shell
#   2. basic_layout/.bench-token   (gitignored; ONE line — just the sk-ant-... token)
#
# Create .bench-token by running `claude setup-token` INTERACTIVELY (it opens a
# browser), copying the printed sk-ant-oat01-... value, then writing ONLY that:
#     printf %s 'sk-ant-oat01-...' > basic_layout/.bench-token
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
TOK=""; SRC=""
if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  TOK="$(printf '%s' "$CLAUDE_CODE_OAUTH_TOKEN" | tr -d '[:space:]')"; SRC="\$CLAUDE_CODE_OAUTH_TOKEN (env)"
elif [ -f "$TOKEN_FILE" ]; then
  TOK="$(tr -d '[:space:]' < "$TOKEN_FILE")"; SRC="$TOKEN_FILE"
else
  echo "[run] ERROR: no \$CLAUDE_CODE_OAUTH_TOKEN and no $TOKEN_FILE." >&2
  echo "[run]   The rubric verifier needs a token (its isolated CLAUDE_CONFIG_DIR" >&2
  echo "[run]   can't read the Keychain on macOS). Create it once:" >&2
  echo "[run]     claude setup-token   # interactive; copy the printed sk-ant-oat01-... value" >&2
  echo "[run]     printf %s 'sk-ant-oat01-...' > $TOKEN_FILE" >&2
  exit 1
fi
# Reject anything that isn't a bare token (e.g. a redirected setup-token UI dump).
if ! printf '%s' "$TOK" | grep -Eq '^sk-ant-[A-Za-z0-9_-]+$'; then
  echo "[run] ERROR: $SRC is not a bare token (expected just sk-ant-...)." >&2
  echo "[run]   Don't redirect 'claude setup-token' into $TOKEN_FILE — that captures its" >&2
  echo "[run]   interactive UI. Put ONLY the sk-ant-oat01-... value in the file:" >&2
  echo "[run]     printf %s 'sk-ant-oat01-...' > $TOKEN_FILE" >&2
  exit 1
fi
export CLAUDE_CODE_OAUTH_TOKEN="$TOK"
echo "[run] auth: token from $SRC (run-scoped)" >&2

# Warm the shared Maven cache once (cheap if already warm; avoids cold-download races
# between the two concurrent solvers). ~/.m2 is the one un-isolated resource.
( cd ../agentic-dx-improvement/skeletons/vaadin && mvn -q dependency:go-offline ) || true

# --no-cache is REQUIRED, or the agentic providers replay cached output instead of
# actually solving. --max-concurrency 2 runs both solvers (and verifiers) in parallel;
# each has its own workspace, port, and isolated browser/config, so this is safe.
exec npx promptfoo@latest eval -c basic_layout/promptfooconfig.yaml \
  --max-concurrency 2 --no-cache "$@"
