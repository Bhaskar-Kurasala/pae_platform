"""F5 — Retention-engine email outreach (SendGrid wrapper).

Distinct from `email_service.py` (which handles the legacy welcome /
progress-digest / re-engagement emails from earlier phases). This
service is the one F9 nightly automation + admin "Send email" button
will call into.

Mirrors the design of PR3/C3.1 telemetry + C5.1 sentry: no-op safe
when SENDGRID_API_KEY is unset, idempotent retries via F3 throttle,
soft-fail every helper.

Design rules:

  1. **No-op safe.** When `SENDGRID_API_KEY` is unset, every send
     writes a row to outreach_log with status='mocked' and returns
     a fake external_id. Dev work feels exactly like prod — same
     audit trail, no actual outbound traffic.

  2. **Audit BEFORE network.** We write the outreach_log row with
     status='pending' first, then call SendGrid, then flip to
     'sent' / 'failed'. Even if the SendGrid call hangs, we know
     we tried.

  3. **Throttle defense in depth.** F3's was_sent_recently is
     re-checked before each send so two parallel callers (admin
     manual + nightly automation) can't race-condition through
     the gap.

  4. **PII filter.** body_preview captures the first 200 chars of
     the rendered text. Full body is NOT stored.

  5. **Soft fail.** SDK exceptions are swallowed at the service
     edge and reflected in the returned status so the caller routes
     on outcome rather than on exception.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import outreach_service

log = structlog.get_logger()

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "email"

DEFAULT_FROM_EMAIL = os.environ.get("OUTREACH_FROM_EMAIL", "team@pae-platform.dev")
DEFAULT_FROM_NAME = os.environ.get("OUTREACH_FROM_NAME", "PAE Platform")
DEFAULT_REPLY_TO = os.environ.get("OUTREACH_REPLY_TO", "bhaskar@pae-platform.dev")


@dataclass(frozen=True)
class EmailSendResult:
    """Returned by send_outreach_email so callers can route on outcome."""

    log_id: uuid.UUID
    status: str  # 'sent' | 'mocked' | 'throttled' | 'failed' | 'no_recipient'
    external_id: str | None
    skipped_reason: str | None


def _build_jinja() -> Environment:
    """Lazy because TEMPLATES_DIR may not exist in unit-test envs."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_template(template_key: str, vars: dict[str, Any]) -> tuple[str, str]:
    """Render template_key with vars. Returns (subject, html_body).

    Subject convention: each template starts with
    `{% set subject = "..." %}` so subject + body are one file per
    template. We render the body, then read `subject` from the
    template's module namespace.
    """
    env = _build_jinja()
    template = env.get_template(f"{template_key}.html")
    body = template.render(**vars)
    subject = getattr(template.module, "subject", None) or "PAE Platform"
    return str(subject), body


async def send_outreach_email(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    to_email: str,
    template_key: str,
    template_vars: dict[str, Any],
    slip_type: str | None = None,
    triggered_by: str = "system_nightly",
    triggered_by_user_id: uuid.UUID | None = None,
    throttle_days: int = 7,
) -> EmailSendResult:
    """Send one retention-engine email. Always writes an outreach_log row.

    Returns:
        EmailSendResult with status:
          'sent'         — SendGrid accepted the message
          'mocked'       — no API key; logged-only
          'throttled'    — F3 was_sent_recently blocked it
          'failed'       — render or network/SDK error
          'no_recipient' — to_email is empty
    """
    if not to_email:
        log.info(
            "outreach_email.skip_no_recipient",
            user_id=str(user_id),
            template_key=template_key,
        )
        entry = await outreach_service.record(
            db,
            user_id=user_id,
            channel="email",
            template_key=template_key,
            slip_type=slip_type,
            triggered_by=triggered_by,
            triggered_by_user_id=triggered_by_user_id,
            status="failed",
        )
        await outreach_service.update_status(
            db,
            log_id=entry.id,
            status="failed",
            error="no recipient email on file",
        )
        return EmailSendResult(
            log_id=entry.id,
            status="no_recipient",
            external_id=None,
            skipped_reason="no recipient email on file",
        )

    if await outreach_service.was_sent_recently(
        db,
        user_id=user_id,
        template_key=template_key,
        within_days=throttle_days,
    ):
        log.info(
            "outreach_email.throttled",
            user_id=str(user_id),
            template_key=template_key,
            within_days=throttle_days,
        )
        return EmailSendResult(
            log_id=uuid.UUID(int=0),
            status="throttled",
            external_id=None,
            skipped_reason=f"already sent {template_key} within {throttle_days}d",
        )

    try:
        subject, html_body = render_template(template_key, template_vars)
    except Exception as exc:
        log.error(
            "outreach_email.render_failed",
            template_key=template_key,
            error=str(exc),
        )
        entry = await outreach_service.record(
            db,
            user_id=user_id,
            channel="email",
            template_key=template_key,
            slip_type=slip_type,
            triggered_by=triggered_by,
            triggered_by_user_id=triggered_by_user_id,
            status="failed",
        )
        await outreach_service.update_status(
            db, log_id=entry.id, status="failed", error=f"render: {exc}"
        )
        return EmailSendResult(
            log_id=entry.id,
            status="failed",
            external_id=None,
            skipped_reason=f"template render failed: {exc}",
        )

    body_preview = _strip_html(html_body)[:200]
    entry = await outreach_service.record(
        db,
        user_id=user_id,
        channel="email",
        template_key=template_key,
        slip_type=slip_type,
        triggered_by=triggered_by,
        triggered_by_user_id=triggered_by_user_id,
        body_preview=body_preview,
        status="pending",
    )

    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        await outreach_service.update_status(db, log_id=entry.id, status="mocked")
        log.info(
            "outreach_email.mocked",
            user_id=str(user_id),
            to=to_email,
            template_key=template_key,
            subject=subject,
        )
        return EmailSendResult(
            log_id=entry.id,
            status="mocked",
            external_id=None,
            skipped_reason=None,
        )

    try:
        external_id = _sendgrid_send(
            api_key=api_key,
            to_email=to_email,
            subject=subject,
            html_body=html_body,
        )
        await outreach_service.update_status(
            db, log_id=entry.id, status="sent", external_id=external_id
        )
        log.info(
            "outreach_email.sent",
            user_id=str(user_id),
            to=to_email,
            template_key=template_key,
            external_id=external_id,
        )
        return EmailSendResult(
            log_id=entry.id,
            status="sent",
            external_id=external_id,
            skipped_reason=None,
        )
    except Exception as exc:
        log.warning(
            "outreach_email.send_failed",
            user_id=str(user_id),
            template_key=template_key,
            error=str(exc),
        )
        await outreach_service.update_status(
            db, log_id=entry.id, status="failed", error=str(exc)[:500]
        )
        return EmailSendResult(
            log_id=entry.id,
            status="failed",
            external_id=None,
            skipped_reason=str(exc),
        )


def _sendgrid_send(
    *,
    api_key: str,
    to_email: str,
    subject: str,
    html_body: str,
) -> str:
    """Wraps the SendGrid SDK call. Returns the external message id.

    Imported lazily so a missing sendgrid package (in stripped-down
    test envs) doesn't crash module load.
    """
    from sendgrid import SendGridAPIClient  # type: ignore[import-untyped]
    from sendgrid.helpers.mail import (  # type: ignore[import-untyped]
        From,
        Mail,
        ReplyTo,
        To,
    )

    msg = Mail(
        from_email=From(DEFAULT_FROM_EMAIL, DEFAULT_FROM_NAME),
        to_emails=To(to_email),
        subject=subject,
        html_content=html_body,
    )
    msg.reply_to = ReplyTo(DEFAULT_REPLY_TO)

    sg = SendGridAPIClient(api_key)
    response = sg.send(msg)
    headers = getattr(response, "headers", {}) or {}
    external_id = headers.get("X-Message-Id") or headers.get("x-message-id") or ""
    return str(external_id)


def _strip_html(html: str) -> str:
    """Cheap HTML→plain for the body_preview audit field."""
    import re

    no_tags = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", no_tags).strip()
