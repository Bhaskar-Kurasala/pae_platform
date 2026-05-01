"""Agents package — surface for the legacy registry + the new
AgenticBaseAgent layer.

Importing `app.agents` is intentionally side-effect-free. To get
the legacy BaseAgent registry populated:

    from app.agents.registry import _ensure_registered
    _ensure_registered()

To use the new AgenticBaseAgent base class:

    from app.agents.agentic_base import AgenticBaseAgent, AgentInput, AgentContext

We deliberately do NOT eager-import `agentic_base` from this
`__init__` module. Doing so cascades into pgvector / numpy via the
agent_memory model, and the resulting import graph trips coverage
instrumentation's "module loaded more than once" guard. The
explicit-path import is also closer to the rest of the codebase's
conventions (every other model/service is imported by full path,
not via package re-exports).
"""
