"""Intent clarification + follow-up pills (P3 3A-4 / #54 + #69).

Two user-facing affordances:
  1. Clarify pills — shown when student's message is ambiguous enough
     that the tutor might guess wrong about what they want (direct
     answer vs hint vs challenge).
  2. Follow-up pills — shown after every substantive reply, to nudge
     the student to the next useful move.

Pure helpers here. No DB, no LLM — lightweight heuristics so the
stream handler can call these inline without adding latency. If we
ever need stronger classification, swap the pure helper for an LLM
call behind the same interface.
"""

from __future__ import annotations

from dataclasses import dataclass

_MIN_CHARS_FOR_PILLS = 12
_AMBIGUITY_TRIGGER_WORDS = frozenset(
    {
        "help",
        "stuck",
        "confused",
        "explain",
        "what",
        "how",
        "why",
        "understand",
    }
)
_DIRECT_ANSWER_SIGNALS = frozenset(
    {"just tell me", "give me the answer", "show me the solution"}
)
_PRACTICE_SIGNALS = frozenset(
    {"quiz me", "test me", "practice", "exercise"}
)


@dataclass(frozen=True)
class ClarificationPill:
    """One pill option shown in the clarify UI."""

    key: str
    label: str


@dataclass(frozen=True)
class ClarifyDecision:
    show_pills: bool
    reason: str
    pills: tuple[ClarificationPill, ...]


_CLARIFY_PILLS: tuple[ClarificationPill, ...] = (
    ClarificationPill(key="direct", label="Just tell me"),
    ClarificationPill(key="hint", label="Give me a hint"),
    ClarificationPill(key="challenge", label="Challenge me"),
)


def should_clarify(
    message: str,
    *,
    socratic_level: int,
    min_chars: int = _MIN_CHARS_FOR_PILLS,
) -> ClarifyDecision:
    """Decide whether to show clarify pills for `message`.

    Skip pills entirely at socratic level 0 (student opted out of
    push) and for short/trivial messages. Otherwise trigger on
    ambiguity signals (generic ask words like "how", "why", "help")
    or when the student has explicitly named one of the three modes
    (so we can just honor it without asking).
    """
    if socratic_level <= 0:
        return ClarifyDecision(
            show_pills=False,
            reason="socratic_level_zero",
            pills=(),
        )
    cleaned = (message or "").strip()
    if len(cleaned) < min_chars:
        return ClarifyDecision(
            show_pills=False, reason="too_short", pills=()
        )
    lowered = cleaned.lower()
    if any(signal in lowered for signal in _DIRECT_ANSWER_SIGNALS):
        return ClarifyDecision(
            show_pills=False, reason="explicit_direct", pills=()
        )
    if any(signal in lowered for signal in _PRACTICE_SIGNALS):
        return ClarifyDecision(
            show_pills=False, reason="explicit_practice", pills=()
        )
    tokens = {
        t.strip(".,!?;:") for t in lowered.split() if t
    }
    if tokens & _AMBIGUITY_TRIGGER_WORDS:
        return ClarifyDecision(
            show_pills=True,
            reason="ambiguous_intent",
            pills=_CLARIFY_PILLS,
        )
    return ClarifyDecision(
        show_pills=False, reason="no_ambiguity", pills=()
    )


@dataclass(frozen=True)
class FollowupPill:
    key: str
    label: str


_GENERIC_FOLLOWUPS: tuple[FollowupPill, ...] = (
    FollowupPill(key="example", label="Show me an example"),
    FollowupPill(key="practice", label="Quiz me on this"),
    FollowupPill(key="deeper", label="Go deeper"),
)

_CODE_FOLLOWUPS: tuple[FollowupPill, ...] = (
    FollowupPill(key="refactor", label="How would you refactor this?"),
    FollowupPill(key="edge_cases", label="What edge cases should I test?"),
    FollowupPill(key="production", label="What breaks in production?"),
)

_CONCEPT_FOLLOWUPS: tuple[FollowupPill, ...] = (
    FollowupPill(key="contrast", label="Contrast with a related concept"),
    FollowupPill(key="example", label="Show me a concrete example"),
    FollowupPill(key="quiz", label="Quiz me on this"),
)


def _looks_like_code_response(reply: str) -> bool:
    return "```" in reply or "def " in reply or "class " in reply


def _looks_like_concept_response(reply: str) -> bool:
    lowered = reply.lower()
    return any(
        phrase in lowered
        for phrase in (
            "is a ",
            "refers to",
            "in other words",
            "concept",
            "definition",
        )
    )


def generate_followups(
    reply: str,
    *,
    min_chars: int = 80,
) -> tuple[FollowupPill, ...]:
    """Return up to 3 contextual follow-up pills for a tutor reply.

    Empty tuple for trivial replies (short greetings, ack-only) so
    the UI doesn't clutter. Picks a pill family based on cheap
    content signals: code → code pills, concept language → concept
    pills, otherwise generic.
    """
    cleaned = (reply or "").strip()
    if len(cleaned) < min_chars:
        return ()
    if _looks_like_code_response(cleaned):
        return _CODE_FOLLOWUPS
    if _looks_like_concept_response(cleaned):
        return _CONCEPT_FOLLOWUPS
    return _GENERIC_FOLLOWUPS


__all__ = [
    "ClarificationPill",
    "ClarifyDecision",
    "FollowupPill",
    "generate_followups",
    "should_clarify",
]
