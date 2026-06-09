"""D10 Checkpoint 4 / Step 2d — escalate_to_human pin tests.

Coverage:
  • happy path: row lands in student_inbox with kind=escalation
  • idempotency_key dedup returns existing ticket id
  • write failure raises (different from read tools' fail-soft)
  • input schema validation
  • missing-session guard
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.agent_specific.billing_support.escalate_to_human import (
    EscalateToHumanInput,
    EscalateToHumanOutput,
    escalate_to_human,
)


async def _insert_user(session: AsyncSession, uid: uuid.UUID) -> None:
    await session.execute(
        sql_text(
            "INSERT INTO users (id, email, full_name) VALUES (:id, :email, :n)"
        ),
        {"id": uid, "email": f"u-{uid}@t.invalid", "n": "x"},
    )


# ── Happy path ─────────────────────────────────────────────────────


async def test_writes_inbox_row_with_correct_metadata(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)

    out = await escalate_to_human(
        EscalateToHumanInput(
            student_id=user,
            reason="repeat_charge_after_cancel",
            summary="Student reports being charged 3 times after cancelling subscription.",
        )
    )

    assert isinstance(out, EscalateToHumanOutput)
    assert out.was_new is True
    assert isinstance(out.ticket_id, uuid.UUID)

    # Verify the row landed
    row = await session_on_contextvar.execute(
        sql_text(
            "SELECT id, agent_name, kind, title, body, metadata, "
            "       idempotency_key "
            "FROM student_inbox WHERE id = :id"
        ),
        {"id": out.ticket_id},
    )
    inbox = row.first()
    assert inbox is not None
    assert inbox[1] == "billing_support"  # agent_name
    assert inbox[2] == "escalation"  # kind
    assert "repeat_charge_after_cancel" in inbox[3]  # title contains reason
    assert "charged 3 times after cancelling" in inbox[4]  # body has summary
    # metadata is JSONB; asyncpg returns dict directly
    metadata = inbox[5] if isinstance(inbox[5], dict) else json.loads(inbox[5])
    assert metadata.get("reason") == "repeat_charge_after_cancel"
    assert metadata.get("escalated_by") == "billing_support"


# ── Idempotency ────────────────────────────────────────────────────


async def test_idempotency_key_returns_existing_ticket(
    session_on_contextvar: AsyncSession,
) -> None:
    """Same student + same idempotency_key → second call returns
    the ticket id from the first, no new row inserted."""
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)

    out1 = await escalate_to_human(
        EscalateToHumanInput(
            student_id=user,
            reason="duplicate_test",
            summary="First escalation request.",
            idempotency_key="dedup-key-001",
        )
    )
    assert out1.was_new is True

    out2 = await escalate_to_human(
        EscalateToHumanInput(
            student_id=user,
            reason="duplicate_test",
            summary="Second escalation request, same idempotency key.",
            idempotency_key="dedup-key-001",
        )
    )
    assert out2.was_new is False
    assert out2.ticket_id == out1.ticket_id

    # Verify only one row in DB
    cnt = await session_on_contextvar.execute(
        sql_text(
            "SELECT count(*) FROM student_inbox "
            "WHERE user_id = :uid AND idempotency_key = :key"
        ),
        {"uid": user, "key": "dedup-key-001"},
    )
    assert cnt.scalar_one() == 1


# ── Write-failure path ────────────────────────────────────────────


async def test_write_failure_raises(
    session_on_contextvar: AsyncSession,
) -> None:
    """Different from read tools' fail-soft contract: writes raise
    so the caller knows the side effect didn't land. The agent's
    _dispatch_escalation_if_requested catches this and surfaces
    the support email to the student."""
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)

    from app.agents.tools.agent_specific.billing_support import (
        escalate_to_human as mod,
    )

    original_text = mod.sql_text

    def _failing_text(query: str):  # type: ignore[no-untyped-def]
        if "INSERT INTO student_inbox" in query:
            return original_text(
                "INSERT INTO student_inbox (nonexistent_col) VALUES (:id)"
            )
        return original_text(query)

    with patch.object(mod, "sql_text", side_effect=_failing_text):
        with pytest.raises(RuntimeError, match="failed to write inbox row"):
            await escalate_to_human(
                EscalateToHumanInput(
                    student_id=user,
                    reason="write_failure_test",
                    summary="This insert should fail.",
                )
            )


# ── Schema validation ─────────────────────────────────────────────


def test_input_schema_requires_min_length_summary() -> None:
    with pytest.raises(ValidationError):
        EscalateToHumanInput(
            student_id=uuid.uuid4(),
            reason="x",
            summary="too short",  # min_length=10
        )


def test_input_schema_requires_min_length_reason() -> None:
    with pytest.raises(ValidationError):
        EscalateToHumanInput(
            student_id=uuid.uuid4(),
            reason="ab",  # min_length=3
            summary="this summary is long enough to pass min_length validation",
        )


def test_input_schema_caps_summary_length() -> None:
    with pytest.raises(ValidationError):
        EscalateToHumanInput(
            student_id=uuid.uuid4(),
            reason="capped_test",
            summary="x" * 2001,  # max_length=2000
        )


def test_input_schema_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        EscalateToHumanInput(  # type: ignore[call-arg]
            student_id=uuid.uuid4(),
            reason="ok_reason",
            summary="this is a long enough summary to pass validation",
            bogus="x",
        )


# ── Missing-session guard ─────────────────────────────────────────


async def test_raises_without_active_session() -> None:
    with pytest.raises(RuntimeError, match="active session"):
        await escalate_to_human(
            EscalateToHumanInput(
                student_id=uuid.uuid4(),
                reason="no_session_test",
                summary="this is a long enough summary to pass validation",
            )
        )
