"""F5 — Outreach email service tests.

Verifies the four guarantees:
  1. Without SENDGRID_API_KEY → status='mocked' (no network call)
  2. With key + valid template → status='sent' + outreach_log row
  3. F3 throttle blocks repeats → status='throttled' (no row written)
  4. Missing recipient → status='no_recipient' (row written for audit)
  5. Template render failure → status='failed' + outreach_log row

We mock SendGrid via monkeypatch so no network ever happens during tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outreach_log import OutreachLog
from app.models.user import User
from app.services import outreach_email_service


async def _make_user(db: AsyncSession, *, email: str = "test@pae.dev") -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        full_name="Test User",
        hashed_password="x",
        role="student",
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_send_without_api_key_is_mocked(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No SENDGRID_API_KEY → audit row exists with status='mocked'."""
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    user = await _make_user(db_session)

    # Mock the template renderer because we don't have templates in
    # the test env. F6 ships them; here we just want the wiring.
    def fake_render(key: str, vars: dict) -> tuple[str, str]:
        return ("Subject!", f"<p>Hello {vars.get('name', 'there')}</p>")

    monkeypatch.setattr(outreach_email_service, "render_template", fake_render)

    result = await outreach_email_service.send_outreach_email(
        db_session,
        user_id=user.id,
        to_email=user.email,
        template_key="cold_signup_day_1",
        template_vars={"name": "Bhaskar"},
        slip_type="cold_signup",
        triggered_by="system_nightly",
    )

    assert result.status == "mocked"
    # Row exists with status='mocked'.
    row = await db_session.get(OutreachLog, result.log_id)
    assert row is not None
    assert row.status == "mocked"
    assert row.template_key == "cold_signup_day_1"
    assert row.body_preview is not None
    assert "Bhaskar" in row.body_preview


@pytest.mark.asyncio
async def test_send_throttled_returns_throttled(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A previous send within the window blocks the next one."""
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    user = await _make_user(db_session)

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

    monkeypatch.setattr(
        outreach_email_service,
        "render_template",
        lambda k, v: ("S", "<p>x</p>"),
    )

    result = await outreach_email_service.send_outreach_email(
        db_session,
        user_id=user.id,
        to_email=user.email,
        template_key="cold_signup_day_1",
        template_vars={},
    )
    assert result.status == "throttled"
    assert result.skipped_reason is not None
    assert "cold_signup_day_1" in result.skipped_reason


@pytest.mark.asyncio
async def test_no_recipient_returns_no_recipient(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty to_email → no_recipient + audit row written."""
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    user = await _make_user(db_session)

    monkeypatch.setattr(
        outreach_email_service,
        "render_template",
        lambda k, v: ("S", "<p>x</p>"),
    )

    result = await outreach_email_service.send_outreach_email(
        db_session,
        user_id=user.id,
        to_email="",
        template_key="cold_signup_day_1",
        template_vars={},
    )
    assert result.status == "no_recipient"
    row = await db_session.get(OutreachLog, result.log_id)
    assert row is not None
    assert row.status == "failed"
    assert row.error is not None and "no recipient" in row.error


@pytest.mark.asyncio
async def test_render_failure_returns_failed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Template render exception → failed status + audit row."""
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    user = await _make_user(db_session)

    def boom(_k, _v):
        raise ValueError("template not found")

    monkeypatch.setattr(outreach_email_service, "render_template", boom)

    result = await outreach_email_service.send_outreach_email(
        db_session,
        user_id=user.id,
        to_email=user.email,
        template_key="missing_template",
        template_vars={},
    )
    assert result.status == "failed"
    assert "render" in (result.skipped_reason or "")
    row = await db_session.get(OutreachLog, result.log_id)
    assert row is not None
    assert row.status == "failed"
    assert row.error is not None and "render" in row.error


@pytest.mark.asyncio
async def test_send_with_api_key_calls_sendgrid(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With an API key + working SendGrid, status flips to 'sent'."""
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.fake-test-key")
    user = await _make_user(db_session)

    monkeypatch.setattr(
        outreach_email_service,
        "render_template",
        lambda k, v: ("Subject!", f"<p>Hello {v.get('name', 'there')}</p>"),
    )

    captured: dict[str, str] = {}

    def fake_sendgrid(*, api_key: str, to_email: str, subject: str, html_body: str) -> str:
        captured["api_key"] = api_key
        captured["to_email"] = to_email
        captured["subject"] = subject
        captured["html_body"] = html_body
        return "sg_external_id_xyz"

    monkeypatch.setattr(outreach_email_service, "_sendgrid_send", fake_sendgrid)

    result = await outreach_email_service.send_outreach_email(
        db_session,
        user_id=user.id,
        to_email=user.email,
        template_key="paid_silent_day_3",
        template_vars={"name": "Test"},
        slip_type="paid_silent",
    )

    assert result.status == "sent"
    assert result.external_id == "sg_external_id_xyz"
    assert captured["to_email"] == user.email
    assert "Hello Test" in captured["html_body"]

    row = await db_session.get(OutreachLog, result.log_id)
    assert row is not None
    assert row.status == "sent"
    assert row.external_id == "sg_external_id_xyz"


@pytest.mark.asyncio
async def test_sdk_exception_is_swallowed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SendGrid 5xx must not propagate — soft fail to status='failed'."""
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.fake-test-key")
    user = await _make_user(db_session)

    monkeypatch.setattr(
        outreach_email_service,
        "render_template",
        lambda k, v: ("S", "<p>x</p>"),
    )

    def boom(**_kwargs):
        raise RuntimeError("SendGrid 503")

    monkeypatch.setattr(outreach_email_service, "_sendgrid_send", boom)

    # Should NOT raise.
    result = await outreach_email_service.send_outreach_email(
        db_session,
        user_id=user.id,
        to_email=user.email,
        template_key="paid_silent_day_3",
        template_vars={},
    )
    assert result.status == "failed"
    assert "503" in (result.skipped_reason or "")
    row = await db_session.get(OutreachLog, result.log_id)
    assert row is not None
    assert row.status == "failed"
    assert row.error is not None and "503" in row.error
