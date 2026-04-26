"""Culture-signal pattern library for the JD decoder.

Pre-pass over a raw JD text before the LLM analyst runs. Catches the
obvious patterns deterministically so the analyst can focus on nuance and
so we have a guaranteed signal even if the LLM call is degraded.

Output is a list of ``CultureSignal`` dicts with the same shape the
schema expects (``pattern``, ``severity``, ``note``). The LLM analyst
may add to or refine this list; deterministic flags are merged into its
output by the orchestrator.
"""

from __future__ import annotations

import re
from typing import Literal, TypedDict

CultureSeverity = Literal["info", "watch", "warn"]


class CultureSignal(TypedDict):
    pattern: str
    severity: CultureSeverity
    note: str


# Each entry: (label, severity, regex_or_substring, note).
# Substrings are matched case-insensitively. Regex entries use compiled
# patterns directly — keep them anchored on word boundaries to avoid
# false-positive matches inside unrelated longer words.
_PATTERNS: list[tuple[str, CultureSeverity, re.Pattern[str], str]] = [
    (
        "burnout language: hard-charging / rockstar",
        "warn",
        re.compile(
            r"\b(hard[\- ]charging|rockstar|10x|ninja|wear (many|multiple) hats)\b",
            re.IGNORECASE,
        ),
        "Phrasing that historically correlates with long hours and "
        "fuzzy scope. Worth probing in the interview.",
    ),
    (
        "burnout language: comfortable with ambiguity",
        "watch",
        re.compile(
            r"\b(comfortable with ambiguity|thrive in chaos|move fast and break things)\b",
            re.IGNORECASE,
        ),
        "Often a euphemism for unclear priorities or undocumented "
        "process. Ask about how the team makes decisions.",
    ),
    (
        "ownership mentality",
        "watch",
        re.compile(r"\bownership mentality\b", re.IGNORECASE),
        "Can mean trust-and-autonomy, or it can mean being on call for "
        "outcomes you don't control. Ask for a specific example.",
    ),
    (
        "vague compensation",
        "watch",
        re.compile(
            r"\bcompetitive (salary|compensation|pay)\b",
            re.IGNORECASE,
        ),
        "When 'competitive' is the only comp signal in the JD, expect "
        "the offer to come in at or below market. Ask for the band early.",
    ),
    (
        "passion language",
        "info",
        re.compile(
            r"\b(passionate about|love what we do|mission[\- ]driven)\b",
            re.IGNORECASE,
        ),
        "Common boilerplate. Neutral on its own; weight it lower than "
        "the responsibilities and growth narrative.",
    ),
    (
        "fast-paced",
        "info",
        re.compile(r"\bfast[\- ]paced\b", re.IGNORECASE),
        "Says nothing concrete. Worth asking what 'pace' specifically "
        "means — release cadence, on-call expectations, etc.",
    ),
    (
        "vague growth promise",
        "watch",
        re.compile(
            r"\b(opportunities for growth|grow with the (team|company)|career path)\b",
            re.IGNORECASE,
        ),
        "If the JD talks about growth without specifics (promotion "
        "criteria, learning budget, mentorship structure), it's "
        "boilerplate. Ask for concrete examples.",
    ),
    (
        "long hours flag",
        "warn",
        re.compile(
            r"\b(work hard,?\s*play hard|always[\- ]on|24/7)\b",
            re.IGNORECASE,
        ),
        "Plain language for long hours. Take it at face value.",
    ),
]


def detect_culture_signals(jd_text: str) -> list[CultureSignal]:
    """Return signals matched deterministically against *jd_text*.

    Each pattern fires at most once even if it appears repeatedly.
    The LLM analyst may add additional signals; the orchestrator merges
    by ``pattern`` label, preferring the analyst's note when both exist
    (LLM tends to write more nuanced notes than the pre-pass library).
    """
    if not jd_text:
        return []
    seen: set[str] = set()
    signals: list[CultureSignal] = []
    for label, severity, pattern, note in _PATTERNS:
        if label in seen:
            continue
        if pattern.search(jd_text):
            signals.append(
                {"pattern": label, "severity": severity, "note": note}
            )
            seen.add(label)
    return signals


def merge_culture_signals(
    deterministic: list[CultureSignal],
    llm: list[CultureSignal],
) -> list[CultureSignal]:
    """Merge two signal lists by pattern label.

    LLM-authored notes win when both sources agree on a pattern; the
    deterministic severity is preserved (the LLM tends to be more
    optimistic about severity than the pattern library).
    """
    by_label: dict[str, CultureSignal] = {}
    for sig in deterministic:
        by_label[sig["pattern"]] = sig
    for sig in llm:
        label = sig.get("pattern") or ""
        if not label:
            continue
        if label in by_label:
            existing = by_label[label]
            by_label[label] = {
                "pattern": label,
                "severity": existing["severity"],
                "note": sig.get("note") or existing["note"],
            }
        else:
            severity = sig.get("severity") or "info"
            if severity not in ("info", "watch", "warn"):
                severity = "info"
            by_label[label] = {
                "pattern": label,
                "severity": severity,
                "note": sig.get("note") or "",
            }
    return list(by_label.values())


__all__ = [
    "CultureSignal",
    "detect_culture_signals",
    "merge_culture_signals",
]
