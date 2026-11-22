#!/bin/bash
INPUT=$(cat)
command -v jq >/dev/null || exit 0
[ "$(echo "$INPUT" | jq -r '.stop_hook_active' 2>/dev/null)" = "true" ] && exit 0
command -v uv >/dev/null || exit 0
cd "${0%/*}/../../NIH Extractor" || exit 0
uv run --locked pytest -q -p no:cacheprovider 1>&2 || exit 2
