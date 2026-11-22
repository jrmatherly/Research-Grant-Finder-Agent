#!/bin/bash
INPUT=$(cat)
command -v jq >/dev/null || exit 0
[ "$(echo "$INPUT" | jq -r '.stop_hook_active' 2>/dev/null)" = "true" ] && exit 0
command -v uv >/dev/null || exit 0
[ -z "$(git -C "$CLAUDE_PROJECT_DIR" status --porcelain -- '*.py')" ] && exit 0
cd "$CLAUDE_PROJECT_DIR/NIH Extractor" || exit 0
uv run --no-project --with pytest pytest -q -p no:cacheprovider 1>&2 || exit 2
