#!/usr/bin/env bash
# Export local promptfoo evals into the git-tracked dataset (bench/data/).
# Usage: bench/pf-data-push.sh [--all] [<eval-id> ...]
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec node --disable-warning=ExperimentalWarning "$DIR/pf-data-push.mjs" "$@"
