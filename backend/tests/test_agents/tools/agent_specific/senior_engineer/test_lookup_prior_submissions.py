"""D11 Checkpoint 1 — lookup_prior_submissions tool tests.

Five tests pin the contract:
  • happy: rows under submission:code:* surface, with similarity scores
  • empty: no matching rows → empty list, total_returned=0
  • cross-user: another student's submissions are NOT surfaced
  • schema validation: output is a valid LookupPriorSubmissionsOutput
  • asyncpg-rollback contract: an always-failing recall triggers
    session.rollback() per the discipline doc
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives.embeddings import EMBEDDING_DIM
from app.agents.tools.agent_specific.senior_engineer.lookup_prior_submissions import (
    LookupPriorSubmissionsInput,
    LookupPriorSubmissionsOutput,
    lookup_prior_submissions,
)
from tests.test_agents.tools.agent_specific.senior_engineer.conftest import (
    active_session,
)


def _zero_embedding() -> list[float]:
    """Embedding stub — real semantic similarity isn't what the tests
    pin. We stash a zero-vector so rows are insertable; the structured
    branch of MemoryStore.recall surfaces them via key-substring match.
    """
    return [0.0] * EMBEDDING_DIM


async def _seed_submission(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    key_suffix: str,
    code: str,
    agent_name: str = "senior_engineer",
) -> uuid.UUID:
    row_id = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO agent_memory
                (id, user_id, agent_name, scope, key, value, embedding,
                 valence, confidence)
            VALUES
                (:id, :uid, :agent, 'user'::agent_memory_scope,
                 :key, :value, :emb, 0.0, 1.0)
            """
        ),
        {
            "id": row_id,
            "uid": user_id,
            "agent": agent_name,
            "key": f"submission:code:{key_suffix}",
            "value": json.dumps({"code": code}),
            "emb": str(_zero_embedding()),
        },
    )
    await session.commit()
    return row_id


@pytest.mark.asyncio
async def test_lookup_prior_submissions_happy_path(
    pg_session: AsyncSession,
) -> None:
    """Two seeded submissions → both surface, output schema validates."""
    student_id = uuid.uuid4()
    id_a = await _seed_submission(
        pg_session,
        user_id=student_id,
        key_suffix="capstone-v1",
        code="def add(a, b): return a + b",
    )
    id_b = await _seed_submission(
        pg_session,
        user_id=student_id,
        key_suffix="capstone-v2",
        code="def add(a, b):\n    return a + b\n",
    )

    with active_session(pg_session):
        result = await lookup_prior_submissions(
            LookupPriorSubmissionsInput(
                student_id=student_id,
                similar_to_code="def add(a, b): return a + b",
                limit=5,
            )
        )

    assert isinstance(result, LookupPriorSubmissionsOutput)
    surfaced_ids = {s.memory_id for s in result.submissions}
    assert id_a in surfaced_ids
    assert id_b in surfaced_ids
    assert result.total_returned == len(result.submissions)
    assert all(s.key.startswith("submission:code") for s in result.submissions)


@pytest.mark.asyncio
async def test_lookup_prior_submissions_empty(
    pg_session: AsyncSession,
) -> None:
    """No prior submissions → empty list, total_returned=0."""
    student_id = uuid.uuid4()
    with active_session(pg_session):
        result = await lookup_prior_submissions(
            LookupPriorSubmissionsInput(
                student_id=student_id,
                similar_to_code="anything",
            )
        )
    assert result.submissions == []
    assert result.total_returned == 0


@pytest.mark.asyncio
async def test_lookup_prior_submissions_cross_user_isolation(
    pg_session: AsyncSession,
) -> None:
    """Another student's submissions MUST NOT surface — security pin."""
    student_a = uuid.uuid4()
    student_b = uuid.uuid4()
    await _seed_submission(
        pg_session,
        user_id=student_b,
        key_suffix="other-students-code",
        code="leak me",
    )

    with active_session(pg_session):
        result = await lookup_prior_submissions(
            LookupPriorSubmissionsInput(
                student_id=student_a,
                similar_to_code="leak me",
            )
        )
    assert result.submissions == [], (
        "Cross-user submission leaked through — recall is not "
        "filtering by user_id correctly"
    )


@pytest.mark.asyncio
async def test_lookup_prior_submissions_schema_validation_round_trip() -> None:
    """The output schema validates round-trip without DB hits."""
    out = LookupPriorSubmissionsOutput(
        submissions=[],
        total_returned=0,
    )
    j = out.model_dump_json()
    rebuilt = LookupPriorSubmissionsOutput.model_validate_json(j)
    assert rebuilt == out


@pytest.mark.asyncio
async def test_lookup_prior_submissions_asyncpg_rollback_contract() -> None:
    """When MemoryStore.recall raises, the tool MUST call
    session.rollback() before returning the safe-default empty
    result. Pins the asyncpg-rollback discipline."""
    fake_session = AsyncMock(spec=AsyncSession)
    fake_session.rollback = AsyncMock()

    # Patch MemoryStore at the tool's import site so .recall raises.
    # Use importlib so the module-as-namespace doesn't shadow with the
    # same-named function in this file's top-level imports.
    import importlib

    mod = importlib.import_module(
        "app.agents.tools.agent_specific.senior_engineer."
        "lookup_prior_submissions"
    )

    class _BoomMemoryStore:
        def __init__(self, _session: Any) -> None:
            pass

        async def recall(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("simulated DB failure")

    original = mod.MemoryStore
    mod.MemoryStore = _BoomMemoryStore  # type: ignore[misc]
    try:
        with active_session(fake_session):
            result = await lookup_prior_submissions(
                LookupPriorSubmissionsInput(
                    student_id=uuid.uuid4(),
                    similar_to_code="x",
                )
            )
    finally:
        mod.MemoryStore = original  # type: ignore[misc]

    fake_session.rollback.assert_awaited_once()
    assert result.submissions == []
    assert result.total_returned == 0
