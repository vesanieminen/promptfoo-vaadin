#!/usr/bin/env bash
# Run the basic_layout benchmark — PHASE 1 (solve) then PHASE 2 (verify).
#
# What it does:
#   1. PHASE 1  — promptfooconfig.yaml: the SOLVERS (codex, claude, claude-no-skills)
#      solve the task into workspaces/<agent>/app (seed.js re-seeds fresh each run).
#   2. PHASE 2  — verify.yaml: one VERIFIER provider per workspace grades the
#      solution against the rubric and returns a structured verdict.
#   Both phases are separate promptfoo evals; `promptfoo view` shows them together.
#
# Auth (optional in subscription mode):
#   Both phases are anthropic:claude-agent-sdk / claude-code / codex providers, so
#   by default they authenticate from your existing Claude Code / Codex login
#   (macOS Keychain). Unlike the OLD subprocess verifier, NOTHING here uses an
#   isolated CLAUDE_CONFIG_DIR, so a token is NOT required when you're signed in.
#
#   Provide a credential only when you want to OVERRIDE that — e.g. bill against an
#   API key, or run on a machine / CI with no Keychain login. If provided, this
#   script resolves ONE credential and injects it into the bench PROCESS ONLY
#   (never your interactive shell or rc files); if none is found it WARNS and
#   relies on your login.
#
# REPEAT=<n> (default 1): re-run the whole solve+verify pipeline n times for
#   variance (each iteration re-seeds fresh workspaces and shows as its own run in
#   `promptfoo view`). Each row is a ~30-min agentic pass, so raise this knowingly.
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
#   bash basic_layout/run.sh                  # all agent rows: solve + verify, once
#   AGENT=claude bash basic_layout/run.sh     # only the claude row(s) — see AGENT below
#   REPEAT=3 bash basic_layout/run.sh         # run the whole pipeline 3x
#
# AGENT=<name>[,<name>...] (default: all) picks which agent rows to run across BOTH
# phases, by plain name — no regex:
#   AGENT=claude                  → claude only
#   AGENT=claude,claude-no-skills → claude + the no-skills baseline (the skills A/B)
#   AGENT=codex                   → codex only
# Valid names: codex, claude, claude-no-skills. (Under the hood this becomes an
# anchored --filter-providers, because the phase-2 verifiers all share the id
# anthropic:claude-agent-sdk — so a bare name would over-match the verify rows. You
# can still pass --filter-providers '<regex>' yourself instead of AGENT if you like;
# any extra args are forwarded to BOTH phases.)
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
fi

# 2) If a credential was provided, classify it by prefix → export the matching var
#    and unset the OTHER, so the bench process carries exactly ONE credential. The
#    bare-token guard also rejects a redirected setup-token UI dump (multi-line) or
#    stray quoting/spaces. If NONE was provided, warn and rely on the Claude Code /
#    Codex login (Keychain) — the providers no longer need an explicit token.
if [ -z "$TOK" ]; then
  echo "[run] note: no credential provided — relying on your Claude Code / Codex login" >&2
  echo "[run]   (Keychain). To override (API-key billing, or a machine with no login):" >&2
  echo "[run]     • API key:            export ANTHROPIC_API_KEY=sk-ant-api...  (or put it in $TOKEN_FILE)" >&2
  echo "[run]     • Subscription token: claude setup-token  then  printf %s 'sk-ant-oat01-...' > $TOKEN_FILE" >&2
else
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
fi

# Warm the shared Maven cache once (cheap if already warm; avoids cold-download
# races between the concurrent solvers). ~/.m2 is the one un-isolated resource.
( cd ../agentic-dx-improvement/skeletons/vaadin && mvn -q dependency:go-offline ) || true

REPEAT="${REPEAT:-1}"

# AGENT=<name>[,<name>...] → run only those agent rows. Translated to an anchored
# --filter-providers and prepended to the args forwarded to BOTH phases. Anchored at
# the end ('<name>$') because each provider label ENDS with its agent name (solver
# `claude`, verifier `verify-claude`) while the shared verifier id
# `anthropic:claude-agent-sdk` does NOT — so a bare name would over-match verify.
# `set --` injection keeps this bash-3.2 safe (no empty-array expansion under set -u).
if [ -n "${AGENT:-}" ]; then
  AGENT="${AGENT// /}"              # tolerate spaces, e.g. AGENT="claude, codex"
  _known="codex claude claude-no-skills"
  IFS=',' read -ra _want <<< "$AGENT"
  for _a in "${_want[@]}"; do
    case " $_known " in
      *" $_a "*) ;;
      *) echo "[run] ERROR: unknown AGENT '$_a' (valid: $_known; comma-separate for several)." >&2; exit 1 ;;
    esac
  done
  _only="(${AGENT//,/|})\$"          # e.g. claude,codex -> (claude|codex)$
  set -- --filter-providers "$_only" "$@"
  echo "[run] AGENT=$AGENT → running only those row(s) in both phases (--filter-providers '$_only')" >&2
fi

# One full pipeline pass: PHASE 1 (solve) then PHASE 2 (verify). --no-cache is
# REQUIRED — the agentic providers cache by prompt, so without it a re-run replays
# the first run instead of actually solving/verifying. --max-concurrency 3 runs all
# three rows in parallel; each has its own workspace, port, and isolated browser,
# so this is safe. Each phase is `|| true` so a failing/low-scoring row never stops
# the others or the verify phase — the signal lives in `promptfoo view`, not the
# wrapper's exit code.
run_pipeline() {
  echo "[run] PHASE 1/2 — solve  (promptfooconfig.yaml)" >&2
  npx promptfoo@latest eval -c basic_layout/promptfooconfig.yaml \
    --max-concurrency 3 --no-cache "$@" || true
  echo "[run] PHASE 2/2 — verify (verify.yaml)" >&2
  npx promptfoo@latest eval -c basic_layout/verify.yaml \
    --max-concurrency 3 --no-cache "$@" || true
}

if [ "$REPEAT" -le 1 ]; then
  run_pipeline "$@"
else
  for i in $(seq 1 "$REPEAT"); do
    echo "[run] ===== repeat $i/$REPEAT =====" >&2
    run_pipeline "$@"
  done
fi

echo "[run] done. View results:  npx promptfoo@latest view" >&2
