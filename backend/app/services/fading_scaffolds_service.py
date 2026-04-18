"""Fading scaffolds (P3 3B #92).

Companion to `scaffolding_service` (P2-01). That service picks *how much*
scaffolding to give based on skill confidence. This one caps the *number
of hint levels* a student gets to consume as they re-attempt the same
exercise — the scaffolds fade away as attempt count rises, even if the
tutor would otherwise offer more.

Rule of thumb:
  attempt 1  → up to 3 hint levels (gentle nudge, worked sub-step, near-solution)
  attempt 2  → up to 2 levels       (gentle nudge, worked sub-step)
  attempt 3  → up to 1 level        (gentle nudge only)
  attempt 4+ → 0 — make the student retrieve unaided

Pure helpers only — no DB.
"""

from __future__ import annotations

from dataclasses import dataclass

_HINT_LEVEL_NAMES = ("gentle_nudge", "worked_sub_step", "near_solution")
_MAX_HINT_LEVELS = len(_HINT_LEVEL_NAMES)


@dataclass(frozen=True)
class FadedScaffold:
    attempt_number: int
    allowed_levels: tuple[str, ...]
    faded: bool
    reason: str


def allowed_hint_count(attempt_number: int) -> int:
    """How many hint *levels* are allowed on this attempt."""
    if attempt_number < 1:
        return _MAX_HINT_LEVELS
    remaining = _MAX_HINT_LEVELS - (attempt_number - 1)
    return max(0, remaining)


def fade_scaffolds(attempt_number: int) -> FadedScaffold:
    """Return the scaffold envelope for the attempt."""
    count = allowed_hint_count(attempt_number)
    allowed = _HINT_LEVEL_NAMES[:count]
    faded = count < _MAX_HINT_LEVELS
    if count == 0:
        reason = (
            "You've seen enough hints — let's test retrieval without a net"
        )
    elif faded:
        reason = (
            f"Hints are fading with practice — {count} level"
            f"{'s' if count != 1 else ''} available"
        )
    else:
        reason = "Full scaffolding available"
    return FadedScaffold(
        attempt_number=max(1, attempt_number),
        allowed_levels=allowed,
        faded=faded,
        reason=reason,
    )


__all__ = [
    "FadedScaffold",
    "allowed_hint_count",
    "fade_scaffolds",
]
