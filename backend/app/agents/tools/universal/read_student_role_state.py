"""D15 CP2 / Pass 3c — read_student_role_state universal tool.

Returns the student's current role identity, time-in-role, completed
transitions, and a summary of the next transition's gate. Five updated
agents (career_coach, study_planner, practice_curator, project_evaluator,
mock_interview) read this per CP3-CP4 prompt updates so they can adjust
voice and content based on where the student is in the linear role
progression.

Schema dependencies (D15 CP1):
  * roles                 — six identity rows seeded by 0061
  * role_transitions      — five gate definitions seeded by 0061
  * student_role_state    — one row per student, backfilled by 0062

`found=False` when the student has no student_role_state row. Should
never happen for an active user post-0062, but the tool handles it
gracefully — agents read `found` and short-circuit to a sane default
("treat as python_developer") rather than fabricating identity.

`next_transition.gate_summary` is a one-line string the agent can
quote verbatim into a student-facing reply ("you need a capstone at
0.65+ AND 2 of your last 3 mock interviews to pass at 0.65+"). The
structured `target_role_slug` is the input to evaluate_student_against
_gate when the agent wants the actual pass/fail computation.

Permissions: read:student_data
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sql_text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(layer="tools.universal.read_student_role_state")


# ── Input ─────────────────────────────────────────────────────────────


class ReadStudentRoleStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(
        description=(
            "The student whose role state to look up. Required; the "
            "tool does NOT fall back to the active-session user_id "
            "because agents may need to read other students' state "
            "(admin views, simulator scenarios)."
        ),
    )


# ── Output sub-types ──────────────────────────────────────────────────


class CurrentRoleProjection(BaseModel):
    """The student's current role, projected for agent prompts."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    display_name: str
    description: str = Field(
        description=(
            "The role's identity statement — agents quote this into "
            "their prompts to set the student-facing voice."
        ),
    )
    sequence_order: int
    is_terminal: bool


class CompletedTransitionRecord(BaseModel):
    """One entry in transitions_completed JSONB array."""

    model_config = ConfigDict(extra="forbid")

    from_slug: str
    to_slug: str
    completed_at: datetime | None = None
    capstone_score: float | None = None
    mock_session_ids: list[str] = Field(default_factory=list)


class NextTransitionSummary(BaseModel):
    """Compact gate summary for the next transition; None at terminal."""

    model_config = ConfigDict(extra="forbid")

    target_role_slug: str = Field(
        description=(
            "The role the student is gated to next. Pass to "
            "evaluate_student_against_gate(target_role_slug=...) for "
            "the full pass/fail computation."
        ),
    )
    gate_summary: str = Field(
        description=(
            "One-line human-readable threshold summary. Agents may "
            "quote this verbatim or rephrase. Format: 'capstone "
            "score >= X.XX (need Y) AND Z of last W mock interviews "
            ">= V.VV'."
        ),
    )


# ── Output ────────────────────────────────────────────────────────────


class ReadStudentRoleStateOutput(BaseModel):
    """Full role state projection.

    `found=False` collapses every other field to a default — agents
    should branch on `found` first and never assume a current_role
    when found is False.
    """

    model_config = ConfigDict(extra="forbid")

    found: bool
    current_role: CurrentRoleProjection | None = None
    role_started_at: datetime | None = None
    days_in_role: int | None = Field(
        default=None,
        description=(
            "Whole days since role_started_at. NULL when found=False. "
            "Computed at query time via Postgres date arithmetic."
        ),
    )
    transitions_completed: list[CompletedTransitionRecord] = Field(
        default_factory=list,
        description=(
            "Append-only history of completed transitions. Empty list "
            "= student has not transitioned yet."
        ),
    )
    next_transition: NextTransitionSummary | None = Field(
        default=None,
        description=(
            "Summary of the next adjacent transition's gate. None when "
            "the student is at the terminal role (senior_genai_engineer) "
            "OR when found=False."
        ),
    )


# ── Implementation ────────────────────────────────────────────────────


def _coerce_completed_record(raw: Any) -> CompletedTransitionRecord | None:
    """Best-effort projection of a transitions_completed JSONB element.

    Returns None for entries we can't make sense of so the caller can
    drop them rather than blow up the whole tool call. transitions_
    completed is append-only so old entries with looser shape are
    expected to coexist with strict-shape new entries.
    """
    if not isinstance(raw, dict):
        return None
    from_slug = raw.get("from_slug")
    to_slug = raw.get("to_slug")
    if not isinstance(from_slug, str) or not isinstance(to_slug, str):
        return None
    completed_at_raw = raw.get("completed_at")
    completed_at: datetime | None = None
    if isinstance(completed_at_raw, str):
        # Postgres returns ISO-formatted strings out of JSONB. Parse
        # leniently; on failure leave as None rather than crash.
        try:
            completed_at = datetime.fromisoformat(
                completed_at_raw.replace("Z", "+00:00")
            )
        except ValueError:
            completed_at = None
    elif isinstance(completed_at_raw, datetime):
        completed_at = completed_at_raw

    capstone_score = raw.get("capstone_score")
    if not isinstance(capstone_score, (int, float)):
        capstone_score = None

    mock_session_ids_raw = raw.get("mock_session_ids", []) or []
    mock_session_ids = [
        str(sid)
        for sid in mock_session_ids_raw
        if isinstance(sid, (str, uuid.UUID))
    ]

    return CompletedTransitionRecord(
        from_slug=from_slug,
        to_slug=to_slug,
        completed_at=completed_at,
        capstone_score=float(capstone_score) if capstone_score is not None else None,
        mock_session_ids=mock_session_ids,
    )


@tool(
    name="read_student_role_state",
    description=(
        "Returns the student's current role identity (slug, display "
        "name, description), time in role, completed transitions, and "
        "a summary of the next gate. Use to ground every prompt in "
        "the student's actual role state — never fabricate or assume."
    ),
    input_schema=ReadStudentRoleStateInput,
    output_schema=ReadStudentRoleStateOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=8.0,
)
async def read_student_role_state(
    args: ReadStudentRoleStateInput,
) -> ReadStudentRoleStateOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_student_role_state called without an active session. "
            "The tool body relies on the contextvar set by call_agent."
        )

    try:
        # ── Read current role + state in one round trip ────────────
        result = await session.execute(
            sql_text(
                """
                SELECT
                    r.slug,
                    r.display_name,
                    r.description,
                    r.sequence_order,
                    r.is_terminal,
                    s.role_started_at,
                    EXTRACT(DAY FROM (now() - s.role_started_at))::int AS days_in_role,
                    s.transitions_completed
                FROM student_role_state s
                JOIN roles r ON r.id = s.current_role_id
                WHERE s.student_id = :sid
                """
            ),
            {"sid": args.student_id},
        )
        row = result.first()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_student_role_state.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "read_student_role_state.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return ReadStudentRoleStateOutput(found=False)

    if row is None:
        return ReadStudentRoleStateOutput(found=False)

    (
        slug,
        display_name,
        description,
        sequence_order,
        is_terminal,
        role_started_at,
        days_in_role,
        transitions_raw,
    ) = row

    current_role = CurrentRoleProjection(
        slug=slug,
        display_name=display_name,
        description=description,
        sequence_order=sequence_order,
        is_terminal=is_terminal,
    )

    completed: list[CompletedTransitionRecord] = []
    if isinstance(transitions_raw, list):
        for entry in transitions_raw:
            projected = _coerce_completed_record(entry)
            if projected is not None:
                completed.append(projected)

    # ── Resolve next transition (None at terminal) ─────────────────
    next_transition: NextTransitionSummary | None = None
    if not is_terminal:
        try:
            next_row = (
                await session.execute(
                    sql_text(
                        """
                        SELECT
                            t.slug AS to_slug,
                            rt.capstone_threshold,
                            rt.capstone_count_required,
                            rt.mock_interview_pass_threshold,
                            rt.mock_interview_sessions_required_pass,
                            rt.mock_interview_sessions_window
                        FROM role_transitions rt
                        JOIN roles f ON f.id = rt.from_role_id
                        JOIN roles t ON t.id = rt.to_role_id
                        WHERE f.slug = :current_slug
                        """
                    ),
                    {"current_slug": slug},
                )
            ).first()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "read_student_role_state.next_transition_query_failed",
                error=str(exc),
                student_id=str(args.student_id),
            )
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            next_row = None

        if next_row is not None:
            (
                to_slug,
                capstone_t,
                capstone_n,
                mock_t,
                mock_required,
                mock_window,
            ) = next_row
            next_transition = NextTransitionSummary(
                target_role_slug=to_slug,
                gate_summary=(
                    f"capstone score >= {capstone_t:.2f} "
                    f"(need {capstone_n}) AND "
                    f"{mock_required} of last {mock_window} "
                    f"mock interviews >= {mock_t:.2f}"
                ),
            )

    return ReadStudentRoleStateOutput(
        found=True,
        current_role=current_role,
        role_started_at=role_started_at,
        days_in_role=int(days_in_role) if days_in_role is not None else None,
        transitions_completed=completed,
        next_transition=next_transition,
    )


__all__ = [
    "CompletedTransitionRecord",
    "CurrentRoleProjection",
    "NextTransitionSummary",
    "ReadStudentRoleStateInput",
    "ReadStudentRoleStateOutput",
    "read_student_role_state",
]
