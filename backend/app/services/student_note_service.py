"""Admin student intervention notes (P3 3A-18).

Append-only log of admin observations tied to one student. Kept
separate from the generic notifications table so the admin workflow
(at-risk list → open student panel → write note) doesn't share a row
surface with system-generated alerts.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student_note import StudentNote

log = structlog.get_logger()


async def add_note(
    db: AsyncSession,
    *,
    admin_id: uuid.UUID,
    student_id: uuid.UUID,
    body_md: str,
) -> StudentNote:
    """Persist a new note. Caller is responsible for admin authorization."""
    note = StudentNote(admin_id=admin_id, student_id=student_id, body_md=body_md)
    db.add(note)
    await db.commit()
    await db.refresh(note)
    log.info(
        "admin.student_note_added",
        admin_id=str(admin_id),
        student_id=str(student_id),
        note_id=str(note.id),
    )
    return note


async def list_notes(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    limit: int = 50,
) -> list[StudentNote]:
    """Return notes for a student, newest first."""
    rows = (
        await db.execute(
            select(StudentNote)
            .where(StudentNote.student_id == student_id)
            .order_by(desc(StudentNote.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)
