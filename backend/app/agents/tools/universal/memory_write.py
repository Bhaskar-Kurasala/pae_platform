"""D10 / Pass 3d §D.2 — memory_write universal tool.

Audited @tool wrapper around `MemoryStore.write`. Lets agents
upsert a memory row keyed on (user_id, agent_name, scope, key)
with cost / latency / outcome surfacing through the standard
agent_tool_calls audit row.

Per Pass 3d §D.2 spec:
  • Permissions: write:agent_memory.
  • Latency: Fast (20-100ms — includes embedding generation).
  • Status: D2 wrapper.

Naming note: D3 shipped `store_memory` as a stub. Pass 3d §D names
it `memory_write`. D10 implements the Pass 3d name and retires the
D3 stub via app/agents/tools/__init__.py.

Idempotency: same (user_id, agent_name, scope, key) → in-place
update. The output's `was_update` field tells callers which path
ran (useful for observability).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.memory import MemoryStore, MemoryWrite
from app.agents.primitives.tools import tool


class MemoryWriteInput(BaseModel):
    """Mirror of MemoryWrite minus the embedding (the store computes it)."""

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Owning student. Required for scope='user' to be useful; "
            "may be None for scope='agent' or scope='global'."
        ),
    )
    agent_name: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "Agent the memory is written by. Tooling agents and the "
            "agent calling this tool may differ; pass the agent the "
            "memory should be attributed to."
        ),
    )
    scope: Literal["user", "agent", "global"] = Field(
        default="user",
        description="Memory scope per Pass 3d §A.4.",
    )
    key: str = Field(
        min_length=1,
        max_length=512,
        description=(
            "Memory key. Use the namespacing conventions from Pass 3c "
            "§A.5: 'pref:*', 'mastery:*', 'interaction:*', etc."
        ),
    )
    value: dict[str, Any] = Field(
        description="Free-form JSON payload of the memory.",
    )
    valence: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description=(
            "Affective signal: -1 strongly negative, +1 strongly "
            "positive, 0 neutral. Used by interrupt_agent's risk "
            "scoring (Pass 3h)."
        ),
    )
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description=(
            "Caller's confidence in this memory's accuracy. The "
            "decay job lowers confidence on idle rows; this is the "
            "starting value."
        ),
    )
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "Optional explicit expiry. None = retained until "
            "decayed below threshold."
        ),
    )


class MemoryWriteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: uuid.UUID
    was_update: bool = Field(
        description=(
            "True when the call updated an existing key, False when it "
            "created a new row. Useful for observability — repeated "
            "writes of the same key should mostly be updates."
        ),
    )


@tool(
    name="memory_write",
    description=(
        "Upsert a memory row keyed on (user_id, agent_name, scope, "
        "key). Same key + same target → in-place update. Returns the "
        "row id and a flag indicating whether the call wrote new vs "
        "updated existing. Use when the agent has learned something "
        "durable about the student or the cohort that future "
        "invocations should see."
    ),
    input_schema=MemoryWriteInput,
    output_schema=MemoryWriteOutput,
    requires=("write:agent_memory",),
    cost_estimate=0.0001,
    timeout_seconds=10.0,
)
async def memory_write(args: MemoryWriteInput) -> MemoryWriteOutput:
    """Run the upsert. The contextvar-supplied session is what's
    written into; the caller's transaction owns commit/rollback."""
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "memory_write called without an active session. The tool "
            "body relies on the contextvar set by call_agent; if you "
            "are testing the body directly, set _active_session before "
            "invoking."
        )

    store = MemoryStore(session)
    # Detect update-vs-create by probing first. The MemoryStore.write
    # method returns the row but doesn't expose whether it was an
    # update — we read that signal ourselves so the tool's output
    # surface stays accurate without changing the primitive.
    pre_existing = await store._find_one(  # type: ignore[attr-defined]
        user_id=args.user_id,
        agent_name=args.agent_name,
        scope=args.scope,
        key=args.key,
    )
    was_update = pre_existing is not None

    row = await store.write(
        MemoryWrite(
            user_id=args.user_id,
            agent_name=args.agent_name,
            scope=args.scope,
            key=args.key,
            value=args.value,
            valence=args.valence,
            confidence=args.confidence,
            expires_at=args.expires_at,
        )
    )
    return MemoryWriteOutput(memory_id=row.id, was_update=was_update)


__all__ = ["MemoryWriteInput", "MemoryWriteOutput", "memory_write"]
