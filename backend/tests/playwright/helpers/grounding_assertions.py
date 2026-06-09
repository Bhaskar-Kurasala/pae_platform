"""D18 Phase A CP5 — runtime grounding assertions.

Wraps the D15 CP3 runtime grounding verifier
(backend/tests/fixtures/runtime_grounding_verifier.py) in a
Phase-B-friendly assertion. Single source of truth: extraction +
suppression-list logic stays in the D15 module. CP5 just adapts it
to the assertion-error shape Phase B journey tests expect.

The D15 verifier requires a DB session because the legitimate-content
set is derived from the live DB (read_student_accessible_content
mirror). For Phase B journeys that don't have the agent's
student_id, an alternative form takes accessible_titles directly.

Why two forms:
  * `assert_no_runtime_grounding_violation_db` — the canonical path:
    pass student_id + role_slug; helper queries the DB for accessible
    titles and runs the full verifier.
  * `assert_no_runtime_grounding_violation` — minimal path: pass an
    explicit accessible_titles set (e.g., from a fixture that already
    knows what the seeded student can access). Skips the DB
    re-derivation; useful for unit-style tests where DB setup cost
    isn't justified.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# Reuse D15 verifier — single source of truth for extraction +
# suppression-list logic. Importing the private LEGITIMATE set so
# CP5 helpers don't drift if D15 expands the role-name vocabulary.
from tests.fixtures.runtime_grounding_verifier import (
    _LEGITIMATE_ROLE_REFERENCES,  # type: ignore[attr-defined]
    extract_content_references,
    verify_runtime_grounding,
)


def assert_no_runtime_grounding_violation(
    agent_response_text: str | dict[str, Any],
    accessible_content_titles: set[str],
    extra_legitimate_names: set[str] | None = None,
) -> None:
    """Assert agent output references only accessible content + role names.

    Extracts candidate content references via the D15 extractor, then
    flags any reference NOT in:
      * accessible_content_titles (per-student catalog)
      * _LEGITIMATE_ROLE_REFERENCES (D15 role + platform vocabulary)
      * extra_legitimate_names (caller-supplied additions)

    The error message lists every fabricated name + the field path
    where it was extracted (e.g., "response.text"), so investigators
    can grep the agent output directly.
    """
    legitimate = (
        set(accessible_content_titles)
        | _LEGITIMATE_ROLE_REFERENCES
        | (extra_legitimate_names or set())
    )
    candidates = extract_content_references(agent_response_text)
    violations = [
        (name, where)
        for name, where in candidates
        if name.strip() not in legitimate
    ]
    if not violations:
        return
    bullets = "\n  - ".join(
        f"{name!r} at {where}" for name, where in violations
    )
    raise AssertionError(
        "Runtime grounding violation: agent output references content "
        "not in the student's accessible set:\n  - "
        + bullets
        + f"\n(legitimate set had {len(legitimate)} names)"
    )


async def assert_no_runtime_grounding_violation_db(
    db_session: AsyncSession,
    *,
    agent_output: str | dict[str, Any],
    student_id: Any,
    role_slug: str | None,
    extra_legitimate_names: set[str] | None = None,
) -> None:
    """DB-grounded version: re-derives accessible titles for `student_id`.

    Mirrors the D15 verify_runtime_grounding signature but raises
    AssertionError on findings rather than returning the verification
    object. Use this when the test has a real seeded student and
    wants to assert against the actual entitlement state.

    The D15 verifier returns a GroundingVerification object with a
    `findings` list; we surface its content as the assertion message.
    """
    verification = await verify_runtime_grounding(
        db_session,
        agent_output=agent_output,
        student_id=student_id,
        role_slug=role_slug,
        extra_legitimate_names=extra_legitimate_names,
    )
    if not verification.findings:
        return
    bullets = "\n  - ".join(
        f"{f.extracted_name!r} at {f.where_seen} ({f.severity})"
        for f in verification.findings
    )
    raise AssertionError(
        f"Runtime grounding violation for student {student_id} "
        f"(role={role_slug}):\n  - " + bullets
    )


__all__ = [
    "assert_no_runtime_grounding_violation",
    "assert_no_runtime_grounding_violation_db",
]
