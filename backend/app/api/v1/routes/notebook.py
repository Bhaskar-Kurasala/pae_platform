"""Notebook endpoints — save / list / summary / patch / delete / mark-reviewed bookmarked messages.

Mounted under `/api/v1/chat/notebook` beside the existing chat surface.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.notebook_entry import NotebookEntry
from app.models.user import User
from app.schemas.notebook import (
    NotebookEntryCreate,
    NotebookEntryOut,
    NotebookEntryUpdate,
    NotebookSourceCount,
    NotebookSummaryResponse,
    NoteSummarizeRequest,
    NoteSummarizeResponse,
)
from app.services.notebook_service import (
    GraduatedFilter,
    all_tags,
    concept_key_for,
    list_for_user,
    summary_for_user,
)
from app.services.notebook_summarize_service import summarize_for_notebook
from app.services.srs_service import SRSService

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
        tags=list(e.tags or []),
        last_reviewed_at=e.last_reviewed_at,
        graduated_at=e.graduated_at,
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
        user_note=payload.user_note,
        source_type=payload.source_type or "chat",
        topic=payload.topic,
        tags=list(payload.tags or []),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    # Auto-seed an SRS card for this note so the graduation pipeline has a
    # concept to track. Best-effort; never fail the save if SRS upsert errors.
    try:
        # Prefer the title for the prompt (it's typically the topic) and the
        # student's rewritten user_note for the answer — that's the version
        # they'll actually want to recall, vs. the raw assistant wall of text.
        await SRSService(db).upsert_card(
            user_id=current_user.id,
            concept_key=concept_key_for(entry),
            prompt=(entry.title or entry.topic or entry.content)[:512],
            answer=(entry.user_note or entry.content)[:2048],
            hint="Reveal when you can recall the gist in your own words.",
        )
    except Exception as exc:
        log.warning(
            "notebook.srs_seed_failed",
            entry_id=str(entry.id),
            error=str(exc),
        )

    log.info("notebook.saved", user_id=str(current_user.id), entry_id=str(entry.id))
    return _to_out(entry)


@router.post("/summarize", response_model=NoteSummarizeResponse)
async def summarize_for_save(
    payload: NoteSummarizeRequest,
    current_user: User = Depends(get_current_user),
) -> NoteSummarizeResponse:
    """Summarize an assistant reply into a study note + suggested tags.

    Powers the SaveNoteModal preview. Pure read path — does not write a
    notebook row. Result is cached in Redis by `(message_id, content_len)`
    for an hour so re-opening the modal on the same message is free.

    Degrades to a deterministic head-of-text fallback on LLM/parse failure
    so the modal always opens with *something* the student can edit.
    """
    result = await summarize_for_notebook(
        message_id=payload.message_id,
        content=payload.content,
        user_question=payload.user_question,
    )
    log.info(
        "notebook.summarized",
        user_id=str(current_user.id),
        message_id=payload.message_id,
        tags=len(result.tags),
        cached=result.cached,
    )
    return NoteSummarizeResponse(
        summary=result.summary,
        suggested_tags=result.tags,
        cached=result.cached,
    )


@router.get("", response_model=list[NotebookEntryOut])
async def list_notebook(
    source: str | None = Query(default=None, max_length=64),
    graduated: GraduatedFilter = Query(default="all"),
    tag: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[NotebookEntryOut]:
    rows = await list_for_user(
        db,
        user_id=current_user.id,
        source=source,
        graduated=graduated,
        tag=tag,
        limit=limit,
    )
    return [_to_out(e) for e in rows]


@router.get("/summary", response_model=NotebookSummaryResponse)
async def notebook_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotebookSummaryResponse:
    """Aggregate counts for the Notebook ghost card + topbar progress."""
    summary = await summary_for_user(db, user=current_user)
    # Cheap: tags are derived from the entries we already loaded for the
    # graduation summary path. We do a separate small query just for tags
    # because summary_for_user doesn't fetch entry rows.
    rows_q = select(NotebookEntry).where(NotebookEntry.user_id == current_user.id)
    rows = list((await db.execute(rows_q)).scalars().all())
    return NotebookSummaryResponse(
        total=summary.total,
        graduated=summary.graduated,
        in_review=summary.in_review,
        graduation_percentage=summary.graduation_percentage,
        latest_graduated_at=summary.latest_graduated_at,
        by_source=[
            NotebookSourceCount(source=s.source, count=s.count)
            for s in summary.by_source
        ],
        tags=all_tags(rows),
    )


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
    if payload.tags is not None:
        entry.tags = list(payload.tags)

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
