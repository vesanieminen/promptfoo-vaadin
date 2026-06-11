#!/usr/bin/env bash
# cron-run.sh — headless nightly driver for the agentic-dx benchmark on a
# Raspberry Pi 5 (or any headless Linux box), launched from crontab.
#
# What it does:
#   - serializes runs with flock (a full sweep can take hours; never overlap)
#   - sets a cron-safe PATH + JAVA_HOME (cron starts with a minimal env)
#   - pins the run to the skills A/B (claude vs claude-no-skills) at parallel 2
#   - logs each run to bench/logs/run-<timestamp>.log and prunes old logs
#   - delegates to bench/run.sh (which warms ~/.m2, seeds, solves, verifies)
#
# Auth: by default this relies on the AMBIENT Claude login on this box
#   (~/.claude/.credentials.json, written by a one-time `claude login`; it
#   auto-refreshes). To override, export ANTHROPIC_API_KEY or
#   CLAUDE_CODE_OAUTH_TOKEN below, or drop the bare value in bench/.bench-token
#   (run.sh picks it up). See bench/README.md.
#
# Crontab (run as the SAME user that did `claude login`; 2:30am nightly):
#   30 2 * * * /home/pi/code/promptfoo/bench/cron-run.sh
#
# Manual test (exercises the exact path cron will use):
#   /home/pi/code/promptfoo/bench/cron-run.sh
set -euo pipefail

# ---- EDIT ME for your Pi -------------------------------------------------
# Cron runs with a minimal PATH; list every dir holding java/mvn/node/npx/claude.
export PATH="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"
# JDK 25 (the Vaadin skeleton needs Java 25). Point at your arm64 JDK.
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/temurin-25-jdk-arm64}"
export PATH="$JAVA_HOME/bin:$PATH"
# Absolute path to the agentic-dx-improvement checkout (problems + skeleton +
# the agent-skills plugin the `claude` row loads). Submodules must be inited.
export AGENTIC_DX_DIR="${AGENTIC_DX_DIR:-$HOME/code/agentic-dx-improvement}"
# --------------------------------------------------------------------------

# What to run (override via the environment / crontab if you like):
export AGENT="${AGENT:-claude,claude-no-skills}"   # the skills A/B
export MAX_CONCURRENCY="${MAX_CONCURRENCY:-2}"      # 2 fits 8 GB; 3 risks OOM
# PROBLEM unset => all three problems, run sequentially (peak is still 2 rows,
# so RAM is unchanged — only total wall-clock grows). Set e.g.
#   export PROBLEM="basic_layout"
# to run just one problem and finish in ~1-2 h instead of a multi-hour sweep.
# Builds are slower on ARM — give a wedged row more rope than the 45-min default.
export PROMPTFOO_EVAL_TIMEOUT_MS="${PROMPTFOO_EVAL_TIMEOUT_MS:-3600000}"   # 60 min/row
# Optional RAM guard: cap EVERY JVM (Maven build + the Spring Boot app under
# test, which otherwise grabs ~25% of RAM as heap). Uncomment + tune if two live
# apps trigger the OOM killer. Node/Vite (frontend build) memory is separate.
# export JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=15"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG_DIR="bench/logs"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/run-$TS.log"

# Self-lock: if a previous sweep is still running, note it and bail (don't pile up).
LOCK="$LOG_DIR/.cron.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[cron-run $TS] previous run still going (lock held) — skipping this tick." >> "$LOG"
  exit 0
fi

{
  echo "[cron-run $TS] start: AGENT=$AGENT MAX_CONCURRENCY=$MAX_CONCURRENCY PROBLEM=${PROBLEM:-<all>}"
  echo "[cron-run $TS] JAVA_HOME=$JAVA_HOME  AGENTIC_DX_DIR=$AGENTIC_DX_DIR"
  java -version 2>&1 | head -1 || true
  bash bench/run.sh
  echo "[cron-run $TS] done. View results from your laptop:"
  echo "[cron-run $TS]   ssh -L 15500:localhost:15500 <pi>   then   npx promptfoo@latest view"
} >> "$LOG" 2>&1

# Keep the most recent 30 run logs.
ls -1t "$LOG_DIR"/run-*.log 2>/dev/null | tail -n +31 | xargs -r rm -f || true
