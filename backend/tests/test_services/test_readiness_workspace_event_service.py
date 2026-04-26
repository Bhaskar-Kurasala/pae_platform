"""Tests for ``app.services.readiness_workspace_event_service``."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.readiness_workspace_event_service import (
    event_summary,
    list_recent_events,
    record_event,
    record_events_batch,
)


async def _make_user(db: AsyncSession, *, email: str = "ws@test.dev") -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        full_name="Workspace Tester",
        hashed_password="x",
        role="student",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_record_event_writes_row_with_all_fields(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    payload = {"button": "build_kit", "kind": "primary"}
    occurred = datetime.now(UTC) - timedelta(minutes=3)

    row = await record_event(
        db_session,
        user_id=user.id,
        view="kit",
        event="cta_clicked",
        payload=payload,
        session_id=None,
        occurred_at=occurred,
    )

    assert row.id is not None
    assert row.user_id == user.id
    assert row.view == "kit"
    assert row.event == "cta_clicked"
    assert row.payload == payload
    assert row.session_id is None
    # occurred_at preserved as supplied. SQLite drops tzinfo on TIMESTAMPTZ
    # columns (Postgres preserves it in prod) — compare in UTC-naive form.
    expected = occurred.astimezone(UTC).replace(tzinfo=None)
    actual = row.occurred_at
    if actual.tzinfo is not None:
        actual = actual.astimezone(UTC).replace(tzinfo=None)
    assert actual == expected


@pytest.mark.asyncio
async def test_record_event_rejects_unknown_view(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, email="bad-view@test.dev")
    with pytest.raises(ValueError, match="unknown view"):
        await record_event(
            db_session,
            user_id=user.id,
            view="not_a_view",
            event="cta_clicked",
        )


@pytest.mark.asyncio
async def test_record_event_accepts_unknown_event_softly(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, email="soft@test.dev")
    row = await record_event(
        db_session,
        user_id=user.id,
        view="overview",
        event="brand_new_event_kind",
    )
    assert row.event == "brand_new_event_kind"


@pytest.mark.asyncio
async def test_record_events_batch_skips_invalid_entries(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, email="batch@test.dev")
    events = [
        {"view": "overview", "event": "view_opened"},
        {"view": "resume", "event": "cta_clicked", "payload": {"x": 1}},
        # invalid: missing view
        {"event": "cta_clicked"},
        # invalid: bogus view
        {"view": "no_such_view", "event": "cta_clicked"},
        # invalid: payload is a string, not dict
        {"view": "kit", "event": "cta_clicked", "payload": "nope"},
        # valid: unknown event passes through
        {"view": "jd", "event": "totally_new_thing"},
    ]
    recorded = await record_events_batch(
        db_session, user_id=user.id, events=events
    )
    assert recorded == 3

    rows = await list_recent_events(db_session, user_id=user.id, limit=10)
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_list_recent_events_newest_first_with_view_filter(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, email="list@test.dev")
    base = datetime.now(UTC) - timedelta(hours=1)
    await record_event(
        db_session,
        user_id=user.id,
        view="overview",
        event="view_opened",
        occurred_at=base,
    )
    await record_event(
        db_session,
        user_id=user.id,
        view="resume",
        event="view_opened",
        occurred_at=base + timedelta(minutes=5),
    )
    await record_event(
        db_session,
        user_id=user.id,
        view="overview",
        event="cta_clicked",
        occurred_at=base + timedelta(minutes=10),
    )

    rows = await list_recent_events(db_session, user_id=user.id, limit=10)
    assert [r.event for r in rows] == [
        "cta_clicked",
        "view_opened",
        "view_opened",
    ]

    overview_only = await list_recent_events(
        db_session, user_id=user.id, view="overview", limit=10
    )
    assert len(overview_only) == 2
    assert all(r.view == "overview" for r in overview_only)


@pytest.mark.asyncio
async def test_event_summary_aggregates_correctly(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, email="sum@test.dev")
    now = datetime.now(UTC)
    await record_event(
        db_session,
        user_id=user.id,
        view="overview",
        event="view_opened",
        occurred_at=now - timedelta(hours=1),
    )
    await record_event(
        db_session,
        user_id=user.id,
        view="overview",
        event="cta_clicked",
        occurred_at=now - timedelta(hours=2),
    )
    await record_event(
        db_session,
        user_id=user.id,
        view="kit",
        event="cta_clicked",
        occurred_at=now - timedelta(minutes=10),
    )

    summary = await event_summary(db_session, user_id=user.id, since_days=7)
    assert summary["total"] == 3
    assert summary["by_view"] == {"overview": 2, "kit": 1}
    assert summary["by_event"] == {"view_opened": 1, "cta_clicked": 2}
    assert summary["last_event_at"] is not None


@pytest.mark.asyncio
async def test_event_summary_empty_user_returns_zeroes(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, email="empty@test.dev")
    summary = await event_summary(db_session, user_id=user.id, since_days=7)
    assert summary == {
        "total": 0,
        "by_view": {},
        "by_event": {},
        "last_event_at": None,
    }
