#!/usr/bin/env bash
# Import the git-tracked dataset (bench/data/) into the local promptfoo store.
# Usage: bench/pf-data-pull.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec node --disable-warning=ExperimentalWarning "$DIR/pf-data-pull.mjs" "$@"
