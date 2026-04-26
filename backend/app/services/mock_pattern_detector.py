"""Pattern detection over a mock interview transcript.

Surfaces the kind of insight that voice prep tools usually charge for:
filler word counts, time-to-first-word, evasion patterns. Pure-Python,
no LLM.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

# Common interview filler words — keep the list focused, not exhaustive.
# We surface them as a *signal*, not a punishment.
_FILLERS = {
    "um",
    "uh",
    "like",
    "you know",
    "i mean",
    "kind of",
    "sort of",
    "basically",
    "literally",
    "actually",
    "honestly",
    "i guess",
    "i think",
    "i would say",
}

# Phrases that indicate evasion of the actual question.
_EVASION_PATTERNS = [
    r"\bi (?:don'?t|do not) (?:really )?(?:remember|recall|know exactly)\b",
    r"\b(?:that'?s|it'?s) (?:a )?(?:hard|tricky|tough) (?:one|question)\b",
    r"\bi (?:never|haven'?t) (?:really )?(?:done|tried|seen) that\b",
]
_EVASION_RE = re.compile("|".join(_EVASION_PATTERNS), re.IGNORECASE)

_HEDGE_RE = re.compile(
    r"\b(maybe|possibly|might|sort of|kind of|i think|i guess|not sure|probably)\b",
    re.IGNORECASE,
)


@dataclass
class AnswerSignals:
    """Per-answer pattern signals — written to mock_answers row."""

    word_count: int
    filler_word_count: int
    hedge_word_count: int
    evasion_hits: int


@dataclass
class SessionPatterns:
    """Aggregated patterns for the post-mortem report."""

    filler_word_rate: float  # per 100 words
    avg_time_to_first_word_ms: float | None
    avg_words_per_answer: float
    evasion_count: int
    confidence_language_score: float  # 0–10, derived from hedge density inverse

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)


def detect_answer_signals(answer_text: str) -> AnswerSignals:
    """Compute per-answer signals. Used by the orchestrator on each submit."""
    text = (answer_text or "").lower()
    words = re.findall(r"\b\w+(?:'\w+)?\b", text)
    word_count = len(words)

    # Filler words — count multi-word phrases too.
    filler_count = 0
    for filler in _FILLERS:
        if " " in filler:
            filler_count += text.count(filler)
        else:
            filler_count += sum(1 for w in words if w == filler)

    hedge_count = len(_HEDGE_RE.findall(text))
    evasion_hits = len(_EVASION_RE.findall(text))

    return AnswerSignals(
        word_count=word_count,
        filler_word_count=filler_count,
        hedge_word_count=hedge_count,
        evasion_hits=evasion_hits,
    )


def aggregate_session_patterns(
    *,
    answer_signals: list[AnswerSignals],
    time_to_first_word_samples: list[int],
) -> SessionPatterns:
    """Aggregate per-answer signals into a session-level pattern report."""
    if not answer_signals:
        return SessionPatterns(
            filler_word_rate=0.0,
            avg_time_to_first_word_ms=None,
            avg_words_per_answer=0.0,
            evasion_count=0,
            confidence_language_score=5.0,
        )

    total_words = sum(s.word_count for s in answer_signals)
    total_fillers = sum(s.filler_word_count for s in answer_signals)
    total_hedges = sum(s.hedge_word_count for s in answer_signals)
    total_evasions = sum(s.evasion_hits for s in answer_signals)

    filler_rate = (total_fillers / total_words * 100) if total_words else 0.0
    avg_words = total_words / len(answer_signals) if answer_signals else 0.0

    # Confidence language: more hedges per word → lower score.
    # Calibration: 0 hedges/100 words → 10; 5+ hedges/100 words → 0.
    hedge_rate = (total_hedges / total_words * 100) if total_words else 0.0
    confidence_score = max(0.0, min(10.0, 10.0 - (hedge_rate * 2.0)))

    avg_ttfw = (
        sum(time_to_first_word_samples) / len(time_to_first_word_samples)
        if time_to_first_word_samples
        else None
    )

    return SessionPatterns(
        filler_word_rate=round(filler_rate, 2),
        avg_time_to_first_word_ms=avg_ttfw,
        avg_words_per_answer=round(avg_words, 1),
        evasion_count=total_evasions,
        confidence_language_score=round(confidence_score, 1),
    )
