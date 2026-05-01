"""Tool stubs for the Agentic OS.

Importing this package triggers each module's `@tool` decorators,
populating `app.agents.primitives.tools.registry`. Mirrors the
agent registry's import-time-side-effect pattern.

Add a new tool by:
  1. Pick the right themed module (or create one)
  2. Define pydantic input + output schemas
  3. Decorate an async function with @tool(...)
  4. Add the module to the import block below

Tests can wipe and re-import this package to get a clean registry.
"""

from __future__ import annotations

# noqa block: each import side-effect-registers tools at import time.
from app.agents.tools import (  # noqa: F401
    career_tools,
    code_tools,
    content_tools,
    github_tools,
    memory_tools,
    student_tools,
)


__all__ = [
    "career_tools",
    "code_tools",
    "content_tools",
    "github_tools",
    "memory_tools",
    "student_tools",
]
