#!/usr/bin/env bash
# promptfoo "exec" provider that runs the Codex CLI as the SOLVER for the
# agentic-dx `basic_layout` task. It mirrors run_task_local.sh from the
# agentic-dx-improvement harness, adapted to promptfoo:
#
#   - promptfoo calls:  solve.sh "<rendered prompt>" "<optsJSON>" "<ctxJSON>"
#     (we only use the prompt, $1).
#   - we seed a fresh writable workspace (skeleton + task files, rubric stripped),
#     run `codex exec` in it, and print {workspace, app, final} JSON to stdout.
#
# stdout IS the promptfoo "output" the graders parse, so ALL codex chatter is
# sent to stderr to keep stdout clean JSON.
#
# No `set -u`: macOS bash 3.2 errors on empty-array expansion under it.
set -o pipefail

PROMPT="${1:-}"

# --- Resolve locations (independent of cwd; we use BASH_SOURCE) ------------
SOLVE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # promptfoo/basic_layout
REPO_ROOT="$(cd "$SOLVE_DIR/.." && pwd)"                     # promptfoo

# The agentic-dx-improvement repo is the source of truth for the problem,
# skeleton, and base prompt. Defaults to the sibling checkout; override with
# AGENTIC_DX_DIR if it lives elsewhere.
AGENTIC_DX_DIR="${AGENTIC_DX_DIR:-$REPO_ROOT/../agentic-dx-improvement}"
PROBLEM="${PROBLEM:-basic_layout}"
TECHSTACK="${TECHSTACK:-vaadin}"

PROBLEM_DIR="$AGENTIC_DX_DIR/problems/$PROBLEM"
SKELETON_DIR="$AGENTIC_DX_DIR/skeletons/$TECHSTACK"

for p in "$PROBLEM_DIR" "$SKELETON_DIR"; do
    if [ ! -d "$p" ]; then
        echo "Missing required path: $p (set AGENTIC_DX_DIR to your agentic-dx-improvement checkout)" >&2
        exit 1
    fi
done

if ! command -v codex >/dev/null 2>&1; then
    echo "codex CLI not found on PATH. Sign in once with 'codex login'." >&2
    exit 1
fi

# --- Seed a fresh writable workspace (mirrors run_task_local.sh) -----------
TS="$(date +%s)-$$"
RESULTS_DIR="${RESULTS_DIR:-$SOLVE_DIR/runs}"
WORKSPACE="$RESULTS_DIR/$PROBLEM/$TECHSTACK/$TS"
mkdir -p "$WORKSPACE"
cp -a "$PROBLEM_DIR/." "$WORKSPACE/"      # task.md + reference PNGs (+ rubric.md)
cp -a "$SKELETON_DIR" "$WORKSPACE/app"    # the project the agent edits in place
rm -f "$WORKSPACE/rubric.md"              # the agent must NOT see the grading rubric
printf '%s\n' "$PROMPT" > "$WORKSPACE/prompt.txt"

echo "Workspace: $WORKSPACE" >&2

# --- Run the solver --------------------------------------------------------
# Full access mirrors the harness's `claude --dangerously-skip-permissions`:
# the agent must edit files, run Maven (network + ~/.m2), and start a server.
# Scope this to a trusted machine.
CODEX_EFFORT="${CODEX_EFFORT:-medium}"
LAST_MSG="$WORKSPACE/codex-last-message.txt"

CODEX_MODEL_ARGS=()
if [ -n "${CODEX_MODEL:-}" ]; then CODEX_MODEL_ARGS=(-c "model=\"$CODEX_MODEL\""); fi

# The solver may background a dev server (dev.sh / mvn spring-boot:run) to preview
# its work with Playwright. If that outlives codex it keeps port 8080 bound and the
# grader's run.sh can't start. So run codex as its own process-group leader and reap
# the whole group on exit; free port 8080 as a backstop. Mirrors run_task_local.sh.
CODEX_PGID=""
cleanup() {
    if [ -n "$CODEX_PGID" ]; then
        kill -TERM "-$CODEX_PGID" 2>/dev/null || true
        sleep 1
        kill -KILL "-$CODEX_PGID" 2>/dev/null || true
    fi
    # Backstop: free port 8080 if a dev server escaped the process group. This
    # runs at solver exit, before grading starts, so it can't hit the grader.
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti tcp:8080 2>/dev/null | xargs kill 2>/dev/null || true
    fi
}
trap cleanup EXIT

# python wrapper puts codex in a fresh process group (macOS has no setsid).
SETPGRP='import os, sys; os.setpgrp(); os.execvp(sys.argv[1], sys.argv[1:])'
python3 -c "$SETPGRP" \
    codex exec \
    --skip-git-repo-check \
    --dangerously-bypass-approvals-and-sandbox \
    --ephemeral \
    --color never \
    --cd "$WORKSPACE" \
    -c model_reasoning_effort="$CODEX_EFFORT" \
    ${CODEX_MODEL_ARGS[@]+"${CODEX_MODEL_ARGS[@]}"} \
    -o "$LAST_MSG" \
    "$PROMPT" 1>&2 &
CODEX_PID=$!
CODEX_PGID=$CODEX_PID   # codex is the group leader, so pgid == pid
wait "$CODEX_PID" || true

# --- Emit the result for the graders (stdout = promptfoo output) -----------
python3 - "$WORKSPACE" "$LAST_MSG" <<'PY'
import json, os, sys
workspace, last_msg = sys.argv[1], sys.argv[2]
final = ""
if os.path.isfile(last_msg):
    with open(last_msg, encoding="utf-8", errors="replace") as f:
        final = f.read()
print(json.dumps({
    "workspace": workspace,
    "app": os.path.join(workspace, "app"),
    "final": final,
}))
PY
