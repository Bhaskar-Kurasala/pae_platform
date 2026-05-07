"""D15 CP3 resume — runtime grounding cross-reference verifier.

Reusable utility for the CP3 + CP4 real-LLM harnesses. Per the founder's
post-Bug-24 framing:

    "For each phase, after the agent dispatches, the verification
    harness extracts any capstone/exercise/notebook names mentioned
    in the agent output, reads the same call's
    read_student_accessible_content output, and verifies that every
    extracted name appears in accessible_courses /
    accessible_curated_problems / accessible_notebooks. If not:
    flags as runtime grounding violation."

The verifier sidesteps a known operational gap in the agent_tool_calls
audit (career_coach doesn't currently persist tool-call rows under its
seeded user_id — pre-existing issue, not Bug 24) by re-querying
accessible content directly from the same DB the agent saw. Because
the seeded student state is stable for the duration of a phase,
re-querying yields the same projection the agent consumed.

Heuristic for content-name extraction: scan the agent's full JSON
output for capitalized phrase shapes that look like content titles.
The detector is intentionally narrow — only patterns that look like
authored content names (Title Case multi-word, "DXX CP" prefixes
specific to platform capstone naming, parenthetical "(Title …)"
references) — so legitimate role-identity language ("you're a Python
Developer") doesn't trip the alarm.

When the founder's hard stop fires ("verifier produces false positives
that the LLM legitimately should be making: STOP and tune"), the
caller can pass `extra_legitimate_names` to whitelist phrases that
the verifier was wrongly catching.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class GroundingFinding:
    """One runtime-grounding-rule violation."""

    extracted_name: str
    where_seen: str  # JSON path or section label
    accessible_set_size: int


@dataclass
class GroundingVerification:
    """Result of running the verifier against one phase."""

    extracted_names: list[str] = field(default_factory=list)
    accessible_titles: set[str] = field(default_factory=set)
    findings: list[GroundingFinding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings

    def summary(self) -> str:
        if self.passed:
            return (
                f"runtime_grounding: ok ({len(self.extracted_names)} "
                f"content references all matched against "
                f"{len(self.accessible_titles)} accessible titles)"
            )
        names = ", ".join(f.extracted_name for f in self.findings[:5])
        return (
            f"runtime_grounding: {len(self.findings)} violation(s) — "
            f"e.g. {names}"
        )


# ── Accessible-content lookup ─────────────────────────────────────


async def fetch_accessible_titles(
    session: AsyncSession,
    *,
    student_id: Any,
    role_slug: str | None = None,
) -> set[str]:
    """Re-derive the agent's accessible content set from the live DB.

    Mirrors the SQL shape of the read_student_accessible_content tool;
    re-querying here (rather than reading from the agent_tool_calls
    audit) bypasses the pre-existing audit-write gap on career_coach.
    The seeded student state is stable across the phase so the
    snapshot the verifier sees matches what the agent saw.
    """
    accessible_titles: set[str] = set()
    role_filter = "AND r.slug = :role_slug" if role_slug else ""
    bind: dict[str, Any] = {"sid": student_id}
    if role_slug:
        bind["role_slug"] = role_slug

    # Courses
    course_rows = (
        await session.execute(
            sql_text(
                f"""
                SELECT c.title
                FROM course_entitlements ce
                JOIN courses c ON c.id = ce.course_id
                LEFT JOIN roles r ON r.id = c.role_id
                WHERE ce.user_id = :sid
                  AND ce.revoked_at IS NULL
                  AND (ce.expires_at IS NULL OR ce.expires_at > now())
                  {role_filter}
                """
            ),
            bind,
        )
    ).all()
    for (title,) in course_rows:
        if title:
            accessible_titles.add(title)

    # Curated problems / capstones
    problem_rows = (
        await session.execute(
            sql_text(
                f"""
                SELECT e.title
                FROM exercises e
                JOIN lessons l ON l.id = e.lesson_id
                JOIN courses c ON c.id = l.course_id
                LEFT JOIN roles r ON r.id = c.role_id
                JOIN course_entitlements ce
                    ON ce.course_id = c.id
                    AND ce.user_id = :sid
                    AND ce.revoked_at IS NULL
                    AND (ce.expires_at IS NULL OR ce.expires_at > now())
                WHERE (e.is_deleted IS NULL OR e.is_deleted = FALSE)
                  {role_filter}
                """
            ),
            bind,
        )
    ).all()
    for (title,) in problem_rows:
        if title:
            accessible_titles.add(title)

    # Notebooks (lesson_resources)
    nb_rows = (
        await session.execute(
            sql_text(
                f"""
                SELECT lr.title
                FROM lesson_resources lr
                JOIN courses c ON c.id = lr.course_id
                LEFT JOIN roles r ON r.id = c.role_id
                JOIN course_entitlements ce
                    ON ce.course_id = c.id
                    AND ce.user_id = :sid
                    AND ce.revoked_at IS NULL
                    AND (ce.expires_at IS NULL OR ce.expires_at > now())
                WHERE 1=1
                  {role_filter}
                """
            ),
            bind,
        )
    ).all()
    for (title,) in nb_rows:
        if title:
            accessible_titles.add(title)

    return accessible_titles


# ── Content-name extraction ───────────────────────────────────────


# Pattern matches strings that look like authored platform content
# titles. Conservative by design: requires a "DNN CP" platform capstone
# prefix OR a parenthetical "(Title Case Phrase)" reference following
# the word "capstone"/"exercise"/"course"/"problem"/"notebook"/"submit".
# Tuned post-Bug-24 — this is the shape the LLM actually used to refer
# to the leaked capstone ("D14c CP3 Phase 2: Multi-Agent Eval Harness").
_CAPSTONE_TITLE_RE = re.compile(
    r"\bD\d+[a-z]?\s+CP\d+(?:\s+[A-Za-z][A-Za-z0-9]*)+(?::?\s*[A-Z][A-Za-z][A-Za-z0-9 \-]+)?",
)
_PARENTHETICAL_TITLE_RE = re.compile(
    r"\((?:the\s+)?([A-Z][A-Za-z0-9][A-Za-z0-9 \-:]+(?:[A-Za-z0-9]))\)",
)
_CONTENT_REF_KEYWORDS = (
    "capstone",
    "exercise",
    "notebook",
    "lesson",
    "submission",
    "course",
    "problem",
)


# Suppression list — things that LOOK like content titles but are
# legitimately referenced role identities, role display names, or
# generic platform vocabulary the LLM uses for framing. These are
# never platform-authored content; flagging them would produce false
# positives.
_LEGITIMATE_ROLE_REFERENCES = {
    "Python Developer",
    "Data Analyst",
    "Data Scientist",
    "ML Engineer",
    "GenAI Engineer",
    "Senior GenAI Engineer",
    "Senior ML Engineer",
    "Senior Data Scientist",
    "Senior Data Analyst",
    "AICareerOS",
    "Career Coach",
    "Study Planner",
}


def _is_legitimate_phrase(name: str) -> bool:
    """Filter out role names + platform-vocabulary phrases."""
    return name.strip() in _LEGITIMATE_ROLE_REFERENCES


def extract_content_references(
    agent_output: dict[str, Any] | str,
) -> list[tuple[str, str]]:
    """Extract candidate content-name references from agent output.

    Returns a list of (extracted_name, where_seen) tuples. `where_seen`
    is the field path or section name where the match landed, used for
    human-readable findings.
    """
    if isinstance(agent_output, dict):
        text_blob = json.dumps(agent_output, default=str)
    else:
        text_blob = str(agent_output)

    refs: list[tuple[str, str]] = []

    # Pattern 1: D-prefixed platform capstone titles (the Bug 24
    # signature). Always flag these — none are role identities.
    for m in _CAPSTONE_TITLE_RE.finditer(text_blob):
        name = m.group(0).strip(" \t\n.,;:")
        refs.append((name, "agent_output"))

    # Pattern 2: parenthetical Title Case phrase that appears within a
    # local context window (~80 chars) of a content keyword. Filters
    # out role identities via _is_legitimate_phrase.
    for m in _PARENTHETICAL_TITLE_RE.finditer(text_blob):
        candidate = m.group(1).strip()
        if _is_legitimate_phrase(candidate):
            continue
        # Single-word phrases (e.g. "(LLMs)") rarely refer to platform
        # content; require >= 2 words.
        if len(candidate.split()) < 2:
            continue
        # Local context check: is a content keyword nearby?
        window_start = max(0, m.start() - 80)
        window_end = min(len(text_blob), m.end() + 80)
        window = text_blob[window_start:window_end].lower()
        if any(kw in window for kw in _CONTENT_REF_KEYWORDS):
            refs.append((candidate, "agent_output"))

    return refs


# ── Verification driver ──────────────────────────────────────────


async def verify_runtime_grounding(
    session: AsyncSession,
    *,
    agent_output: dict[str, Any] | str,
    student_id: Any,
    role_slug: str | None,
    extra_legitimate_names: Iterable[str] | None = None,
) -> GroundingVerification:
    """Run the cross-reference verification for one phase.

    Returns a GroundingVerification carrying the extracted candidate
    names, the accessible-titles set, and any findings. `findings`
    is empty when every extracted name was found in the accessible
    set OR was legitimate role-identity language.
    """
    accessible_titles = await fetch_accessible_titles(
        session, student_id=student_id, role_slug=role_slug
    )
    extras = set(extra_legitimate_names or [])

    refs = extract_content_references(agent_output)
    seen_names: list[str] = []
    findings: list[GroundingFinding] = []

    for name, where in refs:
        seen_names.append(name)
        if name in accessible_titles:
            continue
        if name in extras:
            continue
        # Substring match also acceptable: the LLM may shorten "Data
        # Analyst Path" to "Data Analyst Path" or extend it with a
        # subtitle. Allow titles that partially match an accessible
        # title in either direction.
        substring_match = any(
            name in t or t in name for t in accessible_titles if len(t) >= 6
        )
        if substring_match:
            continue
        findings.append(
            GroundingFinding(
                extracted_name=name,
                where_seen=where,
                accessible_set_size=len(accessible_titles),
            )
        )

    return GroundingVerification(
        extracted_names=seen_names,
        accessible_titles=accessible_titles,
        findings=findings,
    )


__all__ = [
    "GroundingFinding",
    "GroundingVerification",
    "extract_content_references",
    "fetch_accessible_titles",
    "verify_runtime_grounding",
]
