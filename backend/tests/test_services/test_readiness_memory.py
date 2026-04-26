"""Readiness memory service tests.

Coverage:

  1. no_prior_session_returns_none — first-time student gets no hint.
  2. prior_verdict_with_only_strengths_returns_none — if the prior
     verdict had no gap-evidence, there's nothing actionable to surface.
  3. closed_gap_appears_in_hint — a prior gap whose concept is in the
     snapshot's weaknesses_resolved_recent list shows up as "closed".
  4. open_gap_appears_in_hint — a prior gap whose concept is still in
     the snapshot's open_weaknesses list shows up as "still open".
  5. mixed_progress_combines_in_hint — closed + open gaps both surface.
  6. list_past_diagnoses_orders_newest_first — history endpoint helper.
  7. list_past_diagnoses_includes_north_star_fields — click +
     completion timestamps are surfaced for the UI.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.readiness import (
    DIAGNOSTIC_STATUS_COMPLETED,
    ReadinessDiagnosticSession,
    ReadinessVerdict,
)
from app.models.user import User
from app.services.readiness_memory_service import (
    build_prior_session_hint,
    list_past_diagnoses,
)
from app.services.student_snapshot_service import StudentSnapshot


async def _make_user(db: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"{uuid.uuid4()}@test.local",
        full_name="Memory Tester",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


def _snapshot(
    user_id: uuid.UUID,
    *,
    open_concepts: list[str] | None = None,
    resolved_recent: list[str] | None = None,
) -> StudentSnapshot:
    return StudentSnapshot(
        id=uuid.uuid4(),
        user_id=user_id,
        payload={
            "open_weaknesses": [
                {"concept": c, "severity": 0.5, "last_seen_at": None}
                for c in (open_concepts or [])
            ],
            "weaknesses_resolved_recent": resolved_recent or [],
        },
        evidence_allowlist=set(),
    )


async def _seed_prior_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    evidence: list[dict],
    completed_at: datetime | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    session = ReadinessDiagnosticSession(
        user_id=user_id,
        status=DIAGNOSTIC_STATUS_COMPLETED,
        completed_at=completed_at or datetime.now(UTC),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    verdict = ReadinessVerdict(
        session_id=session.id,
        headline="Prior session headline.",
        evidence=evidence,
        next_action_intent="skills_gap",
        next_action_route="/courses/x",
        next_action_label="Open lesson",
    )
    db.add(verdict)
    await db.commit()
    await db.refresh(verdict)

    session.verdict_id = verdict.id
    await db.commit()
    return session.id, verdict.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_prior_session_returns_none(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    snap = _snapshot(user_id)
    hint = await build_prior_session_hint(
        db_session, user_id=user_id, snapshot=snap
    )
    assert hint is None


@pytest.mark.asyncio
async def test_prior_verdict_with_only_strengths_returns_none(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    await _seed_prior_session(
        db_session,
        user_id,
        evidence=[
            {
                "text": "Strong Python skills",
                "evidence_id": "python",
                "kind": "strength",
            }
        ],
    )
    snap = _snapshot(user_id)
    hint = await build_prior_session_hint(
        db_session, user_id=user_id, snapshot=snap
    )
    assert hint is None, (
        "Prior verdict had no gap evidence — memory should not reach "
        "for a vague reference."
    )


@pytest.mark.asyncio
async def test_closed_gap_appears_in_hint(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    await _seed_prior_session(
        db_session,
        user_id,
        evidence=[
            {
                "text": "No SQL exposure",
                "evidence_id": "weakness:sql",
                "kind": "gap",
            }
        ],
    )
    snap = _snapshot(user_id, resolved_recent=["sql"])
    hint = await build_prior_session_hint(
        db_session, user_id=user_id, snapshot=snap
    )
    assert hint is not None
    assert "sql" in hint.lower()
    assert "closed" in hint.lower()


@pytest.mark.asyncio
async def test_open_gap_appears_in_hint(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    await _seed_prior_session(
        db_session,
        user_id,
        evidence=[
            {
                "text": "No system design exposure",
                "evidence_id": "weakness:system_design",
                "kind": "gap",
            }
        ],
    )
    snap = _snapshot(user_id, open_concepts=["system_design"])
    hint = await build_prior_session_hint(
        db_session, user_id=user_id, snapshot=snap
    )
    assert hint is not None
    assert "system_design" in hint.lower()
    assert "still open" in hint.lower()


@pytest.mark.asyncio
async def test_mixed_progress_combines_in_hint(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    await _seed_prior_session(
        db_session,
        user_id,
        evidence=[
            {
                "text": "No SQL",
                "evidence_id": "weakness:sql",
                "kind": "gap",
            },
            {
                "text": "No system design",
                "evidence_id": "weakness:system_design",
                "kind": "gap",
            },
        ],
    )
    snap = _snapshot(
        user_id,
        open_concepts=["system_design"],
        resolved_recent=["sql"],
    )
    hint = await build_prior_session_hint(
        db_session, user_id=user_id, snapshot=snap
    )
    assert hint is not None
    assert "sql" in hint.lower()
    assert "system_design" in hint.lower()
    assert "closed" in hint.lower()
    assert "still open" in hint.lower()


@pytest.mark.asyncio
async def test_list_past_diagnoses_orders_newest_first(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    older = datetime.now(UTC) - timedelta(days=14)
    newer = datetime.now(UTC) - timedelta(days=2)

    await _seed_prior_session(
        db_session,
        user_id,
        evidence=[],
        completed_at=older,
    )
    s_newer, _ = await _seed_prior_session(
        db_session,
        user_id,
        evidence=[],
        completed_at=newer,
    )

    items = await list_past_diagnoses(db_session, user_id=user_id)
    assert len(items) == 2
    assert items[0]["session_id"] == s_newer


@pytest.mark.asyncio
async def test_list_past_diagnoses_surfaces_north_star_fields(
    db_session: AsyncSession,
) -> None:
    """The history endpoint must expose next_action_clicked_at and
    next_action_completed_at — those are the north-star metric fields
    the UI needs to render badges like 'completed' / 'in progress'."""
    user_id = await _make_user(db_session)
    s_id, _v_id = await _seed_prior_session(
        db_session,
        user_id,
        evidence=[],
    )
    # Simulate the click + 24h completion.
    session = (
        await db_session.execute(
            ReadinessDiagnosticSession.__table__.select().where(
                ReadinessDiagnosticSession.id == s_id
            )
        )
    ).first()
    assert session is not None

    from sqlalchemy import update

    now = datetime.now(UTC)
    await db_session.execute(
        update(ReadinessDiagnosticSession)
        .where(ReadinessDiagnosticSession.id == s_id)
        .values(
            next_action_clicked_at=now,
            next_action_completed_at=now + timedelta(hours=4),
        )
    )
    await db_session.commit()

    items = await list_past_diagnoses(db_session, user_id=user_id)
    assert items[0]["next_action_clicked_at"] is not None
    assert items[0]["next_action_completed_at"] is not None
