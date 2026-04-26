"""Tests for cohort_event_service — handle masking + DB-backed feed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.cohort_event_service import (
    mask_handle,
    peers_active_today,
    promotions_today,
    record_event,
    recent_events,
)


# ---------------------------------------------------------------------------
# mask_handle — pure
# ---------------------------------------------------------------------------


def test_mask_handle_two_names_uses_first_and_last_initial() -> None:
    assert mask_handle("Priya Kumar") == "Priya K."


def test_mask_handle_single_name_returns_first_only() -> None:
    assert mask_handle("Cher") == "Cher"


def test_mask_handle_empty_string_returns_fallback() -> None:
    assert mask_handle("") == "A peer"


def test_mask_handle_none_returns_fallback() -> None:
    assert mask_handle(None) == "A peer"


def test_mask_handle_whitespace_only_returns_fallback() -> None:
    assert mask_handle("   ") == "A peer"


def test_mask_handle_collapses_internal_multispace() -> None:
    # "Priya   Singh   Kumar" -> first + initial of last
    assert mask_handle("Priya   Singh   Kumar") == "Priya K."


def test_mask_handle_three_names_uses_first_and_last_initial() -> None:
    assert mask_handle("Maria Sofia Lopez") == "Maria L."


def test_mask_handle_custom_fallback() -> None:
    assert mask_handle(None, fallback="Anonymous") == "Anonymous"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _make_user(
    db: AsyncSession, email: str, full_name: str = "Priya Kumar"
) -> User:
    u = User(email=email, full_name=full_name, role="student")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


# ---------------------------------------------------------------------------
# record_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_event_masks_actor_handle(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, "p@test.dev", "Priya Kumar")
    ev = await record_event(
        db_session,
        kind="level_up",
        actor=user,
        label="reached Python Developer",
        level_slug="python_developer",
    )
    assert ev.actor_handle == "Priya K."
    assert ev.kind == "level_up"
    assert ev.actor_id == user.id
    assert ev.level_slug == "python_developer"


@pytest.mark.asyncio
async def test_record_event_with_no_actor_uses_fallback(
    db_session: AsyncSession,
) -> None:
    ev = await record_event(
        db_session, kind="cohort_milestone", actor=None, label="100 graduates"
    )
    assert ev.actor_id is None
    assert ev.actor_handle == "A peer"


# ---------------------------------------------------------------------------
# recent_events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recent_events_newest_first(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "n@test.dev")
    base = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    await record_event(
        db_session,
        kind="ship",
        actor=user,
        label="oldest",
        occurred_at=base - timedelta(hours=3),
    )
    await record_event(
        db_session,
        kind="ship",
        actor=user,
        label="middle",
        occurred_at=base - timedelta(hours=2),
    )
    await record_event(
        db_session,
        kind="ship",
        actor=user,
        label="newest",
        occurred_at=base - timedelta(hours=1),
    )
    events = await recent_events(db_session, limit=5)
    assert [e.label for e in events] == ["newest", "middle", "oldest"]


@pytest.mark.asyncio
async def test_recent_events_filters_by_level(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "lvl@test.dev")
    await record_event(
        db_session,
        kind="level_up",
        actor=user,
        label="py",
        level_slug="python_developer",
    )
    await record_event(
        db_session,
        kind="level_up",
        actor=user,
        label="data",
        level_slug="data_engineer",
    )
    py_events = await recent_events(
        db_session, level_slug="python_developer"
    )
    assert {e.label for e in py_events} == {"py"}


@pytest.mark.asyncio
async def test_recent_events_filters_by_kind(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "kf@test.dev")
    await record_event(db_session, kind="ship", actor=user, label="s")
    await record_event(db_session, kind="level_up", actor=user, label="l")
    out = await recent_events(db_session, kinds=["level_up"])
    assert {e.kind for e in out} == {"level_up"}


@pytest.mark.asyncio
async def test_recent_events_respects_limit(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "lim@test.dev")
    for i in range(5):
        await record_event(
            db_session,
            kind="ship",
            actor=user,
            label=f"e{i}",
            occurred_at=datetime(2026, 4, 25, 10 + i, 0, tzinfo=UTC),
        )
    out = await recent_events(db_session, limit=2)
    assert len(out) == 2


# ---------------------------------------------------------------------------
# peers_active_today
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peers_active_today_counts_distinct_actors(
    db_session: AsyncSession,
) -> None:
    a = await _make_user(db_session, "a@test.dev", "Alpha One")
    b = await _make_user(db_session, "b@test.dev", "Beta Two")
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    # Two events from the same actor still count as 1 distinct peer.
    await record_event(
        db_session, kind="ship", actor=a, label="x", occurred_at=now
    )
    await record_event(
        db_session,
        kind="ship",
        actor=a,
        label="y",
        occurred_at=now - timedelta(hours=2),
    )
    await record_event(
        db_session,
        kind="ship",
        actor=b,
        label="z",
        occurred_at=now - timedelta(hours=1),
    )
    count = await peers_active_today(db_session, now=now)
    assert count == 2


@pytest.mark.asyncio
async def test_peers_active_today_excludes_older_than_24h(
    db_session: AsyncSession,
) -> None:
    a = await _make_user(db_session, "old@test.dev")
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    await record_event(
        db_session,
        kind="ship",
        actor=a,
        label="ancient",
        occurred_at=now - timedelta(hours=48),
    )
    assert await peers_active_today(db_session, now=now) == 0


@pytest.mark.asyncio
async def test_peers_active_today_ignores_null_actor(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    await record_event(
        db_session,
        kind="cohort_milestone",
        actor=None,
        label="system",
        occurred_at=now,
    )
    assert await peers_active_today(db_session, now=now) == 0


# ---------------------------------------------------------------------------
# promotions_today
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promotions_today_filters_by_level_up_kind(
    db_session: AsyncSession,
) -> None:
    a = await _make_user(db_session, "p1@test.dev")
    b = await _make_user(db_session, "p2@test.dev")
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    await record_event(
        db_session, kind="level_up", actor=a, label="up", occurred_at=now
    )
    await record_event(
        db_session, kind="level_up", actor=b, label="up", occurred_at=now
    )
    # different kind should not be counted
    await record_event(
        db_session, kind="ship", actor=a, label="x", occurred_at=now
    )
    assert await promotions_today(db_session, now=now) == 2


@pytest.mark.asyncio
async def test_promotions_today_excludes_older_than_24h(
    db_session: AsyncSession,
) -> None:
    a = await _make_user(db_session, "exp@test.dev")
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    await record_event(
        db_session,
        kind="level_up",
        actor=a,
        label="old",
        occurred_at=now - timedelta(hours=25),
    )
    assert await promotions_today(db_session, now=now) == 0
