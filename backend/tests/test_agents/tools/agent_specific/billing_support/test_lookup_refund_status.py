"""D10 Checkpoint 4 / Step 2c — lookup_refund_status pin tests.

Coverage:
  • happy path: refunds joined to orders + payment_attempts
  • empty path: no refunds
  • order_id filter narrows to one order's refunds
  • cross-user security (refunds for other students' orders are
    NOT returned even if the order_id matches)
  • LEFT JOIN to payment_attempts surfaces NULL when refund has
    no attempt link
  • input schema validation
  • missing-session guard
  • asyncpg-rollback contract
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.agent_specific.billing_support.lookup_refund_status import (
    LookupRefundStatusInput,
    LookupRefundStatusOutput,
    lookup_refund_status,
)


async def _insert_user(session: AsyncSession, uid: uuid.UUID) -> None:
    await session.execute(
        sql_text(
            "INSERT INTO users (id, email, full_name) VALUES (:id, :email, :n)"
        ),
        {"id": uid, "email": f"u-{uid}@t.invalid", "n": "x"},
    )


async def _insert_order(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    receipt_number: str | None = None,
) -> uuid.UUID:
    oid = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO orders
              (id, user_id, target_type, target_id, amount_cents,
               currency, provider, status, receipt_number)
            VALUES
              (:id, :uid, 'course', :tid, 4999_00, 'INR', 'razorpay',
               'paid', :receipt)
            """
        ),
        {
            "id": oid,
            "uid": user_id,
            "tid": uuid.uuid4(),
            "receipt": receipt_number,
        },
    )
    await session.flush()
    return oid


async def _insert_payment_attempt(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    status: str = "captured",
) -> uuid.UUID:
    aid = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO payment_attempts
              (id, order_id, provider, amount_cents, status)
            VALUES (:id, :oid, 'razorpay', 4999_00, :status)
            """
        ),
        {"id": aid, "oid": order_id, "status": status},
    )
    await session.flush()
    return aid


async def _insert_refund(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    payment_attempt_id: uuid.UUID | None = None,
    status: str = "pending",
    amount_cents: int = 4999_00,
) -> uuid.UUID:
    rid = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO refunds
              (id, order_id, payment_attempt_id, provider,
               amount_cents, currency, status)
            VALUES (:id, :oid, :aid, 'razorpay', :amt, 'INR', :status)
            """
        ),
        {
            "id": rid,
            "oid": order_id,
            "aid": payment_attempt_id,
            "amt": amount_cents,
            "status": status,
        },
    )
    await session.flush()
    return rid


# ── Happy path ─────────────────────────────────────────────────────


async def test_returns_all_refunds_for_student(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)
    order = await _insert_order(
        session_on_contextvar, user_id=user, receipt_number="CF-001"
    )
    attempt = await _insert_payment_attempt(
        session_on_contextvar, order_id=order, status="captured"
    )
    await _insert_refund(
        session_on_contextvar,
        order_id=order,
        payment_attempt_id=attempt,
        status="pending",
    )
    out = await lookup_refund_status(
        LookupRefundStatusInput(student_id=user)
    )
    assert isinstance(out, LookupRefundStatusOutput)
    assert out.total_returned == 1
    refund = out.refunds[0]
    assert refund.receipt_number == "CF-001"
    assert refund.status == "pending"
    assert refund.payment_attempt_status == "captured"


async def test_returns_empty_when_no_refunds(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)
    out = await lookup_refund_status(
        LookupRefundStatusInput(student_id=user)
    )
    assert out.total_returned == 0


async def test_order_id_filter_narrows_results(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)
    order1 = await _insert_order(
        session_on_contextvar, user_id=user, receipt_number="CF-001"
    )
    order2 = await _insert_order(
        session_on_contextvar, user_id=user, receipt_number="CF-002"
    )
    await _insert_refund(session_on_contextvar, order_id=order1)
    await _insert_refund(session_on_contextvar, order_id=order2)

    out = await lookup_refund_status(
        LookupRefundStatusInput(student_id=user, order_id=order1)
    )
    assert out.total_returned == 1
    assert out.refunds[0].receipt_number == "CF-001"


async def test_payment_attempt_status_null_when_no_attempt_link(
    session_on_contextvar: AsyncSession,
) -> None:
    """LEFT JOIN to payment_attempts must surface NULL gracefully."""
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)
    order = await _insert_order(
        session_on_contextvar, user_id=user, receipt_number="CF-NA"
    )
    # Refund WITHOUT payment_attempt_id link
    await _insert_refund(
        session_on_contextvar, order_id=order, payment_attempt_id=None
    )

    out = await lookup_refund_status(
        LookupRefundStatusInput(student_id=user)
    )
    assert out.total_returned == 1
    assert out.refunds[0].payment_attempt_status is None


async def test_other_users_refunds_not_returned_even_with_order_id(
    session_on_contextvar: AsyncSession,
) -> None:
    """SECURITY: the JOIN through orders.user_id = :uid is the
    structural gate. Even if a malicious caller passes another
    student's order_id, the user_id filter must block the leak.
    """
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    await _insert_user(session_on_contextvar, user_a)
    await _insert_user(session_on_contextvar, user_b)
    # Order belongs to user_b
    bs_order = await _insert_order(
        session_on_contextvar, user_id=user_b, receipt_number="OTHER-001"
    )
    await _insert_refund(session_on_contextvar, order_id=bs_order)

    # user_a queries with user_b's order_id → MUST return empty
    out = await lookup_refund_status(
        LookupRefundStatusInput(student_id=user_a, order_id=bs_order)
    )
    assert out.total_returned == 0, (
        "SECURITY GAP: returned another student's refund. The "
        "orders.user_id filter is broken."
    )


# ── Schema validation ─────────────────────────────────────────────


def test_input_schema_requires_student_id() -> None:
    with pytest.raises(ValidationError):
        LookupRefundStatusInput()  # type: ignore[call-arg]


def test_input_schema_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LookupRefundStatusInput(  # type: ignore[call-arg]
            student_id=uuid.uuid4(), bogus="x"
        )


def test_input_schema_accepts_optional_order_id() -> None:
    parsed = LookupRefundStatusInput(student_id=uuid.uuid4(), order_id=None)
    assert parsed.order_id is None
    parsed2 = LookupRefundStatusInput(
        student_id=uuid.uuid4(), order_id=uuid.uuid4()
    )
    assert parsed2.order_id is not None


# ── Missing-session guard ─────────────────────────────────────────


async def test_raises_without_active_session() -> None:
    with pytest.raises(RuntimeError, match="active session"):
        await lookup_refund_status(
            LookupRefundStatusInput(student_id=uuid.uuid4())
        )


# ── asyncpg-rollback contract ─────────────────────────────────────


async def test_session_recovers_after_query_failure(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)

    from app.agents.tools.agent_specific.billing_support import (
        lookup_refund_status as mod,
    )

    original_text = mod.sql_text

    def _failing_text(query: str):  # type: ignore[no-untyped-def]
        if "FROM refunds r" in query:
            return original_text(
                "SELECT nonexistent_for_test FROM refunds WHERE id = :uid"
            )
        return original_text(query)

    with patch.object(mod, "sql_text", side_effect=_failing_text):
        out = await lookup_refund_status(
            LookupRefundStatusInput(student_id=user)
        )

    assert out.total_returned == 0

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
