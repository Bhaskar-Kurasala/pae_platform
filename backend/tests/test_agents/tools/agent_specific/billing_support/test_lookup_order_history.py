"""D10 Checkpoint 4 / Step 2a — lookup_order_history pin tests.

Coverage:
  • happy path: seeded orders → returned most-recent-first
  • empty path: no orders → returns empty + total_returned=0
  • truncation: limit+1 detection
  • missing-session guard
  • asyncpg-rollback contract (synthetic SQL failure → session
    recovers for downstream INSERTs)
  • input schema validation
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.agent_specific.billing_support.lookup_order_history import (
    LookupOrderHistoryInput,
    LookupOrderHistoryOutput,
    lookup_order_history,
)

# pyproject.toml has asyncio_mode = "auto"; sync funcs run normally,
# async funcs run via pytest-asyncio. No module-level mark needed.


def _seed_user(uid: uuid.UUID) -> dict:
    return {
        "id": uid,
        "email": f"test-{uid}@test.invalid",
        "name": f"Test {uid.hex[:6]}",
    }


async def _insert_user(session: AsyncSession, uid: uuid.UUID) -> None:
    await session.execute(
        sql_text(
            "INSERT INTO users (id, email, full_name) "
            "VALUES (:id, :email, :name)"
        ),
        _seed_user(uid),
    )


async def _insert_order(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    receipt_number: str | None = None,
    amount_cents: int = 4999_00,
    status: str = "paid",
    created_at: datetime | None = None,
) -> uuid.UUID:
    order_id = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO orders
              (id, user_id, target_type, target_id, amount_cents,
               currency, provider, status, receipt_number, created_at,
               paid_at)
            VALUES
              (:id, :uid, 'course', :target, :amt, 'INR', 'razorpay',
               :status, :receipt, :created, :paid)
            """
        ),
        {
            "id": order_id,
            "uid": user_id,
            "target": uuid.uuid4(),
            "amt": amount_cents,
            "status": status,
            "receipt": receipt_number,
            "created": created_at or datetime.now(UTC),
            "paid": datetime.now(UTC) if status == "paid" else None,
        },
    )
    await session.flush()
    return order_id


# ── Happy path ─────────────────────────────────────────────────────


async def test_returns_orders_most_recent_first(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)
    # Seed three orders with explicit ordering
    o1 = await _insert_order(
        session_on_contextvar,
        user_id=user,
        receipt_number="CF-001",
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    o2 = await _insert_order(
        session_on_contextvar,
        user_id=user,
        receipt_number="CF-002",
        created_at=datetime(2026, 4, 15, tzinfo=UTC),
    )
    o3 = await _insert_order(
        session_on_contextvar,
        user_id=user,
        receipt_number="AC-003",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )

    out = await lookup_order_history(
        LookupOrderHistoryInput(student_id=user, limit=20)
    )

    assert isinstance(out, LookupOrderHistoryOutput)
    assert out.total_returned == 3
    assert out.truncated is False
    # most-recent first
    receipts = [o.receipt_number for o in out.orders]
    assert receipts == ["AC-003", "CF-002", "CF-001"]
    # amount conversion: 4999_00 cents → 4999.00 INR
    assert out.orders[0].amount == 4999_00 // 100  # type: ignore[comparison-overlap]


async def test_returns_empty_when_no_orders(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)
    out = await lookup_order_history(
        LookupOrderHistoryInput(student_id=user, limit=20)
    )
    assert out.total_returned == 0
    assert out.orders == []
    assert out.truncated is False


async def test_truncated_flag_when_more_than_limit(
    session_on_contextvar: AsyncSession,
) -> None:
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)
    # Seed 5 orders, limit=3 → expect 3 returned + truncated=True
    for i in range(5):
        await _insert_order(
            session_on_contextvar,
            user_id=user,
            receipt_number=f"CF-{i:03d}",
            created_at=datetime(2026, 4, 1 + i, tzinfo=UTC),
        )

    out = await lookup_order_history(
        LookupOrderHistoryInput(student_id=user, limit=3)
    )
    assert out.total_returned == 3
    assert out.truncated is True


async def test_other_users_orders_not_returned(
    session_on_contextvar: AsyncSession,
) -> None:
    """SECURITY: cross-student leakage check. orders.user_id is the
    gate; the tool must filter on it strictly."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    await _insert_user(session_on_contextvar, user_a)
    await _insert_user(session_on_contextvar, user_b)
    await _insert_order(
        session_on_contextvar, user_id=user_b, receipt_number="OTHER-001"
    )

    out = await lookup_order_history(
        LookupOrderHistoryInput(student_id=user_a, limit=20)
    )
    assert out.total_returned == 0
    assert all(o.receipt_number != "OTHER-001" for o in out.orders)


# ── Schema validation ─────────────────────────────────────────────


def test_input_schema_rejects_invalid_limit() -> None:
    with pytest.raises(ValidationError):
        LookupOrderHistoryInput(student_id=uuid.uuid4(), limit=0)
    with pytest.raises(ValidationError):
        LookupOrderHistoryInput(student_id=uuid.uuid4(), limit=101)


def test_input_schema_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LookupOrderHistoryInput(  # type: ignore[call-arg]
            student_id=uuid.uuid4(), bogus="x"
        )


# ── Missing-session guard ─────────────────────────────────────────


async def test_raises_without_active_session() -> None:
    """Defensive: production never hits this path (call_agent sets
    the contextvar) but tests that forget to set it should fail
    loudly."""
    with pytest.raises(RuntimeError, match="active session"):
        await lookup_order_history(
            LookupOrderHistoryInput(student_id=uuid.uuid4(), limit=5)
        )


# ── asyncpg-rollback contract ─────────────────────────────────────


async def test_session_recovers_after_query_failure(
    session_on_contextvar: AsyncSession,
) -> None:
    """The same contract pinned for _load_goal_contract in Commit 5.
    When the SELECT inside lookup_order_history fails, the session
    must be recoverable for downstream INSERTs.
    """
    user = uuid.uuid4()
    await _insert_user(session_on_contextvar, user)

    from app.agents.tools.agent_specific.billing_support import (
        lookup_order_history as mod,
    )

    original_text = mod.sql_text

    def _failing_text(query: str):  # type: ignore[no-untyped-def]
        if "FROM orders" in query:
            return original_text(
                "SELECT nonexistent_column_for_test FROM orders WHERE user_id = :uid"
            )
        return original_text(query)

    with patch.object(mod, "sql_text", side_effect=_failing_text):
        out = await lookup_order_history(
            LookupOrderHistoryInput(student_id=user, limit=5)
        )

    # Tool should fail-soft to empty
    assert out.total_returned == 0
    assert out.orders == []

    # Session should be recoverable — downstream INSERT must succeed
    new_user = uuid.uuid4()
    await session_on_contextvar.execute(
        sql_text(
            "INSERT INTO users (id, email, full_name) "
            "VALUES (:id, :email, :name)"
        ),
        _seed_user(new_user),
    )
    await session_on_contextvar.flush()

    # Confirm the row landed
    raw = await session_on_contextvar.execute(
        sql_text("SELECT count(*) FROM users WHERE id = :id"),
        {"id": new_user},
    )
    assert raw.scalar_one() == 1, (
        "Downstream INSERT failed after lookup_order_history except path "
        "fired — rollback discipline is broken"
    )
