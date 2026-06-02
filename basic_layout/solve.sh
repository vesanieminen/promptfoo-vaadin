#!/usr/bin/env bash
# promptfoo "exec" provider that runs an agentic CLI as the SOLVER for the
# agentic-dx `basic_layout` task. Mirrors run_task_local.sh from the
# agentic-dx-improvement harness, adapted to promptfoo.
#
# The agent is selected by SOLVER_AGENT (codex|claude); the thin wrappers
# solve-codex.sh / solve-claude.sh set it. promptfoo calls a wrapper as:
#     solve-<agent>.sh "<rendered prompt>" "<optsJSON>" "<ctxJSON>"
# and it execs this script with the prompt as $1.
#
# We seed a fresh writable workspace (skeleton + task files, rubric stripped),
# run the agent in it, and print {workspace, app, final} JSON to stdout. stdout
# IS the promptfoo "output" the graders parse, so ALL agent chatter goes to
# stderr / a log file to keep stdout clean JSON.
#
# No `set -u`: macOS bash 3.2 errors on empty-array expansion under it.
set -o pipefail

PROMPT="${1:-}"

# --- Resolve locations (independent of cwd; we use BASH_SOURCE) ------------
SOLVE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # promptfoo/basic_layout
REPO_ROOT="$(cd "$SOLVE_DIR/.." && pwd)"                     # promptfoo

# agentic-dx-improvement is the source of truth for problem/skeleton/base prompt.
AGENTIC_DX_DIR="${AGENTIC_DX_DIR:-$REPO_ROOT/../agentic-dx-improvement}"
PROBLEM="${PROBLEM:-basic_layout}"
TECHSTACK="${TECHSTACK:-vaadin}"
SOLVER_AGENT="${SOLVER_AGENT:-codex}"

PROBLEM_DIR="$AGENTIC_DX_DIR/problems/$PROBLEM"
SKELETON_DIR="$AGENTIC_DX_DIR/skeletons/$TECHSTACK"

for p in "$PROBLEM_DIR" "$SKELETON_DIR"; do
    if [ ! -d "$p" ]; then
        echo "Missing required path: $p (set AGENTIC_DX_DIR to your agentic-dx-improvement checkout)" >&2
        exit 1
    fi
done

# --- Seed a fresh writable workspace (mirrors run_task_local.sh) -----------
TS="$(date +%s)-$$"
RESULTS_DIR="${RESULTS_DIR:-$SOLVE_DIR/runs}"
WORKSPACE="$RESULTS_DIR/$PROBLEM/$TECHSTACK/$SOLVER_AGENT/$TS"
mkdir -p "$WORKSPACE"
cp -a "$PROBLEM_DIR/." "$WORKSPACE/"      # task.md + reference PNGs (+ rubric.md)
cp -a "$SKELETON_DIR" "$WORKSPACE/app"    # the project the agent edits in place
rm -f "$WORKSPACE/rubric.md"              # the agent must NOT see the grading rubric
printf '%s\n' "$PROMPT" > "$WORKSPACE/prompt.txt"

echo "Solver: $SOLVER_AGENT   Workspace: $WORKSPACE" >&2

# --- Shared cleanup: reap the agent's process group + free port 8080 -------
# The solver may background a dev server (dev.sh / mvn spring-boot:run) to preview
# its work with Playwright. If that outlives the agent it keeps port 8080 bound and
# the grader's run.sh can't start. So run the agent as its own process-group leader
# and reap the whole group on exit; free port 8080 as a backstop. Mirrors the
# watchdog in run_task_local.sh. Cleanup runs at solver exit, before grading begins.
AGENT_PGID=""
cleanup() {
    if [ -n "$AGENT_PGID" ]; then
        kill -TERM "-$AGENT_PGID" 2>/dev/null || true
        sleep 1
        kill -KILL "-$AGENT_PGID" 2>/dev/null || true
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti tcp:8080 2>/dev/null | xargs kill 2>/dev/null || true
    fi
}
trap cleanup EXIT

# python wrapper puts the agent in a fresh process group (macOS has no setsid).
SETPGRP='import os, sys; os.setpgrp(); os.execvp(sys.argv[1], sys.argv[1:])'
LAST_MSG="$WORKSPACE/agent-last-message.txt"        # codex final message (-o)
CLAUDE_LOG="$WORKSPACE/claude-agent.log.jsonl"      # claude stream-json transcript

# Full access mirrors the harness's `--dangerously-skip-permissions`: the agent
# must edit files, run Maven (network + ~/.m2), and start a server. Trusted host only.
case "$SOLVER_AGENT" in
    codex)
        if ! command -v codex >/dev/null 2>&1; then
            echo "codex CLI not found on PATH. Sign in once with 'codex login'." >&2
            exit 1
        fi
        CODEX_EFFORT="${CODEX_EFFORT:-medium}"
        CODEX_MODEL_ARGS=()
        if [ -n "${CODEX_MODEL:-}" ]; then CODEX_MODEL_ARGS=(-c "model=\"$CODEX_MODEL\""); fi
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
        ;;
    claude)
        if ! command -v claude >/dev/null 2>&1; then
            echo "claude CLI not found on PATH." >&2
            exit 1
        fi
        # Reuse the harness's isolated home (Vaadin plugin + Playwright MCP).
        export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$AGENTIC_DX_DIR/.bench-claude-home}"
        CLAUDE_MODEL_ARGS=()
        if [ -n "${CLAUDE_MODEL:-}" ]; then CLAUDE_MODEL_ARGS+=(--model "$CLAUDE_MODEL"); fi
        if [ -n "${CLAUDE_EFFORT:-}" ]; then CLAUDE_MODEL_ARGS+=(--effort "$CLAUDE_EFFORT"); fi
        # claude has no --cd, so run it from the workspace in a subshell. bash execs
        # the subshell's last command in place, so $! is the group-leader pid.
        (
            cd "$WORKSPACE"
            python3 -c "$SETPGRP" \
                claude ${CLAUDE_MODEL_ARGS[@]+"${CLAUDE_MODEL_ARGS[@]}"} \
                --dangerously-skip-permissions \
                --output-format stream-json --verbose \
                -p "$PROMPT"
        ) > "$CLAUDE_LOG" 2>&1 &
        ;;
    *)
        echo "Unknown SOLVER_AGENT: '$SOLVER_AGENT' (use codex|claude)" >&2
        exit 1
        ;;
esac
AGENT_PID=$!
AGENT_PGID=$AGENT_PID   # group leader, so pgid == pid
wait "$AGENT_PID" || true

# --- Emit the result for the graders (stdout = promptfoo output) -----------
python3 - "$WORKSPACE" "$LAST_MSG" "$CLAUDE_LOG" <<'PY'
import json, os, sys
workspace, last_msg, claude_log = sys.argv[1], sys.argv[2], sys.argv[3]
final = ""
if os.path.isfile(last_msg):
    with open(last_msg, encoding="utf-8", errors="replace") as f:
        final = f.read()
elif os.path.isfile(claude_log):
    # best-effort: the final `result` event's text from the stream-json log
    try:
        with open(claude_log, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("type") == "result" and isinstance(ev.get("result"), str):
                    final = ev["result"]
    except Exception:
        pass
print(json.dumps({
    "workspace": workspace,
    "app": os.path.join(workspace, "app"),
    "final": final,
}))
PY
