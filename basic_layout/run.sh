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
#   2. basic_layout/.bench-token   (gitignored; a single line: the token)
#   3. minted interactively via `claude setup-token` (opens a browser, one time)
#
# Usage:
#   bash basic_layout/run.sh                 # run the benchmark
#   bash basic_layout/run.sh --filter-first-n 1   # extra args pass through to promptfoo
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TOKEN_FILE="basic_layout/.bench-token"
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  if [ -f "$TOKEN_FILE" ]; then
    CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
    echo "[run] auth: using token from $TOKEN_FILE (run-scoped)" >&2
  else
    echo "[run] auth: no \$CLAUDE_CODE_OAUTH_TOKEN and no $TOKEN_FILE." >&2
    echo "[run]       minting one with 'claude setup-token' (interactive, one time)…" >&2
    echo "[run]       tip: save it to $TOKEN_FILE to skip this next time." >&2
    CLAUDE_CODE_OAUTH_TOKEN="$(claude setup-token)"
  fi
fi
export CLAUDE_CODE_OAUTH_TOKEN

# Warm the shared Maven cache once (cheap if already warm; avoids cold-download races
# between the two concurrent solvers). ~/.m2 is the one un-isolated resource.
( cd ../agentic-dx-improvement/skeletons/vaadin && mvn -q dependency:go-offline ) || true

# --no-cache is REQUIRED, or the agentic providers replay cached output instead of
# actually solving. --max-concurrency 2 runs both solvers (and verifiers) in parallel;
# each has its own workspace, port, and isolated browser/config, so this is safe.
exec npx promptfoo@latest eval -c basic_layout/promptfooconfig.yaml \
  --max-concurrency 2 --no-cache "$@"
