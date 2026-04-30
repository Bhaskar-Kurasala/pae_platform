"""F8 — Student message service (in-app direct messaging).

Two-party threads (admin + one student). The service:
  - creates messages
  - lists threads + per-thread messages
  - tracks read status
  - reports unread counts (used by the banner poller)

When admin sends, ALSO writes to outreach_log via F3 so the audit
trail covers in-app channel as well as email/WA.

When student replies, the service finds the most recent admin-manual
in-app outreach for that user and flips its replied_at — closing the
loop on F3's "did the user respond?" tracking.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outreach_log import OutreachLog
from app.models.student_message import StudentMessage
from app.services import outreach_service

log = structlog.get_logger()

MAX_BODY_LEN = 5000


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def create_message(
    db: AsyncSession,
    *,
    thread_id: uuid.UUID | None,
    student_id: uuid.UUID,
    sender_role: str,  # 'admin' | 'student'
    sender_id: uuid.UUID,
    body: str,
) -> StudentMessage:
    """Create one message. If thread_id is None, mint a new thread.

    Side effects:
      - admin-sent messages also write an outreach_log row (channel='in_app',
        triggered_by='admin_manual') for the F3 audit trail
      - student-sent messages flip the most recent admin-initiated
        outreach_log row's replied_at, IF one exists with replied_at IS NULL
    """
    if sender_role not in ("admin", "student"):
        raise ValueError(f"sender_role must be 'admin' or 'student', got {sender_role!r}")
    body = (body or "").strip()
    if not body:
        raise ValueError("message body must not be empty")
    if len(body) > MAX_BODY_LEN:
        body = body[:MAX_BODY_LEN]

    new_thread = thread_id or uuid.uuid4()
    msg = StudentMessage(
        id=uuid.uuid4(),
        thread_id=new_thread,
        student_id=student_id,
        sender_role=sender_role,
        sender_id=sender_id,
        body=body,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    if sender_role == "admin":
        await _record_admin_outreach(
            db,
            student_id=student_id,
            admin_id=sender_id,
            body_preview=body[:200],
        )
    else:
        await _flip_replied_at(db, student_id=student_id)

    log.info(
        "student_message.created",
        thread_id=str(new_thread),
        student_id=str(student_id),
        sender_role=sender_role,
    )
    return msg


async def _record_admin_outreach(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    admin_id: uuid.UUID,
    body_preview: str,
) -> None:
    """Mirror an admin-sent in-app message into outreach_log so the
    F3 audit trail covers the in_app channel."""
    await outreach_service.record(
        db,
        user_id=student_id,
        channel="in_app",
        template_key=None,  # ad-hoc, not from a template
        slip_type=None,
        triggered_by="admin_manual",
        triggered_by_user_id=admin_id,
        body_preview=body_preview,
        status="sent",
    )


async def _flip_replied_at(db: AsyncSession, *, student_id: uuid.UUID) -> None:
    """When the student replies in-app, find the most recent
    admin-initiated outreach to them (any channel) that doesn't have
    a replied_at yet, and stamp it. That closes the F3 loop on 'did
    the user respond?'

    Heuristic: most recent triggered_by='admin_manual' OR
    'system_nightly' row with replied_at IS NULL. We don't filter
    by channel because a student might reply in-app to an email
    we sent — same conversation, different channel."""
    q = await db.execute(
        select(OutreachLog)
        .where(
            OutreachLog.user_id == student_id,
            OutreachLog.replied_at.is_(None),
            OutreachLog.triggered_by.in_(["admin_manual", "system_nightly"]),
        )
        .order_by(desc(OutreachLog.sent_at))
        .limit(1)
    )
    row = q.scalar_one_or_none()
    if row is None:
        return
    row.replied_at = _now()
    await db.commit()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def list_thread(
    db: AsyncSession, *, thread_id: uuid.UUID, limit: int = 50
) -> list[StudentMessage]:
    """All messages in a thread, oldest first (chat order)."""
    q = await db.execute(
        select(StudentMessage)
        .where(
            StudentMessage.thread_id == thread_id,
            StudentMessage.deleted_at.is_(None),
        )
        .order_by(StudentMessage.created_at.asc())
        .limit(limit)
    )
    return list(q.scalars().all())


async def list_for_student(
    db: AsyncSession, *, student_id: uuid.UUID, limit: int = 50
) -> list[StudentMessage]:
    """All messages for one student, newest first. Powers the per-
    student admin view + the student inbox feed."""
    q = await db.execute(
        select(StudentMessage)
        .where(
            StudentMessage.student_id == student_id,
            StudentMessage.deleted_at.is_(None),
        )
        .order_by(desc(StudentMessage.created_at))
        .limit(limit)
    )
    return list(q.scalars().all())


async def list_threads_for_student(
    db: AsyncSession, *, student_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Return one row per thread with the latest message preview.
    Used by the student-side `/messages` inbox.

    Implementation: pull every message for the student, group in
    Python by thread_id (UUIDs are uniformly distributed; window
    functions in SQL would be faster at 10k+ messages but we're not
    there yet)."""
    msgs = await list_for_student(db, student_id=student_id, limit=500)
    threads: dict[uuid.UUID, dict[str, Any]] = {}
    for msg in msgs:
        existing = threads.get(msg.thread_id)
        if existing is None:
            threads[msg.thread_id] = {
                "thread_id": msg.thread_id,
                "last_message_preview": msg.body[:200],
                "last_message_at": msg.created_at,
                "last_sender_role": msg.sender_role,
                "unread_count": 0,
            }
            existing = threads[msg.thread_id]
        # Unread = an admin message the student hasn't read yet.
        if msg.sender_role == "admin" and msg.read_at is None:
            existing["unread_count"] = existing["unread_count"] + 1
    # Sort newest-thread-first by last_message_at.
    return sorted(
        threads.values(),
        key=lambda t: t["last_message_at"],
        reverse=True,
    )


async def mark_thread_read(
    db: AsyncSession, *, thread_id: uuid.UUID, reader_user_id: uuid.UUID
) -> int:
    """Mark every message in a thread that the reader didn't author
    as read. Returns count flipped.

    Symmetric: works whether reader_user_id is the student (marks
    admin messages read) or an admin (marks student messages read)."""
    q = await db.execute(
        select(StudentMessage).where(
            StudentMessage.thread_id == thread_id,
            StudentMessage.read_at.is_(None),
            StudentMessage.sender_id != reader_user_id,
            StudentMessage.deleted_at.is_(None),
        )
    )
    rows = list(q.scalars().all())
    now = _now()
    for row in rows:
        row.read_at = now
    await db.commit()
    return len(rows)


async def unread_count_for_student(
    db: AsyncSession, *, student_id: uuid.UUID
) -> int:
    """Count of admin-sent messages the student hasn't read yet.
    Polled every 60s by the banner; keep it index-only."""
    q = await db.execute(
        select(func.count(StudentMessage.id)).where(
            StudentMessage.student_id == student_id,
            StudentMessage.sender_role == "admin",
            StudentMessage.read_at.is_(None),
            StudentMessage.deleted_at.is_(None),
        )
    )
    return q.scalar() or 0


async def get_or_create_admin_thread_for_student(
    db: AsyncSession, *, student_id: uuid.UUID
) -> uuid.UUID:
    """Return the most recent thread_id between admin and this student.
    If no thread exists yet, mint a new one (UUID4 — the first send
    will create the actual row).

    Convenience for the admin-compose UI: 'open Bhaskar's thread with
    Aanya'. Multiple historical threads can exist; we return the most
    recent so admin lands in the active conversation."""
    q = await db.execute(
        select(StudentMessage.thread_id)
        .where(
            StudentMessage.student_id == student_id,
            StudentMessage.deleted_at.is_(None),
        )
        .order_by(desc(StudentMessage.created_at))
        .limit(1)
    )
    existing = q.scalar_one_or_none()
    return existing or uuid.uuid4()
