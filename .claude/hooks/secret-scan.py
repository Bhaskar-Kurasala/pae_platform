#!/usr/bin/env python3
"""PreToolUse hook (matcher: Write).

Blocks a Write whose content contains a likely hardcoded secret.

Claude Code delivers the hook payload as JSON on stdin. On PreToolUse the file
does not exist yet, so we scan the *content being written*
(tool_input.content), not the file on disk. Exit code 2 is the blocking signal:
stderr is fed back to Claude and the Write is denied.
"""
from __future__ import annotations

import json
import re
import sys

# Matches assignments like:  api_key = "abcd1234...."  /  PASSWORD: 'hunter2hunter'
_SECRET = re.compile(
    r"""(api[_-]?key|secret[_-]?key|secret|password|passwd|token|bearer)\s*[:=]\s*['"][^'"]{8,}['"]""",
    re.IGNORECASE,
)

# Skip obvious non-secrets: env lookups, settings refs, placeholders.
_ALLOW = re.compile(
    r"""(os\.environ|getenv|settings\.|config\.|process\.env|\$\{?[A-Z0-9_]+\}?"""
    r"""|example|placeholder|dummy|fake|sample|xxx+|changeme|your[-_]?|<[^>]+>|\.\.\.)""",
    re.IGNORECASE,
)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # Never block on a parse failure.

    content = (data.get("tool_input", {}) or {}).get("content", "") or ""
    for lineno, line in enumerate(content.splitlines(), 1):
        if _SECRET.search(line) and not _ALLOW.search(line):
            print(
                "BLOCKED: possible hardcoded secret detected "
                f"(line {lineno}):\n  {line.strip()[:120]}\n"
                "Use environment variables (.env, git-ignored) instead.",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
