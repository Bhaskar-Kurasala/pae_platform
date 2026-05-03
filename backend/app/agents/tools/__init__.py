"""Tool stubs + real tools for the Agentic OS.

Importing this package triggers each module's `@tool` decorators,
populating `app.agents.primitives.tools.registry`. Mirrors the
agent registry's import-time-side-effect pattern.

Two tiers of tools live here per Pass 3d §A.1:

  • Universal (`tools.universal.*`) — implicit on every agent that
    has uses_tools=True. Memory ops, log_event, self-introspection.
    Implemented in D10 (the first migration; per Pass 3d §I, the
    first migration shoulders the universal-tool build cost).

  • Themed modules (career_tools, code_tools, ...) — domain or
    agent-specific tools. Some are still D3 stubs awaiting their
    consuming agent's migration.

D3 stubs `recall_memory` and `store_memory` (in memory_tools.py)
were ALSO superseded by Pass 3d §D's universal tools `memory_recall`
and `memory_write`. The names differ (verb-noun reversed) which
allows both to register without collision, but D10 retires the D3
stubs by removing memory_tools from the import block — they would
otherwise sit in the registry forever as dead `is_stub=True`
NotImplementedError-raisers, which is exactly the "dead stubs
littering the registry" anti-pattern Pass 3d cautions against in §A.

Add a new tool by:
  1. Pick the right themed module (or universal/, or create one)
  2. Define pydantic input + output schemas
  3. Decorate an async function with @tool(...)
  4. Add the module to the import block below

Tests can wipe and re-import this package to get a clean registry.
"""

from __future__ import annotations

# noqa block: each import side-effect-registers tools at import time.
# Universal tools come first because every agent gets them.
from app.agents.tools import universal  # noqa: F401
from app.agents.tools import (  # noqa: F401
    career_tools,
    code_tools,
    content_tools,
    github_tools,
    student_tools,
)


__all__ = [
    "career_tools",
    "code_tools",
    "content_tools",
    "github_tools",
    "student_tools",
    "universal",
]
