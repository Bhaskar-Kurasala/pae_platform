#!/usr/bin/env python
"""Smoke-send script — Batch 1 / D-E founder verification step.

Sends each of the three new auth-flow email templates to TEST_EMAIL_RECIPIENT
so the founder can visually verify:
  1. SendGrid delivers to inbox (not spam)
  2. Plain-text and HTML versions render correctly
  3. Links point to PUBLIC_BASE_URL (not localhost)

═══════════════════════════════════════════════════════
FOUNDER EXECUTION STEPS
═══════════════════════════════════════════════════════

Prerequisites:
  1. SENDGRID_API_KEY must be set in your environment (Fly secrets or .env).
     Get the key from your SendGrid dashboard → API Keys.
  2. TEST_EMAIL_RECIPIENT must be set to a real inbox you control.
  3. PUBLIC_BASE_URL should be set to your production URL in production,
     or left as http://localhost:3002 for a local link-shape check.

Run from the backend directory:

  # Option A — via uv (local dev, uses .env file):
  cd backend
  uv run python scripts/send_test_email.py

  # Option B — inside Docker:
  docker compose exec backend python scripts/send_test_email.py

Expected output on success:
  [OK] send_password_reset_email  → check inbox
  [OK] send_email_verification    → check inbox
  [OK] send_account_exists        → check inbox

If you see [SKIP]: SENDGRID_API_KEY is not set or TEST_EMAIL_RECIPIENT is empty.
If you see [FAIL]: SendGrid returned a non-2xx status — check your API key and
sender domain configuration.

═══════════════════════════════════════════════════════
PRODUCTION VERIFICATION CHECKLIST (founder sign-off)
═══════════════════════════════════════════════════════

After running against production:
  □ All three emails arrive in inbox (not spam) within 60 seconds
  □ "Reset my password" link points to https://pae.dev/password-reset/confirm?token=...
  □ "Verify my email address" link points to https://pae.dev/verify-email?token=...
  □ "Log in directly" link in account_exists email points to https://pae.dev/login
  □ From address is noreply@pae.dev (or configured SENDGRID_FROM_EMAIL)
  □ No HTML rendering issues in Gmail / Outlook / Apple Mail spot-check

Mark G1 (SendGrid wired end-to-end) ✅ in cohort-1-launch-readiness-master-list.md
after sign-off.
═══════════════════════════════════════════════════════
"""
import asyncio
import sys
import uuid


async def _run() -> None:
    # Import inside async so Settings loads with .env already parsed.
    import os
    import sys

    # Ensure the backend package is importable when run from the backend dir.
    sys.path.insert(0, ".")

    from app.core.config import settings
    from app.services.email_service import EmailService

    recipient = settings.test_email_recipient
    if not recipient:
        print(
            "[SKIP] TEST_EMAIL_RECIPIENT is not set in .env.\n"
            "       Set it to a real inbox address and re-run."
        )
        return

    if not settings.sendgrid_api_key:
        print(
            "[SKIP] SENDGRID_API_KEY is not set in .env.\n"
            "       This is Track 1 founder work — set the key from your\n"
            "       SendGrid dashboard and re-run."
        )
        return

    svc = EmailService()
    # Use a stable fake token and user_id so link shape is verifiable.
    fake_token = "SMOKETEST_TOKEN_replace_with_real_token_in_production"
    fake_user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    fake_name = "Founder (smoke test)"

    print(f"\nSmoke-sending to: {recipient}")
    print(f"PUBLIC_BASE_URL:  {settings.public_base_url}\n")

    tests = [
        (
            "send_password_reset_email",
            svc.send_password_reset_email(recipient, fake_name, fake_token, fake_user_id),
        ),
        (
            "send_email_verification",
            svc.send_email_verification(recipient, fake_name, fake_token, fake_user_id),
        ),
        (
            "send_account_exists",
            svc.send_account_exists(recipient, fake_name, fake_user_id),
        ),
    ]

    all_ok = True
    for name, coro in tests:
        ok = await coro
        status = "[OK]  " if ok else "[FAIL]"
        print(f"{status} {name}")
        if not ok:
            all_ok = False

    if all_ok:
        print(
            "\nAll sends succeeded. Check inbox for delivery + visual QA.\n"
            "See FOUNDER EXECUTION STEPS in this file for the sign-off checklist."
        )
    else:
        print(
            "\nOne or more sends failed. Check SENDGRID_API_KEY, sender domain,\n"
            "and SendGrid activity feed at https://app.sendgrid.com/email_activity"
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_run())
