#!/usr/bin/env bash
# Promptfoo custom-script provider that routes each prompt through the Codex CLI
# using your ChatGPT subscription auth (set up once with `codex login`).
#
# Promptfoo calls this as:  codex-provider.sh "<rendered prompt>" "<optsJSON>" "<ctxJSON>"
# We only need the first arg. Whatever we print to stdout becomes the model output.
# Note: no `set -u` — macOS bash 3.2 errors on empty-array expansion under it.
set -o pipefail

PROMPT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LAST_MSG="$(mktemp)"
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$LAST_MSG" "$SCRATCH"' EXIT

# If a schema file sits next to this script, force Codex's final answer to match it
# (clean JSON, no markdown fences). Optional — delete the file to get free-form text.
SCHEMA_ARGS=()
if [[ -f "$SCRIPT_DIR/codex-output-schema.json" ]]; then
  SCHEMA_ARGS=(--output-schema "$SCRIPT_DIR/codex-output-schema.json")
fi

# Non-interactive, read-only sandbox, isolated empty cwd, no persisted session.
# Codex's progress chatter goes to stderr; only the final message lands in $LAST_MSG.
codex exec \
  --skip-git-repo-check \
  --sandbox read-only \
  --ephemeral \
  --color never \
  --cd "$SCRATCH" \
  -c model_reasoning_effort="medium" \
  "${SCHEMA_ARGS[@]}" \
  -o "$LAST_MSG" \
  "$PROMPT" 1>&2

# promptfoo reads stdout as the output.
cat "$LAST_MSG"
