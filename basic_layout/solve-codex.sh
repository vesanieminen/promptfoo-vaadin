#!/usr/bin/env bash
# promptfoo provider wrapper: solve basic_layout with the Codex CLI.
# Sets SOLVER_AGENT and hands the prompt/opts/ctx args through to solve.sh.
export SOLVER_AGENT=codex
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/solve.sh" "$@"
