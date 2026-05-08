"""BUG-CP1D regression-guard smoke test.

Model-level regression for the schema-vs-ORM drift on
`interview_sessions.updated_at`. Catches the next instance of the
same bug class at lowest cost: create an InterviewSession without
setting updated_at; assert the row lands with a non-null timestamp
(server_default fires).

Pattern 22 evidence preserved at the test level: this asserts the
fix shape, not just the surface symptom. If a future change reverts
the model column to `nullable=True` without server_default, this
test fails immediately on flush.

Cost class: low (no LLM, pure DB).
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.role_state_fixtures import seed_python_developer_fresh

pytestmark = [pytest.mark.asyncio]


async def test_interview_session_insert_without_updated_at_uses_db_default(
    db_session: AsyncSession,
) -> None:
    """Create an InterviewSession without setting updated_at; verify
    the row lands with a non-null timestamp via server_default.

    Regression guard for BUG-CP1D
    (docs/followups/bug-cp1d-interview-sessions-updated-at-not-null.md).

    If the ORM model loses its `server_default=sa.func.now()` on
    `updated_at`, SQLAlchemy will INSERT explicit NULL and Postgres
    will reject on the NOT NULL constraint — this test catches that
    regression at the model layer.
    """
    student = await seed_python_developer_fresh(db_session)
    await db_session.commit()

    # Insert directly via raw SQL with `updated_at` omitted from the
    # column list. The DB default (now()) MUST fire for the row to
    # land. If it doesn't, the assertion below fails.
    session_id = _uuid.uuid4()
    before = datetime.now(UTC) - timedelta(seconds=2)
    await db_session.execute(
        sql_text(
            """
            INSERT INTO interview_sessions
              (id, user_id, mode, status, questions_asked, scores)
            VALUES
              (:id, :uid, 'behavioral', 'active', '[]'::json, '[]'::json)
            """
        ),
        {"id": session_id, "uid": student.user_id},
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            sql_text(
                "SELECT updated_at, created_at "
                "FROM interview_sessions WHERE id = :id"
            ),
            {"id": session_id},
        )
    ).one()
    assert row.updated_at is not None, (
        "BUG-CP1D regression: updated_at landed as NULL despite the "
        "schema's NOT NULL DEFAULT now() — server_default not firing"
    )
    assert row.updated_at >= before
    assert row.created_at is not None

    # Cleanup.
    await db_session.execute(
        sql_text("DELETE FROM interview_sessions WHERE id = :id"),
        {"id": session_id},
    )
    await db_session.execute(
        sql_text("DELETE FROM users WHERE id = :id"),
        {"id": student.user_id},
    )
    await db_session.commit()


async def test_interview_session_insert_via_orm_omits_updated_at_for_default(
    db_session: AsyncSession,
) -> None:
    """ORM-level regression: SQLAlchemy must omit updated_at from
    the INSERT when unset, letting the server_default fire.

    The post-BUG-CP1D model declares
    `server_default=sa.func.now()` which signals to SA: do NOT send
    this column on INSERT if the user didn't set it. If anyone
    reverts to `nullable=True` without server_default, SA goes back
    to sending explicit NULL and this test fails on flush.
    """
    from app.models.interview_session import InterviewSession

    student = await seed_python_developer_fresh(db_session)
    await db_session.commit()

    # Construct via ORM, do NOT set updated_at.
    session = InterviewSession(
        user_id=student.user_id,
        mode="behavioral",
        status="active",
    )
    db_session.add(session)
    await db_session.flush()  # this is where the BUG-CP1D INSERT failed

    assert session.updated_at is not None, (
        "BUG-CP1D regression: ORM-INSERT left updated_at NULL post-flush"
    )

    # Cleanup.
    await db_session.execute(
        sql_text("DELETE FROM interview_sessions WHERE id = :id"),
        {"id": session.id},
    )
    await db_session.execute(
        sql_text("DELETE FROM users WHERE id = :id"),
        {"id": student.user_id},
    )
    await db_session.commit()
