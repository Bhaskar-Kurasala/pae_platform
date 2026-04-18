"""Question wall (P3 3B #102).

Per-lesson Q&A thread. Students post questions or reply to existing
ones; upvote / flag counts are denormalized onto `question_posts` for
cheap sorting, with per-user rows in `question_votes` to dedup.

Pure helpers (normalize/rank) on top, async loaders+mutators below.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question_post import QuestionPost, QuestionVote

_MAX_BODY_LEN = 4000
_VALID_VOTE_KINDS = frozenset({"upvote", "flag"})
_FLAG_HIDE_THRESHOLD = 3


def normalize_body(raw: str) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        raise ValueError("body cannot be empty")
    return cleaned[:_MAX_BODY_LEN]


def normalize_vote_kind(raw: str) -> str:
    cleaned = (raw or "").strip().lower()
    if cleaned not in _VALID_VOTE_KINDS:
        raise ValueError(
            f"vote kind must be one of {sorted(_VALID_VOTE_KINDS)}"
        )
    return cleaned


def should_hide(flag_count: int, *, threshold: int = _FLAG_HIDE_THRESHOLD) -> bool:
    return flag_count >= threshold


def rank_posts(posts: Sequence[QuestionPost]) -> list[QuestionPost]:
    """Sort by upvotes desc, created_at asc — ties go to earliest."""
    return sorted(
        posts,
        key=lambda p: (-p.upvote_count, p.created_at),
    )


def filter_visible(posts: Iterable[QuestionPost]) -> list[QuestionPost]:
    """Drop soft-deleted and flag-hidden posts."""
    return [
        p
        for p in posts
        if not p.is_deleted and not should_hide(p.flag_count)
    ]


async def create_post(
    db: AsyncSession,
    *,
    lesson_id: UUID,
    author_id: UUID,
    body: str,
    parent_id: UUID | None = None,
) -> QuestionPost:
    cleaned = normalize_body(body)
    if parent_id is not None:
        parent = await db.get(QuestionPost, parent_id)
        if parent is None or parent.is_deleted:
            raise HTTPException(status_code=404, detail="parent not found")
        if parent.lesson_id != lesson_id:
            raise HTTPException(
                status_code=400, detail="parent lesson mismatch"
            )
    row = QuestionPost(
        lesson_id=lesson_id,
        author_id=author_id,
        parent_id=parent_id,
        body=cleaned,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def list_for_lesson(
    db: AsyncSession,
    *,
    lesson_id: UUID,
    limit: int = 50,
) -> list[QuestionPost]:
    result = await db.execute(
        select(QuestionPost)
        .where(
            QuestionPost.lesson_id == lesson_id,
            QuestionPost.parent_id.is_(None),
        )
        .order_by(
            QuestionPost.upvote_count.desc(),
            QuestionPost.created_at.asc(),
        )
        .limit(limit)
    )
    rows = list(result.scalars().all())
    return filter_visible(rows)


async def list_replies(
    db: AsyncSession, *, parent_id: UUID
) -> list[QuestionPost]:
    result = await db.execute(
        select(QuestionPost)
        .where(QuestionPost.parent_id == parent_id)
        .order_by(QuestionPost.created_at.asc())
    )
    return filter_visible(list(result.scalars().all()))


async def record_vote(
    db: AsyncSession,
    *,
    post_id: UUID,
    voter_id: UUID,
    kind: str,
) -> QuestionPost:
    """Register an upvote or flag (idempotent per (post, voter, kind))."""
    normalized = normalize_vote_kind(kind)
    post = await db.get(QuestionPost, post_id)
    if post is None or post.is_deleted:
        raise HTTPException(status_code=404, detail="post not found")
    if post.author_id == voter_id:
        raise HTTPException(
            status_code=400, detail="cannot vote on your own post"
        )

    existing = await db.execute(
        select(QuestionVote).where(
            QuestionVote.post_id == post_id,
            QuestionVote.voter_id == voter_id,
            QuestionVote.kind == normalized,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return post

    vote = QuestionVote(
        post_id=post_id, voter_id=voter_id, kind=normalized
    )
    db.add(vote)
    if normalized == "upvote":
        post.upvote_count += 1
    else:
        post.flag_count += 1
    await db.flush()
    await db.refresh(post)
    return post


async def soft_delete_post(
    db: AsyncSession, *, post_id: UUID, author_id: UUID
) -> QuestionPost:
    post = await db.get(QuestionPost, post_id)
    if post is None or post.author_id != author_id:
        raise HTTPException(status_code=404, detail="post not found")
    post.is_deleted = True
    post.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(post)
    return post


async def count_for_lesson(
    db: AsyncSession, *, lesson_id: UUID
) -> int:
    result = await db.execute(
        select(func.count(QuestionPost.id)).where(
            QuestionPost.lesson_id == lesson_id,
            QuestionPost.is_deleted.is_(False),
        )
    )
    return int(result.scalar_one() or 0)


__all__ = [
    "count_for_lesson",
    "create_post",
    "filter_visible",
    "list_for_lesson",
    "list_replies",
    "normalize_body",
    "normalize_vote_kind",
    "rank_posts",
    "record_vote",
    "should_hide",
    "soft_delete_post",
]
