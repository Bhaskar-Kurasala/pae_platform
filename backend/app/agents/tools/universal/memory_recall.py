"""D10 / Pass 3d §D.1 — memory_recall universal tool.

Thin wrapper around `MemoryStore.recall` registered via `@tool` so
agents recall memories through the audited tool path instead of
touching the store directly. The audit row in `agent_tool_calls`
is what makes "what did this agent read for this student" answerable
without a separate trace.

Per Pass 3d §D.1 spec:
  • Permissions: read:student_data when scope=user; read:cohort_data
    for scope=agent / scope=global.
  • Latency: Fast (10-50ms typical).
  • Status: D2's MemoryStore already implements .recall(); this
    pass's contribution is the typed @tool wrapper.

Naming note (Pass 3d §D vs D3 stub):
  D3 shipped `recall_memory` as a stub at app/agents/tools/memory_tools.py.
  Pass 3d §D names the universal tool `memory_recall` (verb-noun
  reversed). D10 implements the Pass 3d §D name here and retires
  the D3 stub. See app/agents/tools/__init__.py for the import wiring
  that makes both NOT register simultaneously.

Permission-derivation logic:
  Pass 3d §D.1 mentions both read:student_data and read:cohort_data
  depending on scope. The simpler v1 declaration is to require
  read:agent_memory (the same permission the D3 stub used) — this
  matches what `AgenticBaseAgent.permissions` already grants in
  practice. A finer-grained scope-aware permission split is left
  to a follow-up if/when scope=global tools land.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.memory import MemoryStore
from app.agents.primitives.tools import tool


class MemoryRecallInput(BaseModel):
    """Input schema mirroring MemoryStore.recall().

    `query` is required because the universal tool always runs
    against an LLM-supplied search string. Callers that want a
    pure key lookup should use `key_pattern` semantics by passing
    the key as the query and `mode='structured'`.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=1,
        max_length=2000,
        description="Free-form text the agent wants to recall against.",
    )
    user_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Scope to one student. Pass when the agent is acting on "
            "behalf of a specific user; omit for cross-user recall."
        ),
    )
    agent_name: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Filter to memories written by this agent. Useful when an "
            "agent wants to read only its own past observations."
        ),
    )
    scope: Literal["user", "agent", "global"] | None = Field(
        default=None,
        description=(
            "Memory scope to query. None = include all scopes the "
            "user_id grants access to (per MemoryStore._scope_clause)."
        ),
    )
    k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of rows to return.",
    )
    mode: Literal["hybrid", "semantic", "structured"] = Field(
        default="hybrid",
        description=(
            "'semantic' for embedding similarity, 'structured' for "
            "key substring match, 'hybrid' for both."
        ),
    )
    min_similarity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Override the default similarity threshold for semantic "
            "matches (default 0.35 — see DEFAULT_SIMILARITY_THRESHOLD)."
        ),
    )


class RecalledMemory(BaseModel):
    """One row returned to the agent.

    Trimmed projection of MemoryRow — surfaces id, key, value,
    similarity. valence/confidence/access_count stay below the
    boundary because most agents don't reason over them; agents
    that need them call MemoryStore directly.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    key: str
    value: dict[str, Any]
    similarity: float | None = None


class MemoryRecallOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memories: list[RecalledMemory] = Field(default_factory=list)


@tool(
    name="memory_recall",
    description=(
        "Hybrid recall over the agent_memory table. Returns up to `k` "
        "rows that match the `query` either semantically (cosine "
        "similarity) or structurally (key substring). Use when the "
        "agent needs to ground its response in prior interactions "
        "with this student or in cohort-wide observations."
    ),
    input_schema=MemoryRecallInput,
    output_schema=MemoryRecallOutput,
    requires=("read:agent_memory",),
    cost_estimate=0.0001,  # one Voyage embed worst-case
    timeout_seconds=10.0,
)
async def memory_recall(args: MemoryRecallInput) -> MemoryRecallOutput:
    """Run a recall against the active session's MemoryStore.

    The session comes from the `_active_session` contextvar that
    `call_agent` populates before invoking the callee. Tools are only
    invoked from inside an agent's `run()`, which is itself reached
    through `call_agent`, so the contextvar is always set in
    production. Tests that drive a tool body directly must set the
    session via `_active_session.set(session)` before invoking.
    """
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "memory_recall called without an active session. The tool "
            "body relies on the contextvar set by call_agent; if you "
            "are testing the body directly, set _active_session before "
            "invoking."
        )
    store = MemoryStore(session)
    rows = await store.recall(
        args.query,
        user_id=args.user_id,
        agent_name=args.agent_name,
        scope=args.scope,
        k=args.k,
        mode=args.mode,
        min_similarity=args.min_similarity,
    )
    return MemoryRecallOutput(
        memories=[
            RecalledMemory(
                id=row.id,
                key=row.key,
                value=row.value,
                similarity=row.similarity,
            )
            for row in rows
        ]
    )


__all__ = ["MemoryRecallInput", "MemoryRecallOutput", "RecalledMemory", "memory_recall"]
