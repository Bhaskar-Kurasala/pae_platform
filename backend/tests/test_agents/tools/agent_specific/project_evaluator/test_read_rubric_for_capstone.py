"""D17b/ITEM 2.B — pin tests for read_rubric_for_capstone.

Closes the cross-entitlement leak vector flagged at MEDIUM in
docs/followups/d12-d14c-read-tool-entitlement-leakage-audit.md.
The tool now requires student_id and gates the SQL with a JOIN
through exercises → lessons → courses → course_entitlements,
filtering on `revoked_at IS NULL AND (expires_at IS NULL OR
expires_at > now())`. Mismatched entitlement returns found=False.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.agent_specific.project_evaluator.read_rubric_for_capstone import (
    ReadRubricForCapstoneInput,
    ReadRubricForCapstoneOutput,
    read_rubric_for_capstone,
)


async def _insert_user(session: AsyncSession, uid: uuid.UUID) -> None:
    await session.execute(
        sql_text(
            "INSERT INTO users (id, email, full_name) VALUES (:id, :email, :n)"
        ),
        {"id": uid, "email": f"u-{uid}@test.invalid", "n": "x"},
    )


async def _insert_course(session: AsyncSession) -> uuid.UUID:
    cid = uuid.uuid4()
    await session.execute(
        sql_text(
            "INSERT INTO courses (id, slug, title) VALUES (:id, :slug, :t)"
        ),
        {"id": cid, "slug": f"c-{cid}", "t": "Test Course"},
    )
    return cid


async def _insert_lesson(session: AsyncSession, course_id: uuid.UUID) -> uuid.UUID:
    lid = uuid.uuid4()
    await session.execute(
        sql_text(
            "INSERT INTO lessons (id, course_id, title) VALUES (:id, :c, :t)"
        ),
        {"id": lid, "c": course_id, "t": "Lesson"},
    )
    return lid


async def _insert_capstone(
    session: AsyncSession, lesson_id: uuid.UUID
) -> uuid.UUID:
    eid = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO exercises (id, lesson_id, title, rubric, is_capstone)
            VALUES (:id, :l, :t, CAST(:rubric AS JSONB), TRUE)
            """
        ),
        {
            "id": eid,
            "l": lesson_id,
            "t": "Capstone",
            "rubric": '{"dimensions": [{"name": "correctness", "weight": 0.5}]}',
        },
    )
    return eid


async def _insert_entitlement(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> None:
    await session.execute(
        sql_text(
            """
            INSERT INTO course_entitlements
              (id, user_id, course_id, source, revoked_at, expires_at)
            VALUES (:id, :uid, :cid, 'purchase', :rev, :exp)
            """
        ),
        {
            "id": uuid.uuid4(),
            "uid": user_id,
            "cid": course_id,
            "rev": revoked_at,
            "exp": expires_at,
        },
    )
    await session.flush()


# ── Authorized read with active entitlement ───────────────────────────


async def test_authorized_read_returns_rubric_with_active_entitlement(
    session_on_contextvar: AsyncSession,
) -> None:
    student = uuid.uuid4()
    await _insert_user(session_on_contextvar, student)
    course = await _insert_course(session_on_contextvar)
    lesson = await _insert_lesson(session_on_contextvar, course)
    capstone = await _insert_capstone(session_on_contextvar, lesson)
    await _insert_entitlement(
        session_on_contextvar, user_id=student, course_id=course
    )

    out = await read_rubric_for_capstone(
        ReadRubricForCapstoneInput(
            exercise_id=capstone, student_id=student
        )
    )
    assert isinstance(out, ReadRubricForCapstoneOutput)
    assert out.found is True
    assert out.is_capstone is True
    assert out.rubric_json is not None
    assert out.rubric_json["dimensions"][0]["name"] == "correctness"
    assert out.rubric_text is not None and "correctness" in out.rubric_text


# ── Unentitled student → found=False ──────────────────────────────────


async def test_unentitled_student_gets_not_found(
    session_on_contextvar: AsyncSession,
) -> None:
    """SECURITY: a student without any entitlement to the parent course
    must not see the rubric. found=False is the single error mode (same
    shape as "exercise not found")."""
    student = uuid.uuid4()
    await _insert_user(session_on_contextvar, student)
    course = await _insert_course(session_on_contextvar)
    lesson = await _insert_lesson(session_on_contextvar, course)
    capstone = await _insert_capstone(session_on_contextvar, lesson)
    # Note: no entitlement inserted

    out = await read_rubric_for_capstone(
        ReadRubricForCapstoneInput(
            exercise_id=capstone, student_id=student
        )
    )
    assert out.found is False
    assert out.rubric_json is None
    assert out.rubric_text is None


# ── Expired entitlement → found=False ─────────────────────────────────


async def test_expired_entitlement_gets_not_found(
    session_on_contextvar: AsyncSession,
) -> None:
    """An entitlement with expires_at in the past must NOT grant access."""
    student = uuid.uuid4()
    await _insert_user(session_on_contextvar, student)
    course = await _insert_course(session_on_contextvar)
    lesson = await _insert_lesson(session_on_contextvar, course)
    capstone = await _insert_capstone(session_on_contextvar, lesson)
    await _insert_entitlement(
        session_on_contextvar,
        user_id=student,
        course_id=course,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    out = await read_rubric_for_capstone(
        ReadRubricForCapstoneInput(
            exercise_id=capstone, student_id=student
        )
    )
    assert out.found is False


# ── Revoked entitlement → found=False ─────────────────────────────────


async def test_revoked_entitlement_gets_not_found(
    session_on_contextvar: AsyncSession,
) -> None:
    """An entitlement with revoked_at not null must NOT grant access."""
    student = uuid.uuid4()
    await _insert_user(session_on_contextvar, student)
    course = await _insert_course(session_on_contextvar)
    lesson = await _insert_lesson(session_on_contextvar, course)
    capstone = await _insert_capstone(session_on_contextvar, lesson)
    await _insert_entitlement(
        session_on_contextvar,
        user_id=student,
        course_id=course,
        revoked_at=datetime.now(UTC) - timedelta(hours=1),
    )

    out = await read_rubric_for_capstone(
        ReadRubricForCapstoneInput(
            exercise_id=capstone, student_id=student
        )
    )
    assert out.found is False


# ── Schema validation ────────────────────────────────────────────────


def test_input_schema_requires_student_id() -> None:
    with pytest.raises(ValidationError):
        ReadRubricForCapstoneInput(  # type: ignore[call-arg]
            exercise_id=uuid.uuid4()
        )
