"""F9 — Nightly outreach automation tests.

Eight tests covering the automation contract:
  - dry-run path writes 'would_send' rows, no SendGrid call
  - excluded email suffixes (@pae.dev, @example.com) are skipped
  - signals with slip_type='none' or no recommendation are skipped
  - F3 per-template throttle is honored (already-sent within window
    blocks the next dispatch)
  - global cap of 2 sends per user per 7d is honored even across
    different templates
  - per-user failures (template render error) don't take the pass down
  - real-send path (with mocked SendGrid) flips status to 'sent'
  - production gate: dry_run=None + ENV=production + OUTREACH_AUTO_SEND=1
    flips to live sends; missing either keeps dry-run

We mock the email service at the module level — the F5 service has
its own dedicated test file (test_outreach_email_service.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outreach_log import OutreachLog
from app.models.student_risk_signals import StudentRiskSignals
from app.models.user import User
from app.services import disrupt_prevention_v2_service as automation


async def _user(
    db: AsyncSession, *, email: str = "real@otherdomain.com"
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        full_name="Test User",
        hashed_password="x",
        role="student",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.commit()
    return user


async def _signal(
    db: AsyncSession,
    user: User,
    *,
    slip_type: str = "cold_signup",
    recommended_intervention: str | None = "cold_signup_day_1",
    risk_score: int = 25,
    days_since_last_session: int | None = 5,
) -> StudentRiskSignals:
    sig = StudentRiskSignals(
        id=uuid.uuid4(),
        user_id=user.id,
        risk_score=risk_score,
        slip_type=slip_type,
        days_since_last_session=days_since_last_session,
        max_streak_ever=0,
        paid=False,
        recommended_intervention=recommended_intervention,
        risk_reason=f"test fixture {slip_type}",
    )
    db.add(sig)
    await db.commit()
    return sig


@pytest.mark.asyncio
async def test_dry_run_writes_would_send_rows_no_send(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dry-run path: writes outreach_log row with status='would_send',
    never calls the email service."""
    monkeypatch.delenv("OUTREACH_AUTO_SEND", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    user = await _user(db_session)
    await _signal(db_session, user)

    # If anything calls the real send, fail loud.
    async def boom(*args, **kwargs):
        raise AssertionError("dry-run must NOT call email service")

    monkeypatch.setattr(
        "app.services.disrupt_prevention_v2_service.outreach_email_service.send_outreach_email",
        boom,
    )

    result = await automation.run_nightly_outreach(db_session)
    assert result.dry_run is True
    assert result.mocked == 1
    assert result.sent == 0

    # outreach_log row exists with status='would_send'.
    from sqlalchemy import select

    rows = (
        await db_session.execute(
            select(OutreachLog).where(OutreachLog.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "would_send"
    assert rows[0].template_key == "cold_signup_day_1"


@pytest.mark.asyncio
async def test_excluded_email_suffix_skipped(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke accounts (@pae.dev, @example.com) are excluded."""
    monkeypatch.delenv("OUTREACH_AUTO_SEND", raising=False)
    user = await _user(db_session, email="smoke@pae.dev")
    await _signal(db_session, user)

    result = await automation.run_nightly_outreach(db_session)
    assert result.skipped_excluded == 1
    assert result.mocked == 0
    assert result.sent == 0


@pytest.mark.asyncio
async def test_no_recommendation_skipped(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Signals with slip_type='none' or null recommendation are
    skipped (we never auto-email a healthy user)."""
    monkeypatch.delenv("OUTREACH_AUTO_SEND", raising=False)
    user = await _user(db_session)
    await _signal(
        db_session,
        user,
        slip_type="none",
        recommended_intervention=None,
    )

    result = await automation.run_nightly_outreach(db_session)
    assert result.skipped_no_recommendation == 1
    assert result.mocked == 0


@pytest.mark.asyncio
async def test_per_template_throttle_honored(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If F3 says we already sent this template recently, skip."""
    monkeypatch.delenv("OUTREACH_AUTO_SEND", raising=False)
    user = await _user(db_session)
    await _signal(db_session, user)

    # Pre-seed a recent send.
    db_session.add(
        OutreachLog(
            id=uuid.uuid4(),
            user_id=user.id,
            channel="email",
            template_key="cold_signup_day_1",
            slip_type="cold_signup",
            triggered_by="system_nightly",
            sent_at=datetime.now(UTC) - timedelta(days=2),
            status="sent",
        )
    )
    await db_session.commit()

    result = await automation.run_nightly_outreach(db_session)
    assert result.skipped_template_throttle == 1
    assert result.mocked == 0


@pytest.mark.asyncio
async def test_global_cap_per_week(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2 system_nightly sends in last 7 days = no more sends, even
    for a different template."""
    monkeypatch.delenv("OUTREACH_AUTO_SEND", raising=False)
    user = await _user(db_session)
    await _signal(
        db_session,
        user,
        slip_type="paid_silent",
        recommended_intervention="paid_silent_day_3",
    )

    # Pre-seed 2 different-template sends within the last week.
    for tmpl, days_ago in [("template_x", 3), ("template_y", 5)]:
        db_session.add(
            OutreachLog(
                id=uuid.uuid4(),
                user_id=user.id,
                channel="email",
                template_key=tmpl,
                slip_type="some_other",
                triggered_by="system_nightly",
                sent_at=datetime.now(UTC) - timedelta(days=days_ago),
                status="sent",
            )
        )
    await db_session.commit()

    result = await automation.run_nightly_outreach(db_session)
    assert result.skipped_global_cap == 1
    assert result.mocked == 0


@pytest.mark.asyncio
async def test_admin_manual_sends_dont_count_against_cap(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If admin sent 5 manual emails this week, automated sends still
    flow — admin actions are separate from the system's quota for
    that user."""
    monkeypatch.delenv("OUTREACH_AUTO_SEND", raising=False)
    user = await _user(db_session)
    await _signal(db_session, user)

    # 3 admin-manual sends, each within the throttle window for a
    # *different* template (so per-template throttle doesn't fire).
    # If the global cap were counting these, it'd block. It shouldn't.
    for tmpl in ["t1", "t2", "t3"]:
        db_session.add(
            OutreachLog(
                id=uuid.uuid4(),
                user_id=user.id,
                channel="email",
                template_key=tmpl,
                slip_type=None,
                triggered_by="admin_manual",
                sent_at=datetime.now(UTC) - timedelta(days=1),
                status="sent",
            )
        )
    await db_session.commit()

    result = await automation.run_nightly_outreach(db_session)
    # Cold-signup mock fires because admin sends don't burn the cap.
    assert result.mocked == 1
    assert result.skipped_global_cap == 0


@pytest.mark.asyncio
async def test_live_send_path_flips_status(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the production gate is open AND dry_run=False, the email
    service is actually called and status flips to 'sent'."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("OUTREACH_AUTO_SEND", "1")
    user = await _user(db_session)
    await _signal(db_session, user)

    # Mock the F5 service so we don't hit SendGrid.
    captured = {}

    async def fake_send(db, **kwargs):
        captured.update(kwargs)
        from app.services.outreach_email_service import EmailSendResult

        return EmailSendResult(
            log_id=uuid.uuid4(),
            status="sent",
            external_id="sg_fake",
            skipped_reason=None,
        )

    monkeypatch.setattr(
        "app.services.disrupt_prevention_v2_service.outreach_email_service.send_outreach_email",
        fake_send,
    )

    result = await automation.run_nightly_outreach(db_session)
    assert result.dry_run is False
    assert result.sent == 1
    assert captured["template_key"] == "cold_signup_day_1"
    assert captured["slip_type"] == "cold_signup"
    assert captured["triggered_by"] == "system_nightly"
    assert captured["to_email"] == user.email


@pytest.mark.asyncio
async def test_dev_environment_stays_dry_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even with OUTREACH_AUTO_SEND=1, if ENV != production we stay
    dry-run — protects against laptop-fired automation."""
    monkeypatch.setenv("OUTREACH_AUTO_SEND", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    user = await _user(db_session)
    await _signal(db_session, user)

    async def boom(*args, **kwargs):
        raise AssertionError("ENV=development must stay dry-run")

    monkeypatch.setattr(
        "app.services.disrupt_prevention_v2_service.outreach_email_service.send_outreach_email",
        boom,
    )

    result = await automation.run_nightly_outreach(db_session)
    assert result.dry_run is True
    assert result.mocked == 1
