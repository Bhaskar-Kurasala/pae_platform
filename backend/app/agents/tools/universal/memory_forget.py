"""D10 / Pass 3d §D.3 — memory_forget universal tool.

Audited @tool wrapper around `MemoryStore.forget`. Lets agents
explicitly remove a memory row, and (for ops cases) fire a bulk
forget by user_id or key pattern with the safety `confirm=True`
guard from Pass 3d §D.3.

Per Pass 3d §D.3 spec verbatim:
  • Permissions: write:agent_memory.
  • The confirm=True requirement for bulk operations is a safety
    check against agents accidentally wiping student memory.

Bulk-forget implementation note:
  D2's MemoryStore exposes only `forget(memory_id)` for single-row
  deletion. The bulk paths (`user_id` / `key_pattern`) needed by
  the Pass 3d §D.3 spec are implemented here via the SQLAlchemy
  session because exposing them on MemoryStore would surface a
  primitive that's only ever used through the tool boundary. The
  tool body keeps the primitive narrow.
"""

from __future__ import annotations

import uuid

import structlog
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.memory import MemoryStore
from app.agents.primitives.tools import tool
from app.models.agent_memory import AgentMemory

log = structlog.get_logger().bind(layer="tools.universal.memory_forget")


class MemoryForgetInput(BaseModel):
    """Three mutually-explainable forget modes per Pass 3d §D.3.

    Exactly one of (memory_id, user_id, key_pattern) should be set.
    The model validator enforces that — the tool is for narrow,
    intentional deletes; ambiguous calls are caller bugs.
    """

    model_config = ConfigDict(extra="forbid")

    memory_id: uuid.UUID | None = Field(
        default=None,
        description="Forget exactly one row by id. Bulk-flag not required.",
    )
    user_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Forget every memory for this user. REQUIRES confirm=True "
            "(safety check from Pass 3d §D.3)."
        ),
    )
    key_pattern: str | None = Field(
        default=None,
        max_length=512,
        description=(
            "SQL LIKE pattern (case-insensitive) on key. e.g. "
            "'pref:%' to drop every preference. REQUIRES confirm=True."
        ),
    )
    confirm: bool = Field(
        default=False,
        description=(
            "Safety gate for bulk operations. Single-row forgets via "
            "`memory_id` do NOT need confirm; user_id / key_pattern "
            "DO. Pass 3d §D.3 makes this a tool-layer guard against "
            "accidental wipes."
        ),
    )

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "MemoryForgetInput":
        targets = sum(
            1
            for x in (self.memory_id, self.user_id, self.key_pattern)
            if x is not None
        )
        if targets == 0:
            raise ValueError(
                "memory_forget requires exactly one of memory_id, "
                "user_id, or key_pattern; got none."
            )
        if targets > 1:
            raise ValueError(
                "memory_forget requires exactly one of memory_id, "
                "user_id, or key_pattern; got multiple."
            )
        bulk = self.user_id is not None or self.key_pattern is not None
        if bulk and not self.confirm:
            raise ValueError(
                "Bulk memory_forget (by user_id or key_pattern) "
                "requires confirm=True."
            )
        return self


class MemoryForgetOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forgotten_count: int = Field(
        ge=0,
        description="Number of rows actually deleted.",
    )


@tool(
    name="memory_forget",
    description=(
        "Delete memory rows. Three modes: by exact memory_id "
        "(no confirm needed), by user_id (wipes a user's bank, "
        "confirm=True required), by key_pattern (SQL LIKE on key, "
        "confirm=True required). Use sparingly — most stale memories "
        "should be left for the decay sweep."
    ),
    input_schema=MemoryForgetInput,
    output_schema=MemoryForgetOutput,
    requires=("write:agent_memory",),
    cost_estimate=0.0,
    timeout_seconds=10.0,
)
async def memory_forget(args: MemoryForgetInput) -> MemoryForgetOutput:
    """Execute the appropriate delete given which target was set.

    Single-row uses MemoryStore.forget for consistency with the
    primitive's own audit log line. Bulk paths go directly to the
    session because MemoryStore deliberately doesn't expose them.
    """
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "memory_forget called without an active session. The tool "
            "body relies on the contextvar set by call_agent; if you "
            "are testing the body directly, set _active_session before "
            "invoking."
        )

    if args.memory_id is not None:
        store = MemoryStore(session)
        removed = await store.forget(args.memory_id)
        return MemoryForgetOutput(forgotten_count=1 if removed else 0)

    if args.user_id is not None:
        result = await session.execute(
            delete(AgentMemory).where(AgentMemory.user_id == args.user_id)
        )
        count = result.rowcount or 0
        log.info(
            "memory_forget.bulk_user",
            user_id=str(args.user_id),
            forgotten_count=count,
        )
        return MemoryForgetOutput(forgotten_count=count)

    # key_pattern path
    assert args.key_pattern is not None  # noqa: S101 — guarded by model_validator
    pattern = args.key_pattern.lower()
    result = await session.execute(
        delete(AgentMemory).where(func.lower(AgentMemory.key).like(pattern))
    )
    count = result.rowcount or 0
    log.info(
        "memory_forget.bulk_pattern",
        pattern=args.key_pattern,
        forgotten_count=count,
    )
    return MemoryForgetOutput(forgotten_count=count)


__all__ = ["MemoryForgetInput", "MemoryForgetOutput", "memory_forget"]
