"""D18 Phase A CP4 — admin-specific fixtures.

Two surfaces:

  * `seed_admin_user_with_login(session, password)` — DB-direct admin
    seed using a real bcrypt hash, so the resulting admin can also
    authenticate via the HTTP login flow. This supersedes the CP3-
    temporary `pages._helpers.login_as_admin` for tests that want
    an admin user fixture that actually works.

  * `seed_admin_with_outreach_history(session, channel_counts)` —
    seeds an admin plus pre-existing outreach_log entries for
    verification tests (admin console "outreach history" panels).

The admin_authenticated_session helper shape mentioned in the CP4
prompt is deferred to a future Playwright-shape composite — at CP4
time the existing `pages._helpers.login_as_admin` does the page-side
token injection given a (email, password) pair from these fixtures,
so the surface that actually matters for Phase B is the seed helper.
The auth-injection wiring will land in CP5/CP6 when the broader
fixture set is in scope; documented in this module's docstring + the
saved D18 prompt.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.hashing import hash_password

from .role_state_fixtures import (
    SeededAdmin,
    seed_admin_user,
    seed_outreach_log_entry,
)


@dataclass
class SeededAdminWithLogin:
    """Admin user + the plaintext password tests can use to log in.

    Returned by seed_admin_user_with_login. Tests should pass `email`
    + `password` into pages._helpers.login_as_admin or directly to
    POST /api/v1/auth/login.
    """

    user_id: uuid.UUID
    email: str
    password: str
    full_name: str
    role: str = "admin"


async def seed_admin_user_with_login(
    session: AsyncSession,
    *,
    password: str = "AdminCP4Pass123!",
    email_suffix: str | None = None,
    full_name: str = "D18 CP4 Admin (login-capable)",
) -> SeededAdminWithLogin:
    """Seed an admin user whose hashed_password matches `password`.

    Unlike `seed_admin_user`, this version pays the bcrypt-hash cost
    (~100ms) so the resulting user can authenticate via HTTP. Use
    this when the test needs the admin to log in; use the cheaper
    `seed_admin_user` when only a DB row is needed (e.g., admin_id
    references for student_notes / outreach_log).
    """
    seeded = await seed_admin_user(
        session,
        email_suffix=email_suffix,
        full_name=full_name,
        hashed_password=hash_password(password),
    )
    return SeededAdminWithLogin(
        user_id=seeded.user_id,
        email=seeded.email,
        password=password,
        full_name=seeded.full_name,
    )


@dataclass
class SeededAdminWithOutreach:
    """Admin user + the outreach_log row ids seeded against a target student.

    The admin is the trigger (triggered_by='admin', triggered_by_user_id=admin.user_id).
    """

    admin: SeededAdmin
    target_student_id: uuid.UUID
    outreach_row_ids: list[uuid.UUID] = field(default_factory=list)
    channel_counts: dict[str, int] = field(default_factory=dict)


async def seed_admin_with_outreach_history(
    session: AsyncSession,
    *,
    target_student_id: uuid.UUID,
    channel_counts: dict[str, int],
    email_suffix: str | None = None,
) -> SeededAdminWithOutreach:
    """Seed an admin user + outreach_log rows for verification tests.

    Example:
        await seed_admin_with_outreach_history(
            session,
            target_student_id=student.user_id,
            channel_counts={"email": 3, "whatsapp": 2, "in_app": 1},
        )

    Creates 3 + 2 + 1 = 6 outreach_log rows targeting `target_student_id`
    with `triggered_by='admin'` and `triggered_by_user_id=admin.user_id`.
    Each row is sent_hours_ago staggered (1h, 2h, 3h, ...) so timeline
    queries return them in deterministic order.
    """
    admin = await seed_admin_user(session, email_suffix=email_suffix)
    rids: list[uuid.UUID] = []
    hour_offset = 1
    for channel, count in channel_counts.items():
        for _ in range(count):
            rid = await seed_outreach_log_entry(
                session,
                student_id=target_student_id,
                channel=channel,
                triggered_by="admin",
                triggered_by_user_id=admin.user_id,
                sent_hours_ago=hour_offset,
                body_preview=f"CP4 fixture {channel} #{hour_offset}",
            )
            rids.append(rid)
            hour_offset += 1
    return SeededAdminWithOutreach(
        admin=admin,
        target_student_id=target_student_id,
        outreach_row_ids=rids,
        channel_counts=dict(channel_counts),
    )


__all__ = [
    "SeededAdminWithLogin",
    "SeededAdminWithOutreach",
    "seed_admin_user_with_login",
    "seed_admin_with_outreach_history",
]
