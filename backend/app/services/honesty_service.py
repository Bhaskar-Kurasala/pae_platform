"""Honesty guardrail: tutor must admit uncertainty (P3 3A-8).

A hallucinated answer erodes trust for every future answer. This module
gives the tutor an explicit rule — when not confident, say so out loud
instead of making something up — and a detector that reports when the
tutor actually fires the rule, so we can track honesty over time without
paying for a separate self-reflection pass.

No post-response rewriting: we don't second-guess the model. If the
detector never fires on made-up-library questions, that's signal we need
to tune the overlay, not silently patch the output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


HONESTY_OVERLAY = (
    "\n\n---\nHonesty rule: if you are not confident in an answer — because the "
    "library, API, or paper the student named may not exist, because the "
    "question falls outside what you can verify, or because you'd have to "
    "guess — say so explicitly with a marker like \"I'm not sure\" or \"I don't "
    "know for certain\" and then offer 2-3 hypotheses the student can check. "
    "Never fabricate a specific API signature, version number, paper citation, "
    "or library name to sound confident. A hedged honest answer is always "
    "better than a confident wrong one."
)


# Phrases that signal the tutor explicitly admitted uncertainty. We match
# specific phrases (not generic "maybe") to keep the telemetry signal
# clean — every hit here should be an actual hedge, not stylistic softness.
_HEDGE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bi'?m not sure\b", re.IGNORECASE),
    re.compile(r"\bi don'?t know (?:for certain|for sure|off the top)", re.IGNORECASE),
    re.compile(r"\bi'?m not certain\b", re.IGNORECASE),
    re.compile(r"\blet me think out loud\b", re.IGNORECASE),
    re.compile(r"\bi (?:can'?t|cannot) verify\b", re.IGNORECASE),
    re.compile(r"\bi'?d need to check\b", re.IGNORECASE),
    re.compile(r"\bi'?m not 100% sure\b", re.IGNORECASE),
    re.compile(r"\bmight not (?:exist|be real|be a real)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class HedgeMatch:
    marker: str


def detect_honesty_hedge(tutor_reply: str) -> HedgeMatch | None:
    """Return the first hedge marker found in the tutor reply, if any."""
    if not tutor_reply:
        return None
    for pattern in _HEDGE_PATTERNS:
        match = pattern.search(tutor_reply)
        if match is not None:
            return HedgeMatch(marker=match.group(0))
    return None
