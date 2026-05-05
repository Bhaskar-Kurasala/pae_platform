"""D11 Checkpoint 1 — lookup_prior_reviews tool tests.

Five tests pin the contract:
  • happy: rows under feedback:code_review:* surface, recency-ordered
  • empty: no matching rows → empty list, total_returned=0
  • cross-user: another student's reviews NOT surfaced
  • schema validation: output is a valid LookupPriorReviewsOutput
  • asyncpg-rollback contract: failing recall calls session.rollback
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
from app.agents.tools.agent_specific.senior_engineer.lookup_prior_reviews import (
    LookupPriorReviewsInput,
    LookupPriorReviewsOutput,
    lookup_prior_reviews,
)
from tests.test_agents.tools.agent_specific.senior_engineer.conftest import (
    active_session,
)


def _zero_embedding() -> list[float]:
    return [0.0] * EMBEDDING_DIM


async def _seed_review(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    key_suffix: str,
    verdict: str,
    headline: str,
) -> uuid.UUID:
    row_id = uuid.uuid4()
    value = json.dumps({"verdict": verdict, "headline": headline})
    await session.execute(
        sql_text(
            """
            INSERT INTO agent_memory
                (id, user_id, agent_name, scope, key, value, embedding,
                 valence, confidence)
            VALUES
                (:id, :uid, 'senior_engineer',
                 'user'::agent_memory_scope,
                 :key, :value, :emb, 0.0, 1.0)
            """
        ),
        {
            "id": row_id,
            "uid": user_id,
            "key": f"feedback:code_review:{key_suffix}",
            "value": value,
            "emb": str(_zero_embedding()),
        },
    )
    await session.commit()
    return row_id


@pytest.mark.asyncio
async def test_lookup_prior_reviews_happy_path(
    pg_session: AsyncSession,
) -> None:
    student_id = uuid.uuid4()
    id_a = await _seed_review(
        pg_session,
        user_id=student_id,
        key_suffix="2026-04-15",
        verdict="request_changes",
        headline="bare except in 3 places",
    )
    id_b = await _seed_review(
        pg_session,
        user_id=student_id,
        key_suffix="2026-04-22",
        verdict="approve",
        headline="cleaner exception handling",
    )

    with active_session(pg_session):
        result = await lookup_prior_reviews(
            LookupPriorReviewsInput(student_id=student_id, limit=10)
        )

    assert isinstance(result, LookupPriorReviewsOutput)
    surfaced_ids = {r.memory_id for r in result.reviews}
    assert id_a in surfaced_ids
    assert id_b in surfaced_ids
    assert result.total_returned == len(result.reviews)
    assert all(r.key.startswith("feedback:code_review") for r in result.reviews)


@pytest.mark.asyncio
async def test_lookup_prior_reviews_empty(
    pg_session: AsyncSession,
) -> None:
    student_id = uuid.uuid4()
    with active_session(pg_session):
        result = await lookup_prior_reviews(
            LookupPriorReviewsInput(student_id=student_id)
        )
    assert result.reviews == []
    assert result.total_returned == 0


@pytest.mark.asyncio
async def test_lookup_prior_reviews_cross_user_isolation(
    pg_session: AsyncSession,
) -> None:
    student_a = uuid.uuid4()
    student_b = uuid.uuid4()
    await _seed_review(
        pg_session,
        user_id=student_b,
        key_suffix="other-students-review",
        verdict="approve",
        headline="not yours",
    )

    with active_session(pg_session):
        result = await lookup_prior_reviews(
            LookupPriorReviewsInput(student_id=student_a)
        )
    assert result.reviews == [], (
        "Cross-user review leaked through — recall is not "
        "filtering by user_id correctly"
    )


@pytest.mark.asyncio
async def test_lookup_prior_reviews_schema_validation_round_trip() -> None:
    out = LookupPriorReviewsOutput(reviews=[], total_returned=0)
    j = out.model_dump_json()
    rebuilt = LookupPriorReviewsOutput.model_validate_json(j)
    assert rebuilt == out


@pytest.mark.asyncio
async def test_lookup_prior_reviews_asyncpg_rollback_contract() -> None:
    fake_session = AsyncMock(spec=AsyncSession)
    fake_session.rollback = AsyncMock()

    import importlib

    mod = importlib.import_module(
        "app.agents.tools.agent_specific.senior_engineer."
        "lookup_prior_reviews"
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
            result = await lookup_prior_reviews(
                LookupPriorReviewsInput(student_id=uuid.uuid4())
            )
    finally:
        mod.MemoryStore = original  # type: ignore[misc]

    fake_session.rollback.assert_awaited_once()
    assert result.reviews == []
    assert result.total_returned == 0
