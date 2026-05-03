"""Agent-specific tools per Pass 3d §A.3.

Each agent gets a sub-package; tool bodies are visible only to that
agent's invocation context (enforced by the @tool decorator's
permissions + the agent's own tool_call dispatch).

D10 Checkpoint 3 ships the first agent-specific tool set:
billing_support's four lookup tools.
"""

from app.agents.tools.agent_specific import billing_support  # noqa: F401

__all__ = ["billing_support"]
