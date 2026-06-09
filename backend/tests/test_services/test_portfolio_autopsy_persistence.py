"""Tests for portfolio_autopsy_persistence_service.

Covers the pure axes_to_dict helper plus DB I/O against the in-memory SQLite
session from `tests/conftest.py`. The autopsy LLM is never invoked here —
we hand-build `PortfolioAutopsy` dataclasses to exercise persistence.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.portfolio_autopsy_persistence_service import (
    axes_to_dict,
    get_autopsy_for_user,
    list_autopsies_for_user,
    persist_autopsy_result,
)
from app.services.portfolio_autopsy_service import (
    AutopsyAxis,
    AutopsyFinding,
    PortfolioAutopsy,
)


def _make_result(headline: str = "Solid demo with prod gaps.") -> PortfolioAutopsy:
    return PortfolioAutopsy(
        headline=headline,
        overall_score=68,
        architecture=AutopsyAxis(score=3, assessment="Single-file Flask app."),
        failure_handling=AutopsyAxis(score=2, assessment="No retries on OpenAI."),
        observability=AutopsyAxis(score=2, assessment="print() for logging."),
        scope_discipline=AutopsyAxis(score=4, assessment="Stayed focused."),
        what_worked=["Tight scope", "Smoke-test notebook"],
        what_to_do_differently=[
            AutopsyFinding(
                issue="Embeddings recomputed per request.",
                why_it_matters="Each query is a paid round-trip.",
                what_to_do_differently="Precompute at ingest, store in pgvector.",
            ),
            AutopsyFinding(
                issue="No rate-limit handling.",
                why_it_matters="429s crash the request.",
                what_to_do_differently="Wrap calls with tenacity exponential backoff.",
            ),
        ],
        production_gaps=["No auth on the API", "No request logging"],
        next_project_seed="Build a multi-tenant RAG with row-level access control.",
    )


def _make_request_payload(
    title: str = "Tiny RAG demo",
) -> SimpleNamespace:
    """Stand-in for the route's `AutopsyRequest` — duck-typed for the service."""
    return SimpleNamespace(
        project_title=title,
        project_description="A small RAG over my notes; Flask + OpenAI + FAISS.",
        code="def search(q): ...",
        what_went_well_self=None,
        what_was_hard_self=None,
        model_dump=lambda: {
            "project_title": title,
            "project_description": "A small RAG over my notes; Flask + OpenAI + FAISS.",
            "code": "def search(q): ...",
        },
    )


async def _make_user(db: AsyncSession, email: str = "autopsy@test.dev") -> User:
    user = User(email=email, full_name="Autopsy Tester", role="student")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------


def test_axes_to_dict_returns_four_axes_with_score_and_assessment() -> None:
    result = _make_result()
    out = axes_to_dict(result)
    assert set(out.keys()) == {
        "architecture",
        "failure_handling",
        "observability",
        "scope_discipline",
    }
    for key, expected in (
        ("architecture", 3),
        ("failure_handling", 2),
        ("observability", 2),
        ("scope_discipline", 4),
    ):
        assert out[key]["score"] == expected
        assert isinstance(out[key]["assessment"], str)
        assert out[key]["assessment"]


# ---------------------------------------------------------------------------
# persist_autopsy_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_autopsy_result_writes_row_with_expected_fields(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    payload = _make_request_payload(title="Tiny RAG demo")
    result = _make_result(headline="Ships, but missing prod rails.")

    row = await persist_autopsy_result(
        db_session, user=user, request_payload=payload, result=result
    )

    assert row.id is not None
    assert row.user_id == user.id
    assert row.project_title == "Tiny RAG demo"
    assert row.headline == "Ships, but missing prod rails."
    assert row.overall_score == 68
    assert row.axes["architecture"]["score"] == 3
    assert row.axes["scope_discipline"]["assessment"] == "Stayed focused."
    assert row.what_worked == ["Tight scope", "Smoke-test notebook"]
    assert len(row.what_to_do_differently) == 2
    assert row.what_to_do_differently[0]["issue"] == "Embeddings recomputed per request."
    assert row.production_gaps == ["No auth on the API", "No request logging"]
    assert row.next_project_seed and "multi-tenant" in row.next_project_seed
    assert row.raw_request is not None
    assert row.raw_request["project_title"] == "Tiny RAG demo"
    assert row.created_at is not None


@pytest.mark.asyncio
async def test_persist_does_not_raise_when_axis_field_missing(
    db_session: AsyncSession,
) -> None:
    """Defensive: a malformed result with a partial axis still persists."""
    user = await _make_user(db_session, email="defensive@test.dev")
    payload = _make_request_payload()

    # Intentionally hand a "result" whose `architecture` lacks `assessment`.
    bad_result = SimpleNamespace(
        headline="Partial result",
        overall_score=10,
        architecture=SimpleNamespace(score=1),  # no .assessment
        failure_handling=AutopsyAxis(score=2, assessment="ok"),
        observability=AutopsyAxis(score=2, assessment="ok"),
        scope_discipline=AutopsyAxis(score=2, assessment="ok"),
        what_worked=[],
        what_to_do_differently=[],
        production_gaps=[],
        next_project_seed=None,
    )

    row = await persist_autopsy_result(
        db_session, user=user, request_payload=payload, result=bad_result
    )
    assert row.axes["architecture"]["score"] == 1
    assert row.axes["architecture"]["assessment"] == ""


# ---------------------------------------------------------------------------
# list_autopsies_for_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_autopsies_for_user_newest_first(
    db_session: AsyncSession,
) -> None:
    from datetime import UTC, datetime, timedelta

    user = await _make_user(db_session, email="newest@test.dev")
    first = await persist_autopsy_result(
        db_session,
        user=user,
        request_payload=_make_request_payload("First"),
        result=_make_result(headline="first"),
    )
    second = await persist_autopsy_result(
        db_session,
        user=user,
        request_payload=_make_request_payload("Second"),
        result=_make_result(headline="second"),
    )
    third = await persist_autopsy_result(
        db_session,
        user=user,
        request_payload=_make_request_payload("Third"),
        result=_make_result(headline="third"),
    )

    # SQLite's func.now() granularity can tie three rapid inserts. Force
    # deterministic order so the assertion isn't flaky.
    base = datetime.now(UTC)
    first.created_at = base
    second.created_at = base + timedelta(seconds=1)
    third.created_at = base + timedelta(seconds=2)
    await db_session.commit()

    rows = await list_autopsies_for_user(db_session, user_id=user.id)
    ids = [r.id for r in rows]
    assert ids == [third.id, second.id, first.id]


@pytest.mark.asyncio
async def test_list_autopsies_for_user_is_scoped_to_user(
    db_session: AsyncSession,
) -> None:
    me = await _make_user(db_session, email="me@test.dev")
    other = await _make_user(db_session, email="other@test.dev")
    mine = await persist_autopsy_result(
        db_session,
        user=me,
        request_payload=_make_request_payload("Mine"),
        result=_make_result(),
    )
    await persist_autopsy_result(
        db_session,
        user=other,
        request_payload=_make_request_payload("Theirs"),
        result=_make_result(),
    )

    rows = await list_autopsies_for_user(db_session, user_id=me.id)
    assert [r.id for r in rows] == [mine.id]


# ---------------------------------------------------------------------------
# get_autopsy_for_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_autopsy_for_user_returns_none_for_foreign_owner(
    db_session: AsyncSession,
) -> None:
    me = await _make_user(db_session, email="own@test.dev")
    stranger = await _make_user(db_session, email="stranger@test.dev")
    row = await persist_autopsy_result(
        db_session,
        user=stranger,
        request_payload=_make_request_payload(),
        result=_make_result(),
    )

    found = await get_autopsy_for_user(
        db_session, user_id=me.id, autopsy_id=row.id
    )
    assert found is None

    # And confirm the owner CAN see it (positive control).
    by_owner = await get_autopsy_for_user(
        db_session, user_id=stranger.id, autopsy_id=row.id
    )
    assert by_owner is not None
    assert by_owner.id == row.id


@pytest.mark.asyncio
async def test_get_autopsy_for_user_returns_none_for_unknown_id(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, email="unknown@test.dev")
    found = await get_autopsy_for_user(
        db_session, user_id=user.id, autopsy_id=uuid.uuid4()
    )
    assert found is None
