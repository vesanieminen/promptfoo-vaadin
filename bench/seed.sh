#!/usr/bin/env bash
# Seed-only smoke test — the simplest "does the harness work?" check.
#
# Runs ONLY seed.js's beforeAll hook for ONE problem: it (re)creates that problem's
# per-agent workspaces from the agentic-dx-improvement sources and writes the
# availability manifest (workspaces/<problem>/available.json — agent-skills SHA +
# skill list + plugin-declared MCP servers with a reachability ping). Then it prints
# that manifest.
#
# No agents, no auth, no Maven, no Playwright — runs in ~2 seconds. Use it to sanity-
# check that the agentic-dx-improvement checkout is wired up and to see, up front,
# exactly what skills/MCP SOURCE (and which version) a run will use.
#
# NOTE: seed.js always WIPES and recreates workspaces/<problem>/<agent>. Don't run
# this while a solve/verify run (run.sh) is using that problem's workspaces.
#
# Usage:
#   bash bench/seed.sh                                  # default problem (basic_layout)
#   PROBLEM=md_ui_spec bash bench/seed.sh               # a specific problem
#   AGENTIC_DX_DIR=/path/to/agentic-dx-improvement bash bench/seed.sh   # override source
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # promptfoo/bench
cd "$HERE"

PROBLEM="${PROBLEM:-basic_layout}"   # matches seed.js's bench.currentProblem() default
export PROBLEM

echo "[seed.sh] seeding $PROBLEM workspaces + writing availability manifest…" >&2
node -e "require('$HERE/seed.js').seed('beforeAll').then(() => process.exit(0)).catch((e) => { console.error(e); process.exit(1); })"

MANIFEST="$HERE/workspaces/$PROBLEM/available.json"
echo >&2
echo "[seed.sh] manifest → $MANIFEST" >&2
echo "----------------------------------------------------------------------" >&2
if command -v python3 >/dev/null 2>&1; then
  python3 -m json.tool "$MANIFEST"   # pretty-print + validate
else
  cat "$MANIFEST"
fi
