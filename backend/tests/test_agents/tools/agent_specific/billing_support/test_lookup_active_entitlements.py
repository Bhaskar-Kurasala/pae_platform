"""D10 Checkpoint 4 / Step 2b — lookup_active_entitlements pin tests.

Coverage:
  • happy path: active entitlements joined to courses
  • empty path: no entitlements
  • revoked rows excluded
  • expired rows excluded
  • cross-user security
  • input schema validation
  • missing-session guard
  • asyncpg-rollback contract
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.agent_specific.billing_support.lookup_active_entitlements import (
    LookupActiveEntitlementsInput,
    LookupActiveEntitlementsOutput,
    lookup_active_entitlements,
)


async def _insert_user(session: AsyncSession, uid: uuid.UUID) -> None:
    await session.execute(
        sql_text(
            "INSERT INTO users (id, email, full_name) VALUES (:id, :email, :name)"
        ),
        {"id": uid, "email": f"u-{uid}@test.invalid", "name": "x"},
    )


async def _insert_course(
    session: AsyncSession, *, slug: str, title: str
) -> uuid.UUID:
    cid = uuid.uuid4()
    await session.execute(
        sql_text(
            "INSERT INTO courses (id, slug, title, price_cents, is_published) "
            "VALUES (:id, :slug, :title, 4999_00, true)"
        ),
        {"id": cid, "slug": slug, "title": title},
    )
    return cid


async def _insert_entitlement(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    source: str = "purchase",
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> uuid.UUID:
    eid = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO course_entitlements
              (id, user_id, course_id, source, revoked_at, expires_at)
            VALUES (:id, :uid, :cid, :src, :rev, :exp)
            """
        ),
        {
            "id": eid,
            "uid": user_id,
            "cid": course_id,
            "src": source,
            "rev": revoked_at,
            "exp": expires_at,
        },
    )
    await session.flush()
    return eid


# ── Happy path ─────────────────────────────────────────────────────


async def test_returns_active_entitlements_with_course_metadata(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)
    course1 = await _insert_course(
        session_on_contextvar, slug="genai-engineer", title="GenAI Engineer"
    )
    course2 = await _insert_course(
        session_on_contextvar, slug="rag-prod", title="Production RAG"
    )
    await _insert_entitlement(
        session_on_contextvar, user_id=user, course_id=course1, source="purchase"
    )
    await _insert_entitlement(
        session_on_contextvar, user_id=user, course_id=course2, source="bundle"
    )

    out = await lookup_active_entitlements(
        LookupActiveEntitlementsInput(student_id=user)
    )
    assert isinstance(out, LookupActiveEntitlementsOutput)
    assert out.total_active == 2
    slugs = {e.course_slug for e in out.entitlements}
    assert slugs == {"genai-engineer", "rag-prod"}


async def test_returns_empty_when_no_entitlements(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)
    out = await lookup_active_entitlements(
        LookupActiveEntitlementsInput(student_id=user)
    )
    assert out.total_active == 0
    assert out.entitlements == []


async def test_revoked_entitlements_excluded(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)
    active_course = await _insert_course(
        session_on_contextvar, slug="active-c", title="Active"
    )
    revoked_course = await _insert_course(
        session_on_contextvar, slug="revoked-c", title="Revoked"
    )
    await _insert_entitlement(
        session_on_contextvar, user_id=user, course_id=active_course
    )
    await _insert_entitlement(
        session_on_contextvar,
        user_id=user,
        course_id=revoked_course,
        revoked_at=datetime.now(UTC) - timedelta(days=1),
    )

    out = await lookup_active_entitlements(
        LookupActiveEntitlementsInput(student_id=user)
    )
    assert out.total_active == 1
    assert out.entitlements[0].course_slug == "active-c"


async def test_expired_entitlements_excluded(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)
    fresh = await _insert_course(session_on_contextvar, slug="fresh", title="F")
    expired = await _insert_course(session_on_contextvar, slug="expired", title="E")
    await _insert_entitlement(
        session_on_contextvar,
        user_id=user,
        course_id=fresh,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    await _insert_entitlement(
        session_on_contextvar,
        user_id=user,
        course_id=expired,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    out = await lookup_active_entitlements(
        LookupActiveEntitlementsInput(student_id=user)
    )
    assert out.total_active == 1
    assert out.entitlements[0].course_slug == "fresh"


async def test_other_users_entitlements_not_returned(
    session_on_contextvar: AsyncSession,
) -> None:
    """SECURITY: cross-student leakage check."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    await _insert_user(session_on_contextvar, user_a)
    await _insert_user(session_on_contextvar, user_b)
    course = await _insert_course(session_on_contextvar, slug="c", title="C")
    await _insert_entitlement(
        session_on_contextvar, user_id=user_b, course_id=course
    )

    out = await lookup_active_entitlements(
        LookupActiveEntitlementsInput(student_id=user_a)
    )
    assert out.total_active == 0


# ── Schema validation ─────────────────────────────────────────────


def test_input_schema_requires_student_id() -> None:
    with pytest.raises(ValidationError):
        LookupActiveEntitlementsInput()  # type: ignore[call-arg]


def test_input_schema_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LookupActiveEntitlementsInput(  # type: ignore[call-arg]
            student_id=uuid.uuid4(), bogus="x"
        )


# ── Missing-session guard ─────────────────────────────────────────


async def test_raises_without_active_session() -> None:
    with pytest.raises(RuntimeError, match="active session"):
        await lookup_active_entitlements(
            LookupActiveEntitlementsInput(student_id=uuid.uuid4())
        )


# ── asyncpg-rollback contract ─────────────────────────────────────


async def test_session_recovers_after_query_failure(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)

    from app.agents.tools.agent_specific.billing_support import (
        lookup_active_entitlements as mod,
    )

    original_text = mod.sql_text

    def _failing_text(query: str):  # type: ignore[no-untyped-def]
        if "FROM course_entitlements" in query:
            return original_text(
                "SELECT nonexistent_for_test FROM course_entitlements WHERE user_id = :uid"
            )
        return original_text(query)

    with patch.object(mod, "sql_text", side_effect=_failing_text):
        out = await lookup_active_entitlements(
            LookupActiveEntitlementsInput(student_id=user)
        )

    assert out.total_active == 0
    assert out.entitlements == []

    # Session must be recoverable
    new_user = uuid.uuid4()
    await session_on_contextvar.execute(
        sql_text(
            "INSERT INTO users (id, email, full_name) VALUES (:id, :email, :n)"
        ),
        {"id": new_user, "email": f"x-{new_user}@t.invalid", "n": "x"},
    )
    await session_on_contextvar.flush()
    raw = await session_on_contextvar.execute(
        sql_text("SELECT count(*) FROM users WHERE id = :id"),
        {"id": new_user},
    )
    assert raw.scalar_one() == 1
