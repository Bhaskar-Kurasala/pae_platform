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


# P-Bugfix1 (2026-04-28): on the Today warm-up card, SRS prompts/answers
# render as plain strings inside a small tile. When auto-seeding a card
# from a notebook entry that has no `user_note`, dumping raw markdown
# (code fences, bold markers, list bullets, multi-paragraph blocks) makes
# the tile look broken — text overflows, formatting markers leak through.
# These two helpers normalize the seeded text:
#   - SRS_PROMPT_MAX (90)  — front of the card; one short question/title.
#   - SRS_ANSWER_MAX (240) — back of the card; one short paragraph.
# 240 chars matches the FlashCard backend cap (BACK_MAX = 280) minus
# breathing room and produces ~3 readable lines on the warm-up tile.

SRS_PROMPT_MAX = 90
SRS_ANSWER_MAX = 240


def _strip_markdown_to_text(s: str) -> str:
    """Best-effort markdown → plain text. Removes the formatting that makes
    SRS cards look "creepy" on the Today tile while preserving the actual
    sentence content the student wanted to remember.

    What we strip (in order, because some patterns nest):
      1. Fenced code blocks (```...```), entirely.
      2. Inline backticks around code, leaving the inner text.
      3. Bold/italic markers (**, __, *, _) without dropping the words.
      4. Markdown list bullets (-, *, +, 1.) at line starts.
      5. Heading markers (#, ##, ###) at line starts.
      6. Blockquote markers (>) at line starts.
      7. Collapse runs of blank lines, trim outer whitespace.

    We deliberately DON'T pull a markdown lib for this — the input ceiling
    is 240 chars and these regex passes have been measured at ~30µs.
    """
    import re

    # 1. Fenced code blocks vanish completely — they're rarely the takeaway.
    s = re.sub(r"```[\s\S]*?```", " ", s)
    # 2. Inline code `like this` → `like this`.
    s = re.sub(r"`([^`\n]+)`", r"\1", s)
    # 3. Bold/italic — strip markers, keep the words.
    s = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", s)
    s = re.sub(r"__([^_\n]+)__", r"\1", s)
    s = re.sub(r"(?<![*_])\*([^*\n]+)\*(?!\*)", r"\1", s)
    s = re.sub(r"(?<![*_])_([^_\n]+)_(?!_)", r"\1", s)
    # 4. List bullets / numbered list markers at line starts.
    s = re.sub(r"(?m)^\s*(?:[-*+]|\d+\.)\s+", "", s)
    # 5. Heading markers.
    s = re.sub(r"(?m)^\s*#{1,6}\s+", "", s)
    # 6. Blockquote markers.
    s = re.sub(r"(?m)^\s*>\s?", "", s)
    # 7. Collapse blank-line runs to a single space, then trim.
    s = re.sub(r"\n{2,}", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _truncate_with_ellipsis(s: str, limit: int) -> str:
    """Cut at the last word boundary before `limit` and append a single
    ellipsis character so the student sees there's more behind the card."""
    if len(s) <= limit:
        return s
    cut = s[:limit].rstrip()
    space = cut.rfind(" ")
    if space > limit * 0.6:  # avoid producing a 3-char fragment
        cut = cut[:space]
    return cut.rstrip(",;: ") + "…"


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
    # PR2/B6.1 — Redis idempotency. Two clicks of "Save" within 60s on
    # the same payload produce the same NotebookEntry, not two. The hash
    # covers the canonicalized payload, so saving the SAME message with
    # an EDITED user_note 10 minutes later still creates a fresh entry
    # (intentional — that's a real second action). Practice/Studio saves
    # already mint a unique message_id per click, but a duplicate POST
    # caused by network jitter would still produce two rows; this lock
    # closes that hole too.
    from app.services.idempotency import (
        DEFAULT_TTL_SECONDS,
        fetch_or_lock,
        make_request_hash,
        store_result,
    )

    request_hash = make_request_hash(
        user_id=str(current_user.id),
        payload={
            "message_id": payload.message_id,
            "conversation_id": payload.conversation_id,
            "content": payload.content,
            "title": payload.title,
            "user_note": payload.user_note,
            "source_type": payload.source_type or "chat",
            "topic": payload.topic,
            "tags": sorted(payload.tags or []),
        },
    )
    replayed, prior = await fetch_or_lock(
        prefix="notebook_save", request_hash=request_hash
    )
    if replayed and prior is not None:
        log.info(
            "notebook.saved_idempotent_replay",
            user_id=str(current_user.id),
            entry_id=prior.get("id"),
        )
        return NotebookEntryOut.model_validate(prior)

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
        # P-Bugfix1 — normalize prompt + answer so the Today warm-up tile
        # doesn't render raw markdown / 2 KB of text. The user_note is
        # already short and clean (student-typed); sanitize the markdown
        # path that fires when no note was provided.
        raw_prompt = entry.title or entry.topic or entry.content
        raw_answer = entry.user_note or entry.content
        clean_prompt = _truncate_with_ellipsis(
            _strip_markdown_to_text(raw_prompt), SRS_PROMPT_MAX,
        )
        clean_answer = _truncate_with_ellipsis(
            _strip_markdown_to_text(raw_answer), SRS_ANSWER_MAX,
        )
        await SRSService(db).upsert_card(
            user_id=current_user.id,
            concept_key=concept_key_for(entry),
            prompt=clean_prompt,
            answer=clean_answer,
            hint="Reveal when you can recall the gist in your own words.",
        )
    except Exception as exc:
        log.warning(
            "notebook.srs_seed_failed",
            entry_id=str(entry.id),
            error=str(exc),
        )

    log.info("notebook.saved", user_id=str(current_user.id), entry_id=str(entry.id))
    out = _to_out(entry)
    # PR2/B6.1 — populate the idempotency slot so a duplicate POST
    # within the TTL replays this exact response instead of writing a
    # second row. Best-effort: store_result swallows Redis failures.
    await store_result(
        prefix="notebook_save",
        request_hash=request_hash,
        result=out.model_dump(mode="json"),
        ttl=DEFAULT_TTL_SECONDS,
    )
    return out


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
