"""Notebook service — listing, summary aggregation, and graduation hook.

Notes "graduate" from active review to long-term memory when the SRS card
backing them proves recall (`repetitions >= 2`). Graduation is a one-way
state stamped by `maybe_graduate(...)` — once stamped, we don't un-graduate
even if the student later forgets and resets the SRS state. The eyebrow on
the Notebook screen flips from "In review · …" to "Graduated · …" the
moment graduation lands.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notebook_entry import NotebookEntry
from app.models.srs_card import SRSCard
from app.models.user import User

NOTEBOOK_CONCEPT_PREFIX = "notebook:"
GRADUATION_THRESHOLD_REPS = 2


def concept_key_for(entry: NotebookEntry) -> str:
    """Stable concept key for the SRS card that backs a notebook entry."""
    return f"{NOTEBOOK_CONCEPT_PREFIX}{entry.id}"


def is_notebook_concept(key: str) -> bool:
    return key.startswith(NOTEBOOK_CONCEPT_PREFIX)


def entry_id_from_concept(key: str) -> uuid.UUID | None:
    if not is_notebook_concept(key):
        return None
    try:
        return uuid.UUID(key[len(NOTEBOOK_CONCEPT_PREFIX):])
    except ValueError:
        return None


@dataclass(frozen=True)
class NotebookSourceCount:
    source: str
    count: int


@dataclass(frozen=True)
class NotebookSummary:
    total: int
    graduated: int
    in_review: int
    by_source: list[NotebookSourceCount]
    latest_graduated_at: datetime | None
    graduation_percentage: float


GraduatedFilter = Literal["all", "graduated", "in_review"]


async def list_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    source: str | None = None,
    graduated: GraduatedFilter = "all",
    tag: str | None = None,
    limit: int = 200,
) -> list[NotebookEntry]:
    """Filtered list of notebook entries, newest first."""
    q = (
        select(NotebookEntry)
        .where(NotebookEntry.user_id == user_id)
        .order_by(desc(NotebookEntry.created_at))
        .limit(limit)
    )
    if source is not None:
        q = q.where(NotebookEntry.source_type == source)
    if graduated == "graduated":
        q = q.where(NotebookEntry.graduated_at.is_not(None))
    elif graduated == "in_review":
        q = q.where(NotebookEntry.graduated_at.is_(None))

    rows = list((await db.execute(q)).scalars().all())
    if tag is None:
        return rows
    needle = tag.strip().lower()
    if not needle:
        return rows
    return [
        r for r in rows
        if any((t or "").strip().lower() == needle for t in (r.tags or []))
    ]


async def summary_for_user(
    db: AsyncSession, *, user: User
) -> NotebookSummary:
    """Aggregate counts for the Notebook screen ghost card + topbar."""
    total_q = select(func.count(NotebookEntry.id)).where(
        NotebookEntry.user_id == user.id
    )
    grad_q = total_q.where(NotebookEntry.graduated_at.is_not(None))
    src_q = (
        select(NotebookEntry.source_type, func.count(NotebookEntry.id))
        .where(NotebookEntry.user_id == user.id)
        .group_by(NotebookEntry.source_type)
    )
    latest_q = select(func.max(NotebookEntry.graduated_at)).where(
        NotebookEntry.user_id == user.id,
        NotebookEntry.graduated_at.is_not(None),
    )

    total = int((await db.execute(total_q)).scalar() or 0)
    graduated = int((await db.execute(grad_q)).scalar() or 0)
    by_source = [
        NotebookSourceCount(source=src or "chat", count=int(cnt))
        for src, cnt in (await db.execute(src_q)).all()
    ]
    latest = (await db.execute(latest_q)).scalar()
    in_review = max(0, total - graduated)
    pct = round(graduated / total * 100, 1) if total > 0 else 0.0
    return NotebookSummary(
        total=total,
        graduated=graduated,
        in_review=in_review,
        by_source=by_source,
        latest_graduated_at=latest,
        graduation_percentage=pct,
    )


async def maybe_graduate_card(
    db: AsyncSession, *, card: SRSCard, now: datetime | None = None
) -> NotebookEntry | None:
    """If `card` backs a notebook entry and has crossed the rep threshold,
    stamp `graduated_at` on the entry. Idempotent — already-graduated entries
    are returned unchanged.

    Called from the SRS review path so graduation lands in the same
    transaction as the rep increment. Safe to call on any card; only
    notebook-keyed concepts trigger a write.
    """
    entry_id = entry_id_from_concept(card.concept_key)
    if entry_id is None:
        return None
    if int(card.repetitions) < GRADUATION_THRESHOLD_REPS:
        return None
    entry = (
        await db.execute(
            select(NotebookEntry).where(NotebookEntry.id == entry_id)
        )
    ).scalar_one_or_none()
    if entry is None:
        return None
    if entry.graduated_at is not None:
        return entry
    entry.graduated_at = now or datetime.now(UTC)
    await db.commit()
    await db.refresh(entry)
    return entry


def all_tags(entries: Iterable[NotebookEntry]) -> list[str]:
    """Distinct, lowercase-deduped tag set across entries (sorted)."""
    seen: dict[str, str] = {}
    for e in entries:
        for t in (e.tags or []):
            key = (t or "").strip().lower()
            if not key or key in seen:
                continue
            seen[key] = (t or "").strip()
    return sorted(seen.values(), key=str.lower)
