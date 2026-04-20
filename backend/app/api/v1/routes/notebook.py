"""Notebook endpoints — save / list / patch / delete / mark-reviewed bookmarked messages.

Mounted under `/api/v1/chat/notebook` beside the existing chat surface.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.notebook_entry import NotebookEntry
from app.models.user import User
from app.schemas.notebook import NotebookEntryCreate, NotebookEntryOut, NotebookEntryUpdate

log = structlog.get_logger()

router = APIRouter(prefix="/chat/notebook", tags=["notebook"])


def _to_out(e: NotebookEntry) -> NotebookEntryOut:
    return NotebookEntryOut(
        id=str(e.id),
        message_id=e.message_id,
        conversation_id=e.conversation_id,
        content=e.content,
        title=e.title,
        user_note=e.user_note,
        source_type=e.source_type,
        topic=e.topic,
        last_reviewed_at=e.last_reviewed_at,
        created_at=e.created_at,
    )


@router.post("", response_model=NotebookEntryOut, status_code=status.HTTP_201_CREATED)
async def save_to_notebook(
    payload: NotebookEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotebookEntryOut:
    entry = NotebookEntry(
        user_id=current_user.id,
        message_id=payload.message_id,
        conversation_id=payload.conversation_id,
        content=payload.content,
        title=payload.title,
        source_type=payload.source_type or "chat",
        topic=payload.topic,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    log.info("notebook.saved", user_id=str(current_user.id), entry_id=str(entry.id))
    return _to_out(entry)


@router.get("", response_model=list[NotebookEntryOut])
async def list_notebook(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[NotebookEntryOut]:
    result = await db.execute(
        select(NotebookEntry)
        .where(NotebookEntry.user_id == current_user.id)
        .order_by(NotebookEntry.created_at.desc())
    )
    return [_to_out(e) for e in result.scalars().all()]


@router.patch("/{entry_id}", response_model=NotebookEntryOut)
async def update_notebook_entry(
    entry_id: uuid.UUID,
    payload: NotebookEntryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotebookEntryOut:
    """Inline-edit: student annotation, title, or topic."""
    result = await db.execute(
        select(NotebookEntry).where(
            NotebookEntry.id == entry_id,
            NotebookEntry.user_id == current_user.id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Notebook entry not found")

    if payload.user_note is not None:
        entry.user_note = payload.user_note
    if payload.title is not None:
        entry.title = payload.title
    if payload.topic is not None:
        entry.topic = payload.topic

    await db.commit()
    await db.refresh(entry)
    log.info("notebook.updated", entry_id=str(entry_id))
    return _to_out(entry)


@router.post("/{entry_id}/review", response_model=NotebookEntryOut)
async def mark_reviewed(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotebookEntryOut:
    """Stamp last_reviewed_at = now() for spaced-review tracking."""
    result = await db.execute(
        select(NotebookEntry).where(
            NotebookEntry.id == entry_id,
            NotebookEntry.user_id == current_user.id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Notebook entry not found")

    entry.last_reviewed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(entry)
    log.info("notebook.reviewed", entry_id=str(entry_id))
    return _to_out(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notebook_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(
        delete(NotebookEntry).where(
            NotebookEntry.id == entry_id,
            NotebookEntry.user_id == current_user.id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Notebook entry not found")
    await db.commit()
    log.info("notebook.deleted", user_id=str(current_user.id), entry_id=str(entry_id))
