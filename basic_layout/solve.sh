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
# CONCURRENCY: two solvers can run at once (`--max-concurrency 2`). Per-run state
# is isolated so nothing collides — see the "isolation" notes below:
#   - server port: a free port per run, via the PORT env (application.properties
#     does `server.port=${PORT:8080}`), used by the solver AND the grader;
#   - Claude config + Playwright MCP profile: a per-workspace home (claude-home.sh);
#   - workspace dirs: unique per run (agent + timestamp + pid).
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
printf '%s\n' "$PROMPT" > "$WORKSPACE/prompt.txt"   # the task prompt (no run-env noise)

# --- Per-run server port (so concurrent runs don't collide on 8080) --------
# application.properties has `server.port=${PORT:8080}`, and Spring resolves the
# PORT env var, so exporting it moves the whole app (dev.sh / run.sh) off 8080.
RUN_PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("",0)); print(s.getsockname()[1]); s.close()')"
printf '%s\n' "$RUN_PORT" > "$WORKSPACE/.run-port"
export PORT="$RUN_PORT"
echo "Solver: $SOLVER_AGENT   Port: $RUN_PORT   Workspace: $WORKSPACE" >&2

# Operational note appended to the SOLVER prompt only (prompt.txt stays the task).
# Both agents get the same note, so the comparison stays fair.
SOLVE_PROMPT="$(cat <<EOF
$PROMPT

--- Run environment (not part of the task) ---
This run has a dedicated server port. The PORT environment variable is set to $RUN_PORT and application.properties honours it (server.port=\${PORT:8080}), so the app starts on port $RUN_PORT. Use http://localhost:$RUN_PORT when previewing in a browser; do not hardcode port 8080.
EOF
)"

# --- Shared cleanup: reap the agent's process group + free this run's port -
# The solver may background a dev server (dev.sh / mvn spring-boot:run) to preview
# its work. If that outlives the agent it keeps RUN_PORT bound and the grader's
# run.sh can't start. Run the agent as its own process-group leader and reap the
# whole group on exit; free RUN_PORT (this run's port only) as a backstop. Mirrors
# the watchdog in run_task_local.sh. Runs at solver exit, before grading begins.
AGENT_PGID=""
cleanup() {
    if [ -n "$AGENT_PGID" ]; then
        kill -TERM "-$AGENT_PGID" 2>/dev/null || true
        sleep 1
        kill -KILL "-$AGENT_PGID" 2>/dev/null || true
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti tcp:"$RUN_PORT" 2>/dev/null | xargs kill 2>/dev/null || true
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
            "$SOLVE_PROMPT" 1>&2 &
        ;;
    claude)
        if ! command -v claude >/dev/null 2>&1; then
            echo "claude CLI not found on PATH." >&2
            exit 1
        fi
        # Per-workspace Claude home: isolates .claude.json/session state AND points
        # the Playwright MCP at an isolated browser profile, so a concurrent Claude
        # solver/grader can't deadlock on the shared MCP profile lock.
        export CLAUDE_CONFIG_DIR="$(AGENTIC_DX_DIR="$AGENTIC_DX_DIR" bash "$SOLVE_DIR/claude-home.sh" "$WORKSPACE")"
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
                -p "$SOLVE_PROMPT"
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
