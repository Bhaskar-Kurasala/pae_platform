"""Unit tests for EmailService."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email_service import EmailService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_svc_with_client() -> EmailService:
    """Return an EmailService instance whose _client is a mock."""
    svc = EmailService.__new__(EmailService)
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_client.send.return_value = mock_response
    svc._client = mock_client
    return svc


def _make_svc_no_client() -> EmailService:
    """Return an EmailService with no SendGrid client (key not configured)."""
    svc = EmailService.__new__(EmailService)
    svc._client = None
    return svc


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------


def test_is_configured_true_when_client_set() -> None:
    svc = _make_svc_with_client()
    assert svc._is_configured() is True


def test_is_configured_false_when_no_client() -> None:
    svc = _make_svc_no_client()
    assert svc._is_configured() is False


# ---------------------------------------------------------------------------
# send_welcome
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_welcome_returns_true_on_success() -> None:
    svc = _make_svc_with_client()
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.sendgrid_from_email = "noreply@pae.dev"
        result = await svc.send_welcome("user@example.com", "Alice")
    assert result is True


@pytest.mark.asyncio
async def test_send_welcome_returns_false_when_not_configured() -> None:
    svc = _make_svc_no_client()
    result = await svc.send_welcome("user@example.com", "Alice")
    assert result is False


@pytest.mark.asyncio
async def test_send_welcome_returns_false_on_exception() -> None:
    svc = _make_svc_with_client()
    svc._client.send.side_effect = Exception("network error")
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.sendgrid_from_email = "noreply@pae.dev"
        result = await svc.send_welcome("user@example.com", "Bob")
    assert result is False


# ---------------------------------------------------------------------------
# send_progress_digest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_progress_digest_success() -> None:
    svc = _make_svc_with_client()
    stats = {"lessons_completed": 5, "skills_touched": 3, "streak_days": 4, "top_concept": "RAG"}
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.sendgrid_from_email = "noreply@pae.dev"
        result = await svc.send_progress_digest("user@example.com", "Carol", stats)
    assert result is True


@pytest.mark.asyncio
async def test_send_progress_digest_not_configured() -> None:
    svc = _make_svc_no_client()
    result = await svc.send_progress_digest("user@example.com", "Carol", {})
    assert result is False


# ---------------------------------------------------------------------------
# send_reengage — all three inactivity buckets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_reengage_short_inactive() -> None:
    svc = _make_svc_with_client()
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.sendgrid_from_email = "noreply@pae.dev"
        result = await svc.send_reengage("u@x.com", "Dave", days_inactive=4)
    assert result is True
    # Verify the subject line matches the gentle-nudge bucket
    call_args = svc._client.send.call_args
    mail_obj = call_args[0][0]
    assert "miss you" in str(mail_obj.subject).lower()


@pytest.mark.asyncio
async def test_send_reengage_medium_inactive() -> None:
    svc = _make_svc_with_client()
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.sendgrid_from_email = "noreply@pae.dev"
        result = await svc.send_reengage("u@x.com", "Eve", days_inactive=10)
    assert result is True


@pytest.mark.asyncio
async def test_send_reengage_long_inactive() -> None:
    svc = _make_svc_with_client()
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.sendgrid_from_email = "noreply@pae.dev"
        result = await svc.send_reengage("u@x.com", "Frank", days_inactive=20)
    assert result is True


# ---------------------------------------------------------------------------
# send_enrollment_confirmation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_enrollment_confirmation_success() -> None:
    svc = _make_svc_with_client()
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.sendgrid_from_email = "noreply@pae.dev"
        result = await svc.send_enrollment_confirmation(
            "u@x.com", "Grace", "Production RAG Engineering"
        )
    assert result is True


@pytest.mark.asyncio
async def test_send_enrollment_confirmation_not_configured() -> None:
    svc = _make_svc_no_client()
    result = await svc.send_enrollment_confirmation("u@x.com", "Grace", "Course Name")
    assert result is False
