"""Memory-layer tools.

Wraps `MemoryStore` so agents can recall + store via the executor's
audit/timeout/retry path instead of touching the store directly.
That's how the inter-agent boundary stays clean: an agent that wants
to remember something goes through `recall_memory` / `store_memory`
just like any other tool, and we get one row per call in
`agent_tool_calls`.

Both stubs raise NotImplementedError today. The real implementation
lands in a follow-up that gets a SessionLocal from the surrounding
agent context (D7) and threads it through. The schemas are stable
and represent the public contract.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.tools import tool


# ── recall_memory ───────────────────────────────────────────────────


class RecallMemoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    user_id: uuid.UUID | None = None
    agent_name: str | None = Field(default=None, max_length=200)
    scope: Literal["user", "agent", "global"] | None = None
    k: int = Field(default=5, ge=1, le=50)
    mode: Literal["hybrid", "semantic", "structured"] = "hybrid"
    min_similarity: float | None = Field(default=None, ge=0.0, le=1.0)


class RecalledMemory(BaseModel):
    """One row returned from recall_memory.

    Subset of `MemoryRow` — we don't surface valence/confidence to
    callers by default because most agents don't need them; if they
    do, they read them via the lower-level MemoryStore. The boundary
    here is "what does an agent need to make a decision?"
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    key: str
    value: dict[str, Any]
    similarity: float | None = None


class RecallMemoryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memories: list[RecalledMemory]


@tool(
    name="recall_memory",
    description=(
        "Hybrid recall over agent_memory. Returns up to `k` rows that "
        "match the `query` either semantically (cosine similarity over "
        "the embedding column) or structurally (substring match on key)."
    ),
    input_schema=RecallMemoryInput,
    output_schema=RecallMemoryOutput,
    requires=("read:agent_memory",),
    cost_estimate=0.0001,  # one Voyage call worst-case
    is_stub=True,
)
async def recall_memory(args: RecallMemoryInput) -> RecallMemoryOutput:
    raise NotImplementedError(
        "stub: real implementation wires MemoryStore through the agent "
        "session in deliverable 7 (AgenticBaseAgent)."
    )


# ── store_memory ────────────────────────────────────────────────────


class StoreMemoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID | None = None
    agent_name: str = Field(min_length=1, max_length=200)
    scope: Literal["user", "agent", "global"] = "user"
    key: str = Field(min_length=1, max_length=512)
    value: dict[str, Any]
    valence: float = Field(default=0.0, ge=-1.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class StoreMemoryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    written: bool


@tool(
    name="store_memory",
    description=(
        "Upsert a memory row keyed on (user_id, agent_name, scope, "
        "key). Same key + same target → in-place update. Returns the "
        "row's id and whether the call wrote a new row vs updated."
    ),
    input_schema=StoreMemoryInput,
    output_schema=StoreMemoryOutput,
    requires=("write:agent_memory",),
    cost_estimate=0.0001,
    is_stub=True,
)
async def store_memory(args: StoreMemoryInput) -> StoreMemoryOutput:
    raise NotImplementedError(
        "stub: real implementation wires MemoryStore through the agent "
        "session in deliverable 7 (AgenticBaseAgent)."
    )
