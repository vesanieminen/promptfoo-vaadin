#!/usr/bin/env bash
# Seed-only check for basic_layout — the simplest "does the harness work?" test.
#
# Runs ONLY seed.js's beforeAll hook: it (re)creates the per-agent workspaces from
# the agentic-dx-improvement sources and writes the availability manifest
# (workspaces/available.json — agent-skills SHA + skill list + plugin-declared MCP
# servers with a reachability ping). Then it prints that manifest.
#
# No agents, no auth, no Maven, no Playwright — runs in ~2 seconds. Use it to sanity-
# check that the sibling agentic-dx-improvement checkout is wired up and to see, up
# front, exactly what skills/MCP SOURCE (and which version) a run will use.
#
# NOTE: seed.js always WIPES and recreates workspaces/<agent>. Don't run this while a
# solve/verify run (run.sh) is using those workspaces.
#
# Usage:
#   bash basic_layout/seed.sh
#   AGENTIC_DX_DIR=/path/to/agentic-dx-improvement bash basic_layout/seed.sh   # override source
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # promptfoo/basic_layout
cd "$HERE"

echo "[seed.sh] seeding workspaces + writing availability manifest…" >&2
node -e "require('$HERE/seed.js').seed('beforeAll').then(() => process.exit(0)).catch((e) => { console.error(e); process.exit(1); })"

MANIFEST="$HERE/workspaces/available.json"
echo >&2
echo "[seed.sh] manifest → $MANIFEST" >&2
echo "----------------------------------------------------------------------" >&2
if command -v python3 >/dev/null 2>&1; then
  python3 -m json.tool "$MANIFEST"   # pretty-print + validate
else
  cat "$MANIFEST"
fi
