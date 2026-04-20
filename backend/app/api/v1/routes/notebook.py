"""Notebook endpoints (P3-4) — save / list / delete bookmarked messages.

Mounted under `/api/v1/chat/notebook` so it lives naturally beside the
existing chat surface without needing a separate router prefix.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.notebook_entry import NotebookEntry
from app.models.user import User
from app.schemas.notebook import NotebookEntryCreate, NotebookEntryOut

log = structlog.get_logger()

router = APIRouter(prefix="/chat/notebook", tags=["notebook"])


@router.post(
    "",
    response_model=NotebookEntryOut,
    status_code=status.HTTP_201_CREATED,
)
async def save_to_notebook(
    payload: NotebookEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotebookEntryOut:
    """Save an assistant message to the user's notebook."""
    entry = NotebookEntry(
        user_id=current_user.id,
        message_id=payload.message_id,
        conversation_id=payload.conversation_id,
        content=payload.content,
        title=payload.title,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    log.info(
        "notebook.saved",
        user_id=str(current_user.id),
        entry_id=str(entry.id),
    )
    return NotebookEntryOut(
        id=str(entry.id),
        message_id=entry.message_id,
        conversation_id=entry.conversation_id,
        content=entry.content,
        title=entry.title,
        created_at=entry.created_at,
    )


@router.get("", response_model=list[NotebookEntryOut])
async def list_notebook(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[NotebookEntryOut]:
    """Return all notebook entries for the current user, newest first."""
    result = await db.execute(
        select(NotebookEntry)
        .where(NotebookEntry.user_id == current_user.id)
        .order_by(NotebookEntry.created_at.desc())
    )
    entries = result.scalars().all()
    return [
        NotebookEntryOut(
            id=str(e.id),
            message_id=e.message_id,
            conversation_id=e.conversation_id,
            content=e.content,
            title=e.title,
            created_at=e.created_at,
        )
        for e in entries
    ]


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notebook_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a notebook entry owned by the current user."""
    result = await db.execute(
        delete(NotebookEntry).where(
            NotebookEntry.id == entry_id,
            NotebookEntry.user_id == current_user.id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook entry not found",
        )
    await db.commit()
    log.info(
        "notebook.deleted",
        user_id=str(current_user.id),
        entry_id=str(entry_id),
    )
