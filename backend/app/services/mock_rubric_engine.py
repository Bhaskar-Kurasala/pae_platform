"""Mode-specific rubric definitions for the mock interview Scorer.

The rubrics are deterministic — same `mode + level` always returns the same
shape — so the Scorer prompt + tests can rely on them.
"""

from __future__ import annotations

from typing import Literal

Mode = Literal["behavioral", "technical_conceptual", "live_coding", "system_design"]
Level = Literal["junior", "mid", "senior"]


_BEHAVIORAL = [
    {
        "name": "clarity",
        "description": "Is the answer easy to follow? Does the candidate state the main point upfront?",
    },
    {
        "name": "structure",
        "description": "STAR structure: Situation → Task → Action → Result. Penalise heavily for missing components.",
    },
    {
        "name": "specificity",
        "description": "Concrete details (names, dates, numbers) — not generic platitudes.",
    },
    {
        "name": "ownership",
        "description": "Did the candidate name *their* contribution? 'We' without 'I' is a major flag.",
    },
    {
        "name": "result_quantification",
        "description": "Result has a measurable outcome — number, %, time saved, etc.",
    },
]


_TECHNICAL_CONCEPTUAL = [
    {
        "name": "correctness",
        "description": "Is the core technical claim accurate?",
    },
    {
        "name": "depth",
        "description": "Beyond textbook — production realities, lived experience, failure modes.",
    },
    {
        "name": "edge_cases",
        "description": "Did the candidate consider edge cases unprompted?",
    },
    {
        "name": "tradeoffs",
        "description": "Are tradeoffs acknowledged with concrete reasoning?",
    },
    {
        "name": "communication",
        "description": "Logical flow; appropriate vocabulary; no rambling.",
    },
]


_LIVE_CODING = [
    {
        "name": "correctness",
        "description": "Does the code solve the problem? Pass the visible test case?",
    },
    {
        "name": "time_complexity",
        "description": "Did the candidate articulate Big-O during or after writing?",
    },
    {
        "name": "edge_cases",
        "description": "Empty input, single-element, very large input — handled or named?",
    },
    {
        "name": "code_quality",
        "description": "Naming, structure, no gratuitous globals or unused vars.",
    },
    {
        "name": "communication_during",
        "description": "Did the candidate think out loud while coding?",
    },
]


_SYSTEM_DESIGN_DEFERRED = [
    {
        "name": "deferred",
        "description": "system_design mode is Phase 2 — this rubric is a stub.",
    }
]


def rubric_for(mode: Mode, level: Level) -> list[dict[str, str]]:
    """Return the rubric criteria for *mode*. *level* is informational only —
    the calibration thresholds live in the Scorer prompt."""
    rubrics: dict[Mode, list[dict[str, str]]] = {
        "behavioral": _BEHAVIORAL,
        "technical_conceptual": _TECHNICAL_CONCEPTUAL,
        "live_coding": _LIVE_CODING,
        "system_design": _SYSTEM_DESIGN_DEFERRED,
    }
    return list(rubrics.get(mode, _BEHAVIORAL))


def warmup_rubric_hint(mode: Mode) -> str:
    return {
        "behavioral": "look for a clear story arc; warm-up doesn't need quantified result",
        "technical_conceptual": "look for clarity and one specific example",
        "live_coding": "look for problem-restatement and a brief plan before coding",
        "system_design": "deferred",
    }.get(mode, "general clarity")
