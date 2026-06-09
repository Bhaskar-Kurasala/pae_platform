"""D10 / Pass 3d §D.5 — read_own_capability universal tool.

Self-introspection tool that returns the calling agent's
AgentCapability declaration. Pass 3d §D.5 use case: the
Supervisor's prompt tells specialists "you have ~30 seconds to
respond" — the specialist reads its own typical_latency_ms from
this tool to know its budget.

Per Pass 3d §D.5 spec verbatim:
  • Permissions: none.

Identity discovery:
  The tool needs to know which agent is calling it. Two options:
    1. Take agent_name as input (caller passes its own name)
    2. Recover from the active call chain (the chain's last callee
       is the agent currently running)
  D10 ships option (1) — it's explicit and doesn't depend on the
  call-chain plumbing being fully wired for self-introspection.
  Pass 3d §D.5 does not specify; the explicit-name approach is the
  more conservative interpretation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.agents.capability import get_capability
from app.agents.primitives.tools import tool
from app.schemas.supervisor import AgentCapability


class ReadOwnCapabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "The agent's own name. Pass `self.name` from inside an "
            "AgenticBaseAgent's run(); the tool returns that agent's "
            "AgentCapability declaration."
        ),
    )


class ReadOwnCapabilityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: AgentCapability | None = Field(
        default=None,
        description=(
            "The capability declaration. None when the name has no "
            "registration (e.g. tests, agents whose registry import "
            "didn't fire)."
        ),
    )
    found: bool = Field(
        description="True iff the capability registry knew this agent.",
    )


@tool(
    name="read_own_capability",
    description=(
        "Return this agent's AgentCapability declaration from the "
        "registry. Use to ground prompts in the agent's declared "
        "typical_latency_ms / typical_cost_inr / handoff_targets — "
        "lets the agent reason about its own budget at runtime."
    ),
    input_schema=ReadOwnCapabilityInput,
    output_schema=ReadOwnCapabilityOutput,
    requires=(),
    cost_estimate=0.0,
    timeout_seconds=2.0,
)
async def read_own_capability(
    args: ReadOwnCapabilityInput,
) -> ReadOwnCapabilityOutput:
    """Lookup is O(1) against the in-memory _BY_NAME index. No
    session needed — the registry is process-local."""
    capability = get_capability(args.agent_name)
    return ReadOwnCapabilityOutput(
        capability=capability,
        found=capability is not None,
    )


__all__ = [
    "ReadOwnCapabilityInput",
    "ReadOwnCapabilityOutput",
    "read_own_capability",
]
