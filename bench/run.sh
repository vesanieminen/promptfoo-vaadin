#!/usr/bin/env bash
# Run the agentic-dx benchmark — for each PROBLEM, PHASE 1 (solve) then PHASE 2
# (verify). By default it runs ALL problems (basic_layout, basic_form, md_ui_spec);
# narrow with PROBLEM= (see below). Despite the path, this dir hosts all problems.
#
# What it does, per problem:
#   1. PHASE 1  — promptfooconfig.js: the SOLVERS (codex, claude, claude-no-skills)
#      solve the task into workspaces/<problem>/<agent>/app (seed.js re-seeds fresh).
#   2. PHASE 2  — verify.js: one VERIFIER provider per workspace grades the solution
#      against the rubric and returns a structured verdict.
#   Each phase is a separate promptfoo eval; `promptfoo view` shows them all together.
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
#   3. bench/.bench-token (gitignored; ONE line — just the sk-ant-... value;
#      EITHER kind, mode auto-detected by its sk-ant-api / sk-ant-oat prefix)
#
# Create .bench-token by writing ONLY the bare value, e.g.:
#     printf %s 'sk-ant-api03-...' > bench/.bench-token   # API key  (NEW)
#     printf %s 'sk-ant-oat01-...' > bench/.bench-token   # subscription (OLD)
# Do NOT redirect `claude setup-token` into the file — its interactive UI prints to
# stdout, so the redirect captures the whole UI (and leaks the token into the file).
#
# Usage:
#   bash bench/run.sh                          # all problems × all agents, once
#   PROBLEM=basic_form bash bench/run.sh        # one problem (see PROBLEM below)
#   PROBLEM=basic_form,md_ui_spec bash bench/run.sh
#   AGENT=claude bash bench/run.sh              # only the claude row(s) — see AGENT
#   VERIFIER=codex bash bench/run.sh            # grade phase 2 with Codex (see VERIFIER)
#   REPEAT=3 bash bench/run.sh                  # run the whole thing 3x
#
# PROBLEM=<name>[,<name>...] (default: all) — which problem(s) to run; each gets its
#   own solve+verify pipeline and namespaced workspaces. Valid: basic_layout,
#   basic_form, md_ui_spec.
#
# AGENT=<name>[,<name>...] (default: all) picks which agent rows to run across BOTH
# phases, by plain name — no regex:
#   AGENT=claude                  → claude only
#   AGENT=claude,claude-no-skills → claude + the no-skills baseline (the skills A/B)
#   AGENT=claude,claude-pw-cli    → claude + the Playwright CLI variant (the MCP-vs-CLI A/B)
#   AGENT=codex                   → codex only
# Valid names: the bench.SETUPS labels (see `_known` below). (Under the hood this becomes an
# anchored --filter-providers, because each provider LABEL ends with its agent name
# (solver `claude`, verifier `verify-claude`) while the verifier's provider id
# (anthropic:claude-agent-sdk, or openai:codex:* when VERIFIER=codex) does NOT — so a
# bare name would over-match the verify rows. You can still pass --filter-providers
# '<regex>' yourself instead of AGENT if you like; any extra args go to BOTH phases.)
#
# VERIFIER=<claude|codex> (default: claude) picks the PHASE-2 grader (see verify.js):
#   claude → anthropic:claude-agent-sdk (model pinned claude-opus-4-8) — the default,
#            keeps results comparable with prior runs / the reproducibility ADR.
#   codex  → openai:codex:gpt-5.5. NOTE: Codex grades via its OWN login (Codex Keychain
#            / OPENAI_API_KEY), so VERIFIER=codex needs a Codex login IN ADDITION to the
#            Claude auth the solvers use. Phase 1 (solve) ignores VERIFIER.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TOKEN_FILE="bench/.bench-token"

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
# Honour AGENTIC_DX_DIR so it resolves from a worktree too (not just the sibling).
( cd "${AGENTIC_DX_DIR:-../agentic-dx-improvement}/skeletons/vaadin" && mvn -q dependency:go-offline ) || true

REPEAT="${REPEAT:-1}"
# Per-phase --max-concurrency (default 3 = all agent rows at once). Lower it (e.g.
# MAX_CONCURRENCY=2) to ease load on the machine / browsers / shared ~/.m2.
MAXC="${MAX_CONCURRENCY:-3}"

# VERIFIER=<claude|codex> (default claude) — the PHASE-2 grader. verify.js reads this
# from the environment, so we only validate + export it here (phase 1 ignores it).
export VERIFIER="${VERIFIER:-claude}"
case "$VERIFIER" in
  claude) ;;
  codex) echo "[run] phase-2 verifier: codex (needs a Codex login; solvers still use Claude auth)" >&2 ;;
  *) echo "[run] ERROR: unknown VERIFIER '$VERIFIER' (valid: claude, codex)." >&2; exit 1 ;;
esac

# Per-ROW wall-clock ceiling. promptfoo's per-test timeout defaults to 0 (OFF), which
# lets a wedged agentic subprocess block the whole run indefinitely (observed: a solve
# agent finished but its SDK subprocess never exited, stalling the run 25 min until
# killed by hand). Bound it so a hung row is recorded as a timeout error and the run
# moves on. 45 min/row is generous — real solves run ~7-35 min. Set =0 to disable.
export PROMPTFOO_EVAL_TIMEOUT_MS="${PROMPTFOO_EVAL_TIMEOUT_MS:-2700000}"

# AGENT=<name>[,<name>...] → run only those agent rows. Translated to an anchored
# --filter-providers and prepended to the args forwarded to BOTH phases. Anchored at
# the end ('<name>$') because each provider label ENDS with its agent name (solver
# `claude`, verifier `verify-claude`) while the shared verifier id
# `anthropic:claude-agent-sdk` does NOT — so a bare name would over-match verify.
# `set --` injection keeps this bash-3.2 safe (no empty-array expansion under set -u).
if [ -n "${AGENT:-}" ]; then
  AGENT="${AGENT// /}"              # tolerate spaces, e.g. AGENT="claude, codex"
  _known="codex claude claude-no-skills claude-local-mcp claude-pw-cli codex-pw-cli"   # = bench.SETUPS labels (keep in sync)
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

# PROBLEM=<name>[,<name>...] (default: all, in canonical order) selects which
# problem(s) to run. Each selected problem runs its OWN solve+verify pipeline against
# its OWN namespaced workspaces / ports (8081..8089), so all problems show up
# side-by-side in `promptfoo view`. Valid names: basic_layout, basic_form, md_ui_spec.
# The configs/seed/graders read a SINGLE PROBLEM per eval — run_pipeline sets it per
# call — so we consume the selector here and unset it to avoid leaking a comma-list.
_KNOWN_PROBLEMS="basic_layout basic_form md_ui_spec"
if [ -n "${PROBLEM:-}" ]; then
  _sel="${PROBLEM// /}"                 # tolerate spaces, e.g. PROBLEM="basic_form, md_ui_spec"
  IFS=',' read -ra _PROBLEMS <<< "$_sel"
  for _p in "${_PROBLEMS[@]}"; do
    case " $_KNOWN_PROBLEMS " in
      *" $_p "*) ;;
      *) echo "[run] ERROR: unknown PROBLEM '$_p' (valid: $_KNOWN_PROBLEMS; comma-separate for several)." >&2; exit 1 ;;
    esac
  done
  echo "[run] PROBLEM=$_sel → running only those problem(s)" >&2
else
  # shellcheck disable=SC2206
  _PROBLEMS=( $_KNOWN_PROBLEMS )        # all, in canonical order
fi
unset PROBLEM                           # run_pipeline re-exports a single PROBLEM per call

# One full pipeline pass for ONE problem: PHASE 1 (solve) then PHASE 2 (verify),
# with PROBLEM exported so the configs/seed/graders target that problem's namespaced
# workspaces/ports. --no-cache is REQUIRED — the agentic providers cache by prompt,
# so without it a re-run replays the first run instead of actually solving/verifying.
# --max-concurrency 3 runs all three agent rows in parallel; each has its own
# workspace, port, and isolated browser, so this is safe. Each phase is `|| true` so
# a failing/low-scoring row never stops the others or the verify phase — the signal
# lives in `promptfoo view`, not the wrapper's exit code.
run_pipeline() {
  local prob="$1"; shift
  echo "[run] ===== problem: $prob =====" >&2
  echo "[run] PHASE 1/2 — solve  (promptfooconfig.js)" >&2
  PROBLEM="$prob" npx promptfoo@latest eval -c bench/promptfooconfig.js \
    --max-concurrency "$MAXC" --no-cache "$@" || true
  # Attach each solver's Playwright screenshots (already saved in its workspace root)
  # to its row in the just-written solve eval, so they render as clickable images in
  # `promptfoo view`. Purely post-run: no model call, no provider/grader change (see
  # attach_shots.js). `|| true` so a screenshot-attach hiccup never fails the run.
  PROBLEM="$prob" node bench/attach_shots.js || true
  echo "[run] PHASE 2/2 — verify (verify.js)" >&2
  PROBLEM="$prob" npx promptfoo@latest eval -c bench/verify.js \
    --max-concurrency "$MAXC" --no-cache "$@" || true
}

# Run the selected problems in sequence (each is its own solve+verify pipeline).
run_selected() {
  for _prob in "${_PROBLEMS[@]}"; do
    run_pipeline "$_prob" "$@"
  done
}

if [ "$REPEAT" -le 1 ]; then
  run_selected "$@"
else
  for i in $(seq 1 "$REPEAT"); do
    echo "[run] ===== repeat $i/$REPEAT =====" >&2
    run_selected "$@"
  done
fi

echo "[run] done. View results:  npx promptfoo@latest view" >&2
