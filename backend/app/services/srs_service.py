"""Spaced-repetition service (P2-05).

Implements SM-2 — the algorithm from the original SuperMemo paper. Quality is a
0-5 scale:

    0-2  — incorrect. Reset repetitions, interval back to 1 day.
    3    — correct but hard. Advance, but only slightly penalise ease.
    4    — correct, some hesitation. Normal advance.
    5    — correct, easy. Normal advance + small ease bump.

Pure function `apply_sm2` is deterministic and unit-tested independently of the
DB so the scheduling logic is reviewable without fixtures.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.srs_card import SRSCard

MIN_EASE = 1.3
MAX_EASE = 3.0
DEFAULT_EASE = 2.5


@dataclass(frozen=True)
class SM2Result:
    ease_factor: float
    interval_days: int
    repetitions: int


def _clamp_quality(q: int) -> int:
    if q < 0:
        return 0
    if q > 5:
        return 5
    return q


def apply_sm2(
    *, quality: int, ease_factor: float, interval_days: int, repetitions: int
) -> SM2Result:
    """One SM-2 step.

    Rules, per the original Wozniak paper:
      - quality < 3 ⇒ reset repetitions to 0, interval back to 1 day, ease
        still updated by the quality penalty (so repeatedly failing a card
        makes it harder to skip later).
      - quality ≥ 3 ⇒ first rep → 1d, second rep → 6d, thereafter
        interval = round(prev_interval * ease_factor). Repetitions
        increment by one.
    """
    q = _clamp_quality(quality)

    # Ease-factor update is the same curve in both branches (Wozniak).
    # EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    delta = 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)
    new_ease = max(MIN_EASE, min(MAX_EASE, ease_factor + delta))

    if q < 3:
        return SM2Result(
            ease_factor=round(new_ease, 3),
            interval_days=1,
            repetitions=0,
        )

    if repetitions == 0:
        new_interval = 1
    elif repetitions == 1:
        new_interval = 6
    else:
        new_interval = max(1, round(interval_days * new_ease))

    return SM2Result(
        ease_factor=round(new_ease, 3),
        interval_days=new_interval,
        repetitions=repetitions + 1,
    )


def _now() -> datetime:
    return datetime.now(UTC)


class SRSService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert_card(
        self,
        *,
        user_id: uuid.UUID,
        concept_key: str,
        prompt: str = "",
        answer: str = "",
        hint: str = "",
    ) -> SRSCard:
        """Add a card if it doesn't exist. Existing cards keep their SM-2 state.

        Useful for lesson completion / exercise submission flows that want to
        register a concept for review without clobbering prior progress.
        Answer / hint are filled in only when blank so we never overwrite a
        more carefully authored copy.
        """
        existing = (
            await self.db.execute(
                select(SRSCard).where(
                    SRSCard.user_id == user_id,
                    SRSCard.concept_key == concept_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            dirty = False
            if prompt and not existing.prompt:
                existing.prompt = prompt[:512]
                dirty = True
            if answer and not existing.answer:
                existing.answer = answer
                dirty = True
            if hint and not existing.hint:
                existing.hint = hint
                dirty = True
            if dirty:
                await self.db.commit()
                await self.db.refresh(existing)
            return existing

        card = SRSCard(
            user_id=user_id,
            concept_key=concept_key,
            prompt=prompt[:512],
            answer=answer,
            hint=hint,
            ease_factor=DEFAULT_EASE,
            interval_days=0,
            repetitions=0,
            next_due_at=_now(),
        )
        self.db.add(card)
        await self.db.commit()
        await self.db.refresh(card)
        return card

    async def list_due(
        self,
        *,
        user_id: uuid.UUID,
        limit: int = 10,
        now: datetime | None = None,
    ) -> list[SRSCard]:
        """Cards whose next_due_at <= now, oldest first."""
        threshold = now or _now()
        result = await self.db.execute(
            select(SRSCard)
            .where(
                SRSCard.user_id == user_id,
                SRSCard.next_due_at <= threshold,
            )
            .order_by(SRSCard.next_due_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def review(
        self,
        *,
        user_id: uuid.UUID,
        card_id: uuid.UUID,
        quality: int,
        now: datetime | None = None,
    ) -> SRSCard:
        """Apply one SM-2 step and persist. Raises LookupError if no card."""
        card = (
            await self.db.execute(
                select(SRSCard).where(
                    SRSCard.id == card_id,
                    SRSCard.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if card is None:
            raise LookupError("srs card not found")

        result = apply_sm2(
            quality=quality,
            ease_factor=float(card.ease_factor),
            interval_days=int(card.interval_days),
            repetitions=int(card.repetitions),
        )

        reviewed_at = now or _now()
        card.ease_factor = result.ease_factor
        card.interval_days = result.interval_days
        card.repetitions = result.repetitions
        card.last_reviewed_at = reviewed_at
        card.next_due_at = reviewed_at + timedelta(days=result.interval_days)

        await self.db.commit()
        await self.db.refresh(card)

        # Notebook-graduation hook: if this card backs a notebook entry that
        # has now crossed the rep threshold, stamp `graduated_at` so the
        # entry flips from "In review" to "Graduated" on the Notebook screen.
        # Wrapped in try/except — we never want a graduation hiccup to roll
        # back the SM-2 update the student just earned.
        try:
            from app.services.notebook_service import maybe_graduate_card

            await maybe_graduate_card(self.db, card=card, now=reviewed_at)
        except Exception:
            pass

        return card
