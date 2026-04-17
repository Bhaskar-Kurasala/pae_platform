# SendGrid email service — welcome, progress digest, re-engagement, enrollment confirmation
import asyncio
from typing import Any

import structlog

from app.core.config import settings

log = structlog.get_logger()

_FROM_EMAIL_DEFAULT = "noreply@pae.dev"


def _get_from_email() -> str:
    return settings.sendgrid_from_email or _FROM_EMAIL_DEFAULT


class EmailService:
    """Async wrapper around the SendGrid SDK for transactional emails."""

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

    async def _send(self, to_email: str, subject: str, body_text: str) -> bool:
        """Low-level send via SendGrid; wraps the sync call in a thread.

        Returns True on success, False on any failure.  Never raises.
        """
        if not self._is_configured():
            log.warning(
                "email_service.not_configured",
                to_email=to_email,
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
            response = self._client.send(message)
            status_code: int = response.status_code
            return 200 <= status_code < 300

        try:
            success = await asyncio.to_thread(_do_send)
            if success:
                log.info("email_service.sent", to_email=to_email, subject=subject)
            else:
                log.warning(
                    "email_service.send_failed",
                    to_email=to_email,
                    subject=subject,
                )
            return success
        except Exception as exc:
            log.error(
                "email_service.exception",
                to_email=to_email,
                subject=subject,
                error=str(exc),
            )
            return False

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
        """Send a weekly progress digest email.

        Args:
            stats: dict with keys ``lessons_completed``, ``streak_days``,
                   ``top_concept``.
        """
        lessons_completed: int = stats.get("lessons_completed", 0)
        streak_days: int = stats.get("streak_days", 0)
        top_concept: str = stats.get("top_concept", "N/A")

        subject = "Your weekly PAE Platform progress digest"
        body = (
            f"Hi {name},\n\n"
            "Here's your learning summary for the past week:\n\n"
            f"  Lessons completed : {lessons_completed}\n"
            f"  Study streak      : {streak_days} day(s)\n"
            f"  Top concept       : {top_concept}\n\n"
            "Keep up the great work!\n\n"
            "The PAE Platform Team"
        )
        return await self._send(to_email, subject, body)

    async def send_reengage(
        self, to_email: str, name: str, days_inactive: int
    ) -> bool:
        """Send a re-engagement email triggered by the disrupt_prevention agent.

        Message copy is tailored to the inactivity bucket:
        - 3–7 days  : gentle nudge
        - 7–14 days : stronger reminder
        - 14+ days  : win-back offer
        """
        if days_inactive < 7:
            subject = "We miss you — jump back into PAE Platform"
            body = (
                f"Hi {name},\n\n"
                f"It's been {days_inactive} day(s) since your last session.\n"
                "Your learning streak is waiting — pick up where you left off!\n\n"
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
