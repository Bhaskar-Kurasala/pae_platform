#!/usr/bin/env bash
# PostToolUse hook (matcher: Write|Edit).
# Auto-formats the file Claude just wrote/edited.
#
# Claude Code delivers the hook payload as JSON on stdin, NOT as a ${file}
# shell variable. We extract tool_input.file_path from that JSON.
set -uo pipefail

FILE=$(python3 -c 'import sys, json; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))' 2>/dev/null || true)
[ -z "${FILE}" ] && exit 0
[ -f "${FILE}" ] || exit 0

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

case "${FILE##*.}" in
  py)
    (cd "${ROOT}/backend" && uv run ruff check --fix "${FILE}" >/dev/null 2>&1; \
                             uv run ruff format "${FILE}" >/dev/null 2>&1) || true
    ;;
  ts | tsx | js | jsx)
    (cd "${ROOT}/frontend" && npx --no-install eslint --fix "${FILE}" >/dev/null 2>&1) || true
    ;;
esac

exit 0
