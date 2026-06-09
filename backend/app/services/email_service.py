# SendGrid email service — welcome, progress digest, re-engagement,
# enrollment confirmation, password reset, email verification (Batch 1).
import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from app.core.config import settings

log = structlog.get_logger()

_FROM_EMAIL_DEFAULT = "noreply@pae.dev"

# Batch 1 / D-F — maximum emails of any single token_type per user per hour.
_EMAIL_RATE_LIMIT = 5


def _get_from_email() -> str:
    return settings.sendgrid_from_email or _FROM_EMAIL_DEFAULT


def _hour_bucket() -> str:
    """Return a string key representing the current UTC hour bucket."""
    now = datetime.now(UTC)
    return f"{now.year}{now.month:02d}{now.day:02d}{now.hour:02d}"


async def check_email_rate_limit(user_id: uuid.UUID, token_type: str) -> bool:
    """Return True if the email may be sent; False if the rate limit is exceeded.

    Enforced via Redis INCR + EXPIRE. Key expires after one hour so the
    counter resets naturally. Fail-open: if Redis is unavailable the call
    returns True (permit) so auth flows are not blocked by a cache outage.
    """
    try:
        from app.core.redis import get_redis, namespaced_key

        key = namespaced_key("email_rate", str(user_id), token_type, _hour_bucket())
        redis = await get_redis()
        count = await redis.incr(key)
        if count == 1:
            # First increment in this bucket — set TTL so the key expires
            # automatically at the end of the hour window (+ small buffer).
            await redis.expire(key, 3700)
        return count <= _EMAIL_RATE_LIMIT
    except Exception as exc:
        log.warning(
            "email_rate_limit.redis_error",
            user_id=str(user_id),
            token_type=token_type,
            error=str(exc),
        )
        return True  # fail-open


class EmailService:
    """Async wrapper around the SendGrid SDK for transactional emails.

    D4 (Batch 1): _send() never logs to_email — callers pass user_id for
    structured log correlation. Email addresses never appear in log output.
    """

    def __init__(self) -> None:
        self._client: Any = None
        if settings.sendgrid_api_key:
            try:
                from sendgrid import SendGridAPIClient  # type: ignore[import-untyped]

                self._client = SendGridAPIClient(settings.sendgrid_api_key)
            except ImportError:
                log.warning("email_service.sendgrid_not_installed")

    def _is_configured(self) -> bool:
        return self._client is not None

    async def _send(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        """Low-level send via SendGrid; wraps the sync call in a thread.

        Returns True on success, False on any failure. Never raises.
        Logs use user_id (not to_email) — D4 PII discipline.
        """
        if not self._is_configured():
            log.warning(
                "email_service.not_configured",
                user_id=user_id,
                subject=subject,
            )
            return False

        def _do_send() -> bool:
            from sendgrid.helpers.mail import Mail  # type: ignore[import-untyped]

            message = Mail(
                from_email=_get_from_email(),
                to_emails=to_email,
                subject=subject,
                plain_text_content=body_text,
            )
            if body_html:
                message.html_content = body_html
            response = self._client.send(message)
            status_code: int = response.status_code
            return 200 <= status_code < 300

        try:
            success = await asyncio.to_thread(_do_send)
            if success:
                log.info("email_service.sent", user_id=user_id, subject=subject)
            else:
                log.warning(
                    "email_service.send_failed",
                    user_id=user_id,
                    subject=subject,
                )
            return success
        except Exception as exc:
            log.error(
                "email_service.exception",
                user_id=user_id,
                subject=subject,
                error=str(exc),
            )
            return False

    # ── Existing templates (preserved; user_id added where available) ──

    async def send_welcome(self, to_email: str, name: str) -> bool:
        """Send a welcome email with a getting-started guide."""
        subject = "Welcome to PAE Platform — your AI engineering journey starts now"
        body = (
            f"Hi {name},\n\n"
            "Welcome to the Production AI Engineering Platform!\n\n"
            "Here's how to get started:\n"
            "  1. Browse the course catalogue at https://pae.dev/courses\n"
            "  2. Enrol in your first course and start learning\n"
            "  3. Chat with the AI tutor when you have questions\n\n"
            "We're excited to have you on board.\n\n"
            "Happy learning,\n"
            "The PAE Platform Team"
        )
        return await self._send(to_email, subject, body)

    async def send_progress_digest(
        self, to_email: str, name: str, stats: dict[str, Any]
    ) -> bool:
        """Send a weekly progress digest email."""
        lessons_completed: int = stats.get("lessons_completed", 0)
        skills_touched: int = stats.get("skills_touched", 0)
        streak_days: int = stats.get("streak_days", 0)
        top_concept: str = stats.get("top_concept", "N/A")

        subject = "Your weekly PAE Platform growth snapshot"
        body = (
            f"Hi {name},\n\n"
            "Here's what you explored this week:\n\n"
            f"  Lessons completed : {lessons_completed}\n"
            f"  Skills touched    : {skills_touched}\n"
            f"  Consistency       : {streak_days} day(s) in a row\n"
            f"  Focus area        : {top_concept}\n\n"
            "Growth compounds. Keep shipping.\n\n"
            "The PAE Platform Team"
        )
        return await self._send(to_email, subject, body)

    async def send_reengage(
        self, to_email: str, name: str, days_inactive: int
    ) -> bool:
        """Send a re-engagement email triggered by the disrupt_prevention agent."""
        if days_inactive < 7:
            subject = "We miss you — jump back into PAE Platform"
            body = (
                f"Hi {name},\n\n"
                f"It's been {days_inactive} day(s) since your last session.\n"
                "Pick up where you left off — your work is still here.\n\n"
                "https://pae.dev/dashboard\n\n"
                "The PAE Platform Team"
            )
        elif days_inactive < 14:
            subject = "Don't lose your progress — come back to PAE Platform"
            body = (
                f"Hi {name},\n\n"
                f"You've been away for {days_inactive} days. "
                "Your courses are still here and ready for you.\n\n"
                "Log back in and continue building your AI engineering skills:\n"
                "https://pae.dev/dashboard\n\n"
                "The PAE Platform Team"
            )
        else:
            subject = "We'd love to see you back — exclusive resources inside"
            body = (
                f"Hi {name},\n\n"
                f"It's been {days_inactive} days — we hope you're doing well!\n\n"
                "We've added new AI engineering content since you last visited. "
                "Come back and see what's new:\n"
                "https://pae.dev/courses\n\n"
                "The PAE Platform Team"
            )
        return await self._send(to_email, subject, body)

    async def send_weekly_letter(
        self, to_email: str, name: str, week_ending: str, body_markdown: str
    ) -> bool:
        """Send the AI-authored weekly instructor letter (P1-C-4)."""
        subject = f"Your weekly note from PAE — week ending {week_ending}"
        body = (
            f"Hi {name},\n\n"
            f"{body_markdown.strip()}\n\n"
            "— The PAE Platform\n"
            "See the full receipt: https://pae.dev/receipts\n"
        )
        return await self._send(to_email, subject, body)

    async def send_enrollment_confirmation(
        self, to_email: str, name: str, course_name: str
    ) -> bool:
        """Send enrollment confirmation after a successful Stripe payment."""
        subject = f"You're enrolled in '{course_name}' — let's get started!"
        body = (
            f"Hi {name},\n\n"
            f"Your enrollment in **{course_name}** is confirmed.\n\n"
            "You can start learning right away:\n"
            "https://pae.dev/dashboard\n\n"
            "If you have any questions, reply to this email.\n\n"
            "The PAE Platform Team"
        )
        return await self._send(to_email, subject, body)

    # ── Batch 1 auth-flow templates (D-E) ─────────────────────────────

    async def send_password_reset_email(
        self, to_email: str, name: str, token: str, user_id: uuid.UUID
    ) -> bool:
        """Send a password-reset link. Rate-limited per D-F.

        If the rate limit is exceeded, returns False without sending.
        Never raises — caller decides UX response.
        """
        if not await check_email_rate_limit(user_id, "password_reset"):
            log.warning(
                "email_service.rate_limited",
                user_id=str(user_id),
                token_type="password_reset",
            )
            return False

        reset_url = f"{settings.public_base_url}/password-reset/confirm?token={token}"
        subject = "Reset your PAE Platform password"
        body_text = (
            f"Hi {name},\n\n"
            "We received a request to reset your PAE Platform password.\n\n"
            f"Click the link below to set a new password (valid for 1 hour):\n"
            f"{reset_url}\n\n"
            "If you didn't request this, you can safely ignore this email — "
            "your password will not change.\n\n"
            "The PAE Platform Team\n"
            "Questions? Contact support@pae.dev"
        )
        body_html = (
            f"<p>Hi {name},</p>"
            "<p>We received a request to reset your PAE Platform password.</p>"
            f'<p><a href="{reset_url}">Reset my password</a> (valid for 1 hour)</p>'
            "<p>If you didn't request this, you can safely ignore this email — "
            "your password will not change.</p>"
            "<p>The PAE Platform Team<br>"
            "Questions? <a href='mailto:support@pae.dev'>support@pae.dev</a></p>"
        )
        return await self._send(
            to_email, subject, body_text, body_html, user_id=str(user_id)
        )

    async def send_email_verification(
        self, to_email: str, name: str, token: str, user_id: uuid.UUID
    ) -> bool:
        """Send an email verification link. Rate-limited per D-F.

        If the rate limit is exceeded, returns False without sending.
        """
        if not await check_email_rate_limit(user_id, "email_verify"):
            log.warning(
                "email_service.rate_limited",
                user_id=str(user_id),
                token_type="email_verify",
            )
            return False

        verify_url = f"{settings.public_base_url}/verify-email?token={token}"
        subject = "Verify your PAE Platform email address"
        body_text = (
            f"Hi {name},\n\n"
            "Thanks for signing up for PAE Platform!\n\n"
            "Please verify your email address by clicking the link below "
            "(valid for 24 hours):\n"
            f"{verify_url}\n\n"
            "If you didn't create an account, you can safely ignore this email.\n\n"
            "The PAE Platform Team\n"
            "Questions? Contact support@pae.dev"
        )
        body_html = (
            f"<p>Hi {name},</p>"
            "<p>Thanks for signing up for PAE Platform!</p>"
            f'<p><a href="{verify_url}">Verify my email address</a> '
            "(valid for 24 hours)</p>"
            "<p>If you didn't create an account, you can safely ignore this email.</p>"
            "<p>The PAE Platform Team<br>"
            "Questions? <a href='mailto:support@pae.dev'>support@pae.dev</a></p>"
        )
        return await self._send(
            to_email, subject, body_text, body_html, user_id=str(user_id)
        )

    async def send_account_exists(
        self, to_email: str, name: str, user_id: uuid.UUID
    ) -> bool:
        """Notify an already-verified user that someone tried to register with
        their email (D-B existing-verified branch).

        Rate-limited per D-F (uses email_verify bucket to avoid a separate
        bucket for a low-frequency event).
        """
        if not await check_email_rate_limit(user_id, "email_verify"):
            log.warning(
                "email_service.rate_limited",
                user_id=str(user_id),
                token_type="email_verify",
            )
            return False

        reset_url = f"{settings.public_base_url}/password-reset/request"
        subject = "Someone tried to sign up with your PAE Platform email"
        body_text = (
            f"Hi {name},\n\n"
            "Someone attempted to create a PAE Platform account using your "
            "email address. Since you already have an account, no new account "
            "was created.\n\n"
            "If this was you, you can log in directly:\n"
            f"{settings.public_base_url}/login\n\n"
            "If you've forgotten your password, you can reset it here:\n"
            f"{reset_url}\n\n"
            "If this wasn't you, no action is needed — your account is safe.\n\n"
            "The PAE Platform Team\n"
            "Questions? Contact support@pae.dev"
        )
        body_html = (
            f"<p>Hi {name},</p>"
            "<p>Someone attempted to create a PAE Platform account using your "
            "email address. Since you already have an account, no new account "
            "was created.</p>"
            f'<p>If this was you, <a href="{settings.public_base_url}/login">'
            "log in directly</a> or "
            f'<a href="{reset_url}">reset your password</a>.</p>'
            "<p>If this wasn't you, no action is needed — your account is safe.</p>"
            "<p>The PAE Platform Team<br>"
            "Questions? <a href='mailto:support@pae.dev'>support@pae.dev</a></p>"
        )
        return await self._send(
            to_email, subject, body_text, body_html, user_id=str(user_id)
        )
