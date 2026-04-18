"""Disagreement pushback + misconception logging (P3 3A-6).

A yes-machine tutor is worse than no tutor. Two pieces here:

1. **Prompt overlay** (`DISAGREEMENT_OVERLAY`): appended to every tutor
   system prompt so the model knows that politely pushing back on wrong
   factual claims is required behavior, not optional warmth.
2. **Post-response scan**: after the tutor finishes streaming, we scan
   the full reply for disagreement markers ("actually, that's not
   quite right", "a common misconception is…"). When we see one, we log
   the student's assertion + the tutor's correction to
   `student_misconceptions`. The table becomes the seed for 3A-17
   micro-wins ("you unblocked X yesterday") and helps us track which
   wrong models keep coming back.

The detector + logger are pure-ish (the logger is async but deterministic);
the overlay is a frozen string so tests can assert on it.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student_misconception import StudentMisconception

log = structlog.get_logger()


DISAGREEMENT_OVERLAY = (
    "\n\n---\nDisagreement rule: if the student makes a factual claim that is "
    "wrong or misleading, you MUST politely push back rather than agree. "
    "Open the correction with a soft marker — 'Actually,' / 'That's not quite "
    "right —' / 'A common misconception is' — then state what's true and why, "
    "with one concrete example or reference. Do NOT hedge ('some might say', "
    "'it depends') when the student is simply wrong. Do not push back on "
    "questions, uncertainty, or matters of taste — only on confident factual "
    "claims. Being a yes-machine is worse than being silent."
)


# Markers that reliably signal the tutor is correcting the student. Matched
# case-insensitively near the start of sentences. We bias toward specific
# phrases over generic negations ("no", "not really") to keep false
# positives out of the log — a noisy misconception table is useless.
_DISAGREEMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bactually,", re.IGNORECASE),
    re.compile(r"\bthat'?s not (?:quite )?(?:right|correct|accurate)", re.IGNORECASE),
    re.compile(r"\ba common misconception\b", re.IGNORECASE),
    re.compile(r"\bnot exactly\b[,:]", re.IGNORECASE),
    re.compile(
        r"\b(?:small|one) correction\b",
        re.IGNORECASE,
    ),
    re.compile(r"\blet me (?:gently )?push back\b", re.IGNORECASE),
    re.compile(r"\bthat'?s a myth\b", re.IGNORECASE),
)

# Markers that suggest the student was making a confident factual assertion.
# If the message is a question or explicitly hedged ("I think", "I'm not
# sure"), we treat it as not-a-claim and skip logging even if the tutor
# corrects something, because the correction is pedagogical, not a
# disagreement with an asserted belief.
_CLAIM_NEGATIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\?$"),  # ends with a question mark
    re.compile(r"^(?:is|are|does|do|can|could|would|should|will|what|how|why|when|where|which|who)\b", re.IGNORECASE),
    re.compile(r"\bi (?:think|believe|guess|suppose)\b", re.IGNORECASE),
    re.compile(r"\bi'?m not sure\b", re.IGNORECASE),
    re.compile(r"\bnot sure if\b", re.IGNORECASE),
    re.compile(r"\bcan you (?:explain|clarify|help)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class DisagreementMatch:
    """Result of scanning a tutor reply for disagreement markers.

    `marker` is the exact phrase we matched on — useful for telemetry and
    for manually spot-checking false positives in the log.
    """

    marker: str
    # First ~240 chars around the marker; enough context to verify the log
    # without storing the whole reply.
    excerpt: str


def looks_like_factual_claim(message: str) -> bool:
    """True if the student's message reads as a confident assertion.

    Conservative — we'd rather miss logging a real misconception than spam
    the table with pedagogical corrections on questions. Empty / whitespace
    never counts.
    """
    if not message or not message.strip():
        return False
    stripped = message.strip()
    # Short messages (<= 8 chars) are almost never full claims.
    if len(stripped) < 9:
        return False
    for pattern in _CLAIM_NEGATIVE_PATTERNS:
        if pattern.search(stripped):
            return False
    return True


def detect_disagreement(tutor_reply: str) -> DisagreementMatch | None:
    """Scan tutor text for a disagreement marker; return the first match."""
    if not tutor_reply:
        return None
    for pattern in _DISAGREEMENT_PATTERNS:
        match = pattern.search(tutor_reply)
        if match is None:
            continue
        start = max(0, match.start() - 40)
        end = min(len(tutor_reply), match.end() + 200)
        excerpt = tutor_reply[start:end].strip()
        return DisagreementMatch(marker=match.group(0), excerpt=excerpt)
    return None


def _guess_topic(student_assertion: str) -> str:
    """Cheap topic extraction — first clause or first 12 words.

    The topic column is free text and best-effort; the student_assertion
    itself is stored in full so a smarter classifier can reprocess later.
    """
    head = re.split(r"[.!\n]", student_assertion.strip(), maxsplit=1)[0]
    words = head.split()
    return " ".join(words[:12])


async def log_disagreement(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    student_assertion: str,
    tutor_correction: str,
    topic: str | None = None,
) -> StudentMisconception:
    """Persist a disagreement row. Caller owns the transaction (no commit)."""
    row = StudentMisconception(
        user_id=user_id,
        topic=topic if topic is not None else _guess_topic(student_assertion),
        student_assertion=student_assertion[:4000],
        tutor_correction=tutor_correction[:4000],
    )
    db.add(row)
    log.info(
        "tutor.disagreement_logged",
        user_id=str(user_id),
        topic=row.topic,
    )
    return row


async def maybe_log_disagreement(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    student_message: str,
    tutor_reply: str,
) -> StudentMisconception | None:
    """End-to-end: check both gates, log if both trigger."""
    if not looks_like_factual_claim(student_message):
        return None
    match = detect_disagreement(tutor_reply)
    if match is None:
        return None
    return await log_disagreement(
        db,
        user_id=user_id,
        student_assertion=student_message,
        tutor_correction=match.excerpt,
    )
