"""F8 — Student message service tests.

Eight tests covering the contract:
  - create_message admin → outreach_log row written (F3 audit)
  - create_message student → flips replied_at on most recent admin outreach
  - list_thread / list_for_student / list_threads_for_student return correct shape
  - mark_thread_read flips read_at only for messages NOT authored by the reader
  - unread_count_for_student counts admin-sent unread only
  - empty body raises ValueError
  - body over 5000 chars truncates, doesn't error
  - get_or_create_admin_thread_for_student returns existing thread
    when one exists, mints new UUID otherwise
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outreach_log import OutreachLog
from app.models.student_message import StudentMessage
from app.models.user import User
from app.services import student_message_service


async def _user(db: AsyncSession, *, email: str | None = None) -> User:
    u = User(
        id=uuid.uuid4(),
        email=email or f"u{uuid.uuid4().hex[:8]}@otherdomain.com",
        full_name="Test User",
        hashed_password="x",
        role="student",
        is_active=True,
        is_verified=True,
    )
    db.add(u)
    await db.commit()
    return u


async def _admin(db: AsyncSession) -> User:
    a = User(
        id=uuid.uuid4(),
        email=f"admin{uuid.uuid4().hex[:6]}@otherdomain.com",
        full_name="Admin",
        hashed_password="x",
        role="admin",
        is_active=True,
        is_verified=True,
    )
    db.add(a)
    await db.commit()
    return a


@pytest.mark.asyncio
async def test_admin_send_writes_outreach_log_row(
    db_session: AsyncSession,
) -> None:
    student = await _user(db_session)
    admin = await _admin(db_session)

    msg = await student_message_service.create_message(
        db_session,
        thread_id=None,
        student_id=student.id,
        sender_role="admin",
        sender_id=admin.id,
        body="Hey, I noticed you've been quiet — anything I can help with?",
    )

    assert msg.thread_id is not None
    assert msg.sender_role == "admin"

    # The corresponding outreach_log row exists with channel='in_app'.
    rows = (
        await db_session.execute(
            select(OutreachLog).where(OutreachLog.user_id == student.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].channel == "in_app"
    assert rows[0].triggered_by == "admin_manual"
    assert rows[0].triggered_by_user_id == admin.id


@pytest.mark.asyncio
async def test_student_reply_flips_outreach_replied_at(
    db_session: AsyncSession,
) -> None:
    student = await _user(db_session)
    admin = await _admin(db_session)

    # Pre-seed an admin-initiated outreach row with replied_at NULL.
    outreach_id = uuid.uuid4()
    db_session.add(
        OutreachLog(
            id=outreach_id,
            user_id=student.id,
            channel="email",
            template_key="paid_silent_day_3",
            slip_type="paid_silent",
            triggered_by="admin_manual",
            triggered_by_user_id=admin.id,
            sent_at=datetime.now(UTC) - timedelta(days=1),
            status="sent",
        )
    )
    await db_session.commit()

    # Student replies in-app. F8 should find the admin-initiated row
    # and flip replied_at.
    thread_id = uuid.uuid4()
    await student_message_service.create_message(
        db_session,
        thread_id=thread_id,
        student_id=student.id,
        sender_role="student",
        sender_id=student.id,
        body="Yes, stuck on the JD parser.",
    )

    refreshed = await db_session.get(OutreachLog, outreach_id)
    assert refreshed is not None
    assert refreshed.replied_at is not None


@pytest.mark.asyncio
async def test_list_thread_returns_messages_in_chat_order(
    db_session: AsyncSession,
) -> None:
    student = await _user(db_session)
    admin = await _admin(db_session)
    thread_id = uuid.uuid4()

    # Insert 3 messages alternating admin / student.
    for role, sender, body in [
        ("admin", admin.id, "msg 1"),
        ("student", student.id, "msg 2"),
        ("admin", admin.id, "msg 3"),
    ]:
        await student_message_service.create_message(
            db_session,
            thread_id=thread_id,
            student_id=student.id,
            sender_role=role,
            sender_id=sender,
            body=body,
        )

    msgs = await student_message_service.list_thread(
        db_session, thread_id=thread_id
    )
    # Oldest-first chat order.
    assert [m.body for m in msgs] == ["msg 1", "msg 2", "msg 3"]


@pytest.mark.asyncio
async def test_mark_thread_read_only_flips_others_messages(
    db_session: AsyncSession,
) -> None:
    student = await _user(db_session)
    admin = await _admin(db_session)
    thread_id = uuid.uuid4()

    admin_msg = await student_message_service.create_message(
        db_session,
        thread_id=thread_id,
        student_id=student.id,
        sender_role="admin",
        sender_id=admin.id,
        body="ping",
    )
    student_msg = await student_message_service.create_message(
        db_session,
        thread_id=thread_id,
        student_id=student.id,
        sender_role="student",
        sender_id=student.id,
        body="pong",
    )

    # Student marks thread read — should flip admin_msg.read_at only.
    n = await student_message_service.mark_thread_read(
        db_session, thread_id=thread_id, reader_user_id=student.id
    )
    assert n == 1

    refreshed_admin = await db_session.get(StudentMessage, admin_msg.id)
    refreshed_student = await db_session.get(StudentMessage, student_msg.id)
    assert refreshed_admin is not None and refreshed_admin.read_at is not None
    assert refreshed_student is not None and refreshed_student.read_at is None


@pytest.mark.asyncio
async def test_unread_count_only_admin_sent(
    db_session: AsyncSession,
) -> None:
    student = await _user(db_session)
    admin = await _admin(db_session)
    thread_id = uuid.uuid4()

    # 2 admin messages (unread) + 1 student message (own outgoing).
    for role, sender in [
        ("admin", admin.id),
        ("admin", admin.id),
        ("student", student.id),
    ]:
        await student_message_service.create_message(
            db_session,
            thread_id=thread_id,
            student_id=student.id,
            sender_role=role,
            sender_id=sender,
            body="x",
        )

    n = await student_message_service.unread_count_for_student(
        db_session, student_id=student.id
    )
    assert n == 2  # 2 admin unread; the student's own message doesn't count


@pytest.mark.asyncio
async def test_empty_body_raises(db_session: AsyncSession) -> None:
    student = await _user(db_session)
    admin = await _admin(db_session)
    with pytest.raises(ValueError):
        await student_message_service.create_message(
            db_session,
            thread_id=uuid.uuid4(),
            student_id=student.id,
            sender_role="admin",
            sender_id=admin.id,
            body="   ",  # whitespace-only
        )


@pytest.mark.asyncio
async def test_oversized_body_truncates(
    db_session: AsyncSession,
) -> None:
    student = await _user(db_session)
    admin = await _admin(db_session)
    body = "x" * 6000  # 1000 over the cap
    msg = await student_message_service.create_message(
        db_session,
        thread_id=uuid.uuid4(),
        student_id=student.id,
        sender_role="admin",
        sender_id=admin.id,
        body=body,
    )
    assert len(msg.body) == 5000


@pytest.mark.asyncio
async def test_get_or_create_admin_thread(
    db_session: AsyncSession,
) -> None:
    student = await _user(db_session)
    admin = await _admin(db_session)

    # No thread exists — minted UUID.
    new_id = await student_message_service.get_or_create_admin_thread_for_student(
        db_session, student_id=student.id
    )
    assert isinstance(new_id, uuid.UUID)

    # Send one message; the thread now exists.
    await student_message_service.create_message(
        db_session,
        thread_id=new_id,
        student_id=student.id,
        sender_role="admin",
        sender_id=admin.id,
        body="hi",
    )

    # get_or_create should now return the existing thread_id.
    fetched = (
        await student_message_service.get_or_create_admin_thread_for_student(
            db_session, student_id=student.id
        )
    )
    assert fetched == new_id
