#!/usr/bin/env bash
# Create (idempotently) an ISOLATED Claude config dir for a workspace, so that
# concurrent Claude runs (a Claude solver and/or the Claude graders) don't share:
#   - .claude.json / session state in one config dir, and
#   - the Playwright MCP browser profile, which uses a singleton lock — two
#     concurrent browsers on one persistent profile deadlock.
#
# It copies the harness's bench home (Vaadin plugin + base config) into
# <workspace>/.claude-home, then rewrites the Playwright MCP registration to use
# an in-memory (`--isolated`) profile and a per-workspace `--output-dir`.
#
# Prints the config dir path on stdout; everything else goes to stderr.
set -o pipefail

WS="${1:?usage: claude-home.sh <workspace>}"
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF/.." && pwd)"
AGENTIC_DX_DIR="${AGENTIC_DX_DIR:-$REPO_ROOT/../agentic-dx-improvement}"
SRC="${BENCH_CLAUDE_HOME:-$AGENTIC_DX_DIR/.bench-claude-home}"
DEST="$WS/.claude-home"
MARK="$DEST/.bl-ready"

if [ ! -f "$MARK" ]; then
    mkdir -p "$DEST"
    if [ -d "$SRC" ]; then
        cp -a "$SRC/." "$DEST/" 2>/dev/null || true
    else
        echo "claude-home.sh: bench home not found at $SRC (set BENCH_CLAUDE_HOME)" >&2
    fi
    # Rewrite the Playwright MCP to an isolated, per-workspace profile + output dir.
    python3 - "$DEST/.claude.json" "$WS/.playwright-mcp" <<'PY'
import json, os, sys
cfg, outdir = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(cfg)) if os.path.isfile(cfg) else {}
except Exception:
    d = {}
if not isinstance(d, dict):
    d = {}
servers = d.setdefault("mcpServers", {})
servers["playwright"] = {
    "type": "stdio",
    "command": "npx",
    "args": ["--yes", "@playwright/mcp@latest", "--browser", "chromium",
             "--headless", "--isolated", "--output-dir", outdir],
    "env": {},
}
with open(cfg, "w") as f:
    json.dump(d, f, indent=2)
PY
    : > "$MARK"
fi
printf '%s\n' "$DEST"
