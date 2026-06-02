#!/usr/bin/env bash
# promptfoo provider wrapper: solve basic_layout with the Claude Code CLI.
# Sets SOLVER_AGENT and hands the prompt/opts/ctx args through to solve.sh.
export SOLVER_AGENT=claude
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/solve.sh" "$@"
