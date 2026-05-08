"""D17b/ITEM 2.A — pin tests for read_capstone_submission_content.

Closes the cross-student leak vector flagged at MEDIUM in
docs/followups/d12-d14c-read-tool-entitlement-leakage-audit.md.
The tool now requires student_id in the input schema and gates the
SQL with `AND es.student_id = :student_id`. Mismatched ownership
returns found=False (single error mode — does NOT distinguish
"not found" from "not yours" so an attacker can't probe existence).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.agent_specific.project_evaluator.read_capstone_submission_content import (
    ReadCapstoneSubmissionContentInput,
    ReadCapstoneSubmissionContentOutput,
    read_capstone_submission_content,
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


async def _insert_exercise(
    session: AsyncSession,
    lesson_id: uuid.UUID,
    *,
    is_capstone: bool = True,
    rubric: dict[str, Any] | None = None,
) -> uuid.UUID:
    eid = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO exercises (id, lesson_id, title, description, rubric, is_capstone)
            VALUES (:id, :l, :t, :desc, CAST(:rubric AS JSONB), :cap)
            """
        ),
        {
            "id": eid,
            "l": lesson_id,
            "t": "Capstone Exercise",
            "desc": "Build the thing",
            "rubric": '{"dimensions": []}' if rubric is None else None,
            "cap": is_capstone,
        },
    )
    return eid


async def _insert_submission(
    session: AsyncSession, *, student_id: uuid.UUID, exercise_id: uuid.UUID
) -> uuid.UUID:
    sid = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO exercise_submissions
              (id, student_id, exercise_id, code, status)
            VALUES (:id, :s, :e, :code, 'submitted')
            """
        ),
        {
            "id": sid,
            "s": student_id,
            "e": exercise_id,
            "code": "print('hello capstone')",
        },
    )
    await session.flush()
    return sid


# ── Authorized read (happy path) ──────────────────────────────────────


async def test_authorized_read_returns_submission_content(
    session_on_contextvar: AsyncSession,
) -> None:
    student = uuid.uuid4()
    await _insert_user(session_on_contextvar, student)
    course = await _insert_course(session_on_contextvar)
    lesson = await _insert_lesson(session_on_contextvar, course)
    exercise = await _insert_exercise(session_on_contextvar, lesson)
    submission = await _insert_submission(
        session_on_contextvar, student_id=student, exercise_id=exercise
    )

    out = await read_capstone_submission_content(
        ReadCapstoneSubmissionContentInput(
            submission_id=submission, student_id=student
        )
    )
    assert isinstance(out, ReadCapstoneSubmissionContentOutput)
    assert out.found is True
    assert out.submission_id == submission
    assert out.student_id == student
    assert out.exercise_id == exercise
    assert out.code == "print('hello capstone')"
    assert out.is_capstone is True


# ── Cross-student leak attempt → found=False ──────────────────────────


async def test_cross_student_leak_attempt_returns_not_found(
    session_on_contextvar: AsyncSession,
) -> None:
    """SECURITY: a submission_id from another student must not return content
    when the caller's student_id doesn't match.

    Single error mode: returns found=False (same shape as "not found" in
    DB). Doesn't distinguish "not yours" from "not found" so an attacker
    can't probe existence.
    """
    student_a = uuid.uuid4()
    student_b = uuid.uuid4()
    await _insert_user(session_on_contextvar, student_a)
    await _insert_user(session_on_contextvar, student_b)
    course = await _insert_course(session_on_contextvar)
    lesson = await _insert_lesson(session_on_contextvar, course)
    exercise = await _insert_exercise(session_on_contextvar, lesson)
    # Submission belongs to student_b
    submission_b = await _insert_submission(
        session_on_contextvar, student_id=student_b, exercise_id=exercise
    )

    # Caller is student_a; supplies student_b's submission_id
    out = await read_capstone_submission_content(
        ReadCapstoneSubmissionContentInput(
            submission_id=submission_b, student_id=student_a
        )
    )
    assert out.found is False
    assert out.code is None
    assert out.student_id is None  # not leaked


# ── Submission not found → found=False ────────────────────────────────


async def test_unknown_submission_returns_not_found(
    session_on_contextvar: AsyncSession,
) -> None:
    """A submission_id that doesn't exist returns found=False, same shape
    as the "not yours" path. Single error mode preserved.
    """
    student = uuid.uuid4()
    await _insert_user(session_on_contextvar, student)
    bogus_submission = uuid.uuid4()

    out = await read_capstone_submission_content(
        ReadCapstoneSubmissionContentInput(
            submission_id=bogus_submission, student_id=student
        )
    )
    assert out.found is False
    assert out.submission_id is None


# ── Schema validation ────────────────────────────────────────────────


def test_input_schema_requires_student_id() -> None:
    with pytest.raises(ValidationError):
        ReadCapstoneSubmissionContentInput(  # type: ignore[call-arg]
            submission_id=uuid.uuid4()
        )
