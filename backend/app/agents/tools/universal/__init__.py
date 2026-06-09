"""D10 / Pass 3d §A.1, §D — universal tools available to every agent.

The five tools every `AgenticBaseAgent` with `uses_tools=True` is
expected to have access to:

  • memory_recall   — read from agent_memory via MemoryStore
  • memory_write    — upsert to agent_memory via MemoryStore
  • memory_forget   — delete a single memory row by id
  • log_event       — emit a structured event beyond the auto-logged
                      action row
  • read_own_capability — let an agent read its own AgentCapability
                          declaration (useful for prompts that need
                          to know typical_latency_ms etc.)

Pass 3d §A.1 wording: "Universal tools are imported and registered
automatically when an agent declares `uses_tools=True`. The agent
doesn't list them in its capability declaration — they're implicit."

Importing this package side-effect-registers all five tools with
`app.agents.primitives.tools.registry`. The package itself is
imported from `app.agents.tools.__init__` so any process loading
the tool registry picks them up.

Why this lives in `tools/universal/` not `tools/`:
  Pass 3d §A.1 splits tools into universal / domain / agent-specific
  buckets. Universal tools don't compete for namespace with the
  themed modules (career_tools, code_tools, etc.) — they're a
  separate tier. The directory split makes that taxonomy literal
  on disk.

Design choices honored across all five:
  • Every tool body uses the AsyncSession from a contextvar set by
    the executor's caller. The contextvar pattern matches the one
    `call_agent` uses (see communication.py's _active_session) and
    keeps tool functions async-friendly without an extra session
    parameter on every signature.
  • All inputs / outputs are pydantic models with extra='forbid'.
  • Permissions follow Pass 3d §C.1 standard names.
  • cost_estimate is conservative — these tools are cheap (no
    external calls); zero would also be fair, but a tiny non-zero
    value lets the cost-rollup dashboards distinguish "no calls"
    from "many free calls".
"""

# Import each module so its @tool decorators run at package import.
from app.agents.tools.universal import (  # noqa: F401
    evaluate_student_against_gate,
    log_event,
    memory_forget,
    memory_recall,
    memory_write,
    read_own_capability,
    read_role_transition_gate,
    read_student_accessible_content,
    read_student_lead_in_signals,
    read_student_role_state,
)


__all__ = [
    "evaluate_student_against_gate",
    "log_event",
    "memory_forget",
    "memory_recall",
    "memory_write",
    "read_own_capability",
    "read_role_transition_gate",
    "read_student_accessible_content",
    "read_student_lead_in_signals",
    "read_student_role_state",
]
