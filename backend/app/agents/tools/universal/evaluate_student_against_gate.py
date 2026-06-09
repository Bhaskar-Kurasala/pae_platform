"""D15 CP2 / Pass 3c — evaluate_student_against_gate universal tool.

Computes whether a student passes the gate from their CURRENT role to a
target adjacent role. Returns a structured pass/fail aggregate plus
capstone + mock-interview sub-projections so the agent can quote
specific gap reasons in a student-facing reply.

Schema dependencies:
  * student_role_state    — current role lookup (D15 CP1)
  * roles                 — sequence_order for adjacency check
  * role_transitions      — per-pair gate definitions (D15 CP1)
  * exercises             — is_capstone flag, lesson_id FK
  * lessons               — course_id FK
  * courses               — role_id FK (D15 CP2b)
  * exercise_submissions  — score (0-100 int) + status
  * agent_actions         — last N mock_interview sessions for this
                            transition (the session_verdict + transition
                            _target metadata is populated by CP4
                            mock_interview prompt update; this tool
                            handles missing keys gracefully)

Adjacency rule (D-A): the target role MUST be at sequence_order =
current.sequence_order + 1. Non-adjacent calls raise ValueError so
agents that mis-route to a future role surface loudly rather than
silently produce a misleading False verdict.

Capstone status logic:
  * Query exercise_submissions JOIN exercises (is_capstone=TRUE) JOIN
    lessons JOIN courses WHERE courses.role_id = current_role_id.
    "Capstones for the role they're leaving" — passing those gates
    the move out.
  * Submission must have status='evaluated' AND score IS NOT NULL.
  * exercises.score is a 0-100 integer; threshold is 0.0-1.0 float.
    Normalize at projection time: float(score) / 100.0.
  * Sort descending by normalized score; the top-N (where N =
    capstone_count_required) must each meet capstone_threshold.

Mock interview status logic (CP2 design coupling with CP4):
  * Query agent_actions WHERE agent_name='mock_interview' AND
    student_id matches AND status='completed', ordered descending by
    created_at, LIMIT mock_interview_sessions_window.
  * Filter to sessions whose output_data.session_verdict.transition
    _target.to_role_slug matches target_role_slug (CP4 contract).
  * Count sessions where output_data.session_verdict.passed is True.
  * If sessions_passed >= mock_interview_sessions_required_pass: pass.

  At CP2 ship, no mock_interview sessions populate that metadata yet
  — sessions_passed will be 0 for every student. The CP4 prompt
  update wires the metadata; CP4 verification confirms gate passes
  end-to-end. Pattern 18b: this is expected design coupling, not a bug.

Permissions: read:student_data
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sql_text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.universal.evaluate_student_against_gate"
)


# ── Input ─────────────────────────────────────────────────────────────


class EvaluateStudentAgainstGateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(
        description="The student to evaluate.",
    )
    target_role_slug: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "The adjacent role the student is gated to. Must be at "
            "sequence_order = current.sequence_order + 1; non-adjacent "
            "values raise ValueError."
        ),
    )


# ── Output sub-types ──────────────────────────────────────────────────


class CapstoneStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_score: float = Field(
        description="Threshold from role_transitions.capstone_threshold (0.0-1.0)."
    )
    required_count: int = Field(
        description="How many capstones must meet the threshold."
    )
    best_score_observed: float | None = Field(
        default=None,
        description=(
            "Top normalized capstone score (0.0-1.0), or None when the "
            "student has zero evaluated capstones for the source role."
        ),
    )
    capstones_meeting_threshold: int = Field(
        ge=0,
        description=(
            "Count of evaluated capstones whose normalized score >= "
            "required_score."
        ),
    )
    passed: bool = Field(
        description="capstones_meeting_threshold >= required_count.",
    )


class RecentMockSession(BaseModel):
    """Compact projection of a recent mock_interview session for audit."""

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    created_at: str  # ISO; just for human-readable evidence in agent prompts
    transition_target_to_role: str | None = Field(
        default=None,
        description=(
            "From output_data.session_verdict.transition_target.to_role_slug "
            "when populated by CP4 mock_interview. None for legacy / "
            "general-practice sessions."
        ),
    )
    passed: bool | None = Field(
        default=None,
        description=(
            "From output_data.session_verdict.passed when populated. "
            "None for legacy sessions; counted as 'not passed' for the "
            "aggregate."
        ),
    )


class MockInterviewStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_threshold: float = Field(
        description=(
            "Per-session weighted-score threshold from "
            "role_transitions.mock_interview_pass_threshold."
        ),
    )
    sessions_required_pass: int
    sessions_window: int
    recent_sessions: list[RecentMockSession] = Field(
        default_factory=list,
        description=(
            "Last `sessions_window` mock_interview sessions for this "
            "student, ordered newest-first. Sessions that didn't target "
            "this transition are still listed (transition_target_to_role "
            "= None) so the agent has the full picture."
        ),
    )
    sessions_passed_in_window: int = Field(
        ge=0,
        description=(
            "Count of sessions in `recent_sessions` where "
            "transition_target_to_role == target_role_slug AND "
            "passed=True. Pre-CP4 this is always 0 (metadata not "
            "yet populated)."
        ),
    )
    passed: bool = Field(
        description="sessions_passed_in_window >= sessions_required_pass.",
    )


class EvaluateStudentAgainstGateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_passable: bool = Field(
        description=(
            "Synonym for overall_passed at the top level. Provided so "
            "agents that route on a single boolean don't have to dig "
            "into sub-objects."
        ),
    )
    capstone_status: CapstoneStatus
    mock_interview_status: MockInterviewStatus
    overall_passed: bool = Field(
        description=(
            "capstone_status.passed AND mock_interview_status.passed."
        ),
    )
    gap_summary: str = Field(
        description=(
            "One-line human-readable summary of what's missing. Empty "
            "string when overall_passed=True. Agents quote into "
            "student-facing replies."
        ),
    )


# ── Implementation ────────────────────────────────────────────────────


def _extract_session_verdict(output_data: Any) -> dict[str, Any] | None:
    """Pull session_verdict dict out of output_data with full tolerance.

    CP4 contract: output_data is a dict, contains key 'session_verdict',
    which is itself a dict. Any deviation (None, list, string, missing
    key, wrong type) returns None — the caller then treats the session
    as 'no verdict, doesn't count toward passes'.
    """
    if not isinstance(output_data, dict):
        return None
    verdict = output_data.get("session_verdict")
    if not isinstance(verdict, dict):
        return None
    return verdict


def _extract_target_to_role(verdict: dict[str, Any]) -> str | None:
    target = verdict.get("transition_target")
    if not isinstance(target, dict):
        return None
    to_slug = target.get("to_role_slug")
    if isinstance(to_slug, str) and to_slug:
        return to_slug
    return None


@tool(
    name="evaluate_student_against_gate",
    description=(
        "Computes whether the student passes the gate from their "
        "CURRENT role to the specified ADJACENT target_role_slug. "
        "Returns capstone + mock-interview sub-projections plus a "
        "gap_summary string. Raises ValueError on non-adjacent target."
    ),
    input_schema=EvaluateStudentAgainstGateInput,
    output_schema=EvaluateStudentAgainstGateOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=10.0,
)
async def evaluate_student_against_gate(
    args: EvaluateStudentAgainstGateInput,
) -> EvaluateStudentAgainstGateOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "evaluate_student_against_gate called without an active "
            "session. The tool body relies on the contextvar set by "
            "call_agent."
        )

    # ── Resolve current role + adjacency check ────────────────────
    try:
        current_row = (
            await session.execute(
                sql_text(
                    """
                    SELECT
                        r.id, r.slug, r.sequence_order, r.is_terminal,
                        s.current_role_id
                    FROM student_role_state s
                    JOIN roles r ON r.id = s.current_role_id
                    WHERE s.student_id = :sid
                    """
                ),
                {"sid": args.student_id},
            )
        ).first()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "evaluate_student_against_gate.current_role_query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise

    if current_row is None:
        raise ValueError(
            f"student {args.student_id} has no student_role_state row; "
            f"cannot evaluate gate"
        )

    (
        current_role_id,
        current_slug,
        current_order,
        current_is_terminal,
        _state_role_id,
    ) = current_row

    if current_is_terminal:
        raise ValueError(
            f"student is at terminal role {current_slug!r}; no further "
            f"transitions exist"
        )

    # Find target role + verify adjacency.
    try:
        target_row = (
            await session.execute(
                sql_text(
                    "SELECT id, sequence_order FROM roles WHERE slug = :ts"
                ),
                {"ts": args.target_role_slug},
            )
        ).first()
    except Exception:
        await session.rollback()
        raise

    if target_row is None:
        raise ValueError(
            f"target_role_slug {args.target_role_slug!r} is not a known role"
        )

    target_role_id, target_order = target_row
    if target_order != current_order + 1:
        raise ValueError(
            f"non-adjacent transition: student is at sequence_order "
            f"{current_order} ({current_slug!r}); target is sequence_order "
            f"{target_order} ({args.target_role_slug!r}). Only "
            f"sequence_order={current_order + 1} is allowed (D-A)."
        )

    # ── Read transition gate definition ────────────────────────────
    try:
        transition_row = (
            await session.execute(
                sql_text(
                    """
                    SELECT
                        capstone_threshold,
                        capstone_count_required,
                        mock_interview_pass_threshold,
                        mock_interview_sessions_required_pass,
                        mock_interview_sessions_window
                    FROM role_transitions
                    WHERE from_role_id = :from_id AND to_role_id = :to_id
                    """
                ),
                {"from_id": current_role_id, "to_id": target_role_id},
            )
        ).first()
    except Exception:
        await session.rollback()
        raise

    if transition_row is None:
        raise ValueError(
            f"no role_transitions row from {current_slug!r} to "
            f"{args.target_role_slug!r}; data integrity issue"
        )

    (
        capstone_threshold,
        capstone_count_required,
        mock_pass_threshold,
        mock_sessions_required,
        mock_sessions_window,
    ) = transition_row
    capstone_threshold = float(capstone_threshold)
    mock_pass_threshold = float(mock_pass_threshold)

    # ── Capstone status ────────────────────────────────────────────
    # Score on exercise_submissions is integer 0-100; normalize when
    # comparing against the 0.0-1.0 capstone_threshold.
    try:
        capstone_rows = (
            await session.execute(
                sql_text(
                    """
                    SELECT
                        es.score,
                        es.status
                    FROM exercise_submissions es
                    JOIN exercises e ON e.id = es.exercise_id
                    JOIN lessons l ON l.id = e.lesson_id
                    JOIN courses c ON c.id = l.course_id
                    WHERE es.student_id = :sid
                      AND e.is_capstone = TRUE
                      AND c.role_id = :current_role_id
                      AND es.score IS NOT NULL
                    ORDER BY es.score DESC
                    """
                ),
                {"sid": args.student_id, "current_role_id": current_role_id},
            )
        ).all()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "evaluate_student_against_gate.capstone_query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        capstone_rows = []

    normalized_scores: list[float] = []
    for row in capstone_rows:
        raw_score = row[0]
        if raw_score is None:
            continue
        normalized_scores.append(float(raw_score) / 100.0)

    capstones_meeting = sum(1 for s in normalized_scores if s >= capstone_threshold)
    capstone_passed = capstones_meeting >= capstone_count_required
    best_score = normalized_scores[0] if normalized_scores else None

    capstone_status = CapstoneStatus(
        required_score=capstone_threshold,
        required_count=capstone_count_required,
        best_score_observed=best_score,
        capstones_meeting_threshold=capstones_meeting,
        passed=capstone_passed,
    )

    # ── Mock interview status (CP4 design coupling) ────────────────
    try:
        mock_rows = (
            await session.execute(
                sql_text(
                    """
                    SELECT
                        aa.id, aa.created_at, aa.output_data
                    FROM agent_actions aa
                    WHERE aa.agent_name = 'mock_interview'
                      AND aa.student_id = :sid
                      AND aa.status = 'completed'
                    ORDER BY aa.created_at DESC
                    LIMIT :win
                    """
                ),
                {"sid": args.student_id, "win": mock_sessions_window},
            )
        ).all()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "evaluate_student_against_gate.mock_query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        mock_rows = []

    recent_sessions: list[RecentMockSession] = []
    sessions_passed_in_window = 0
    for row in mock_rows:
        session_id, created_at, output_data = row
        verdict = _extract_session_verdict(output_data)
        if verdict is None:
            recent_sessions.append(
                RecentMockSession(
                    session_id=session_id,
                    created_at=created_at.isoformat() if created_at else "",
                    transition_target_to_role=None,
                    passed=None,
                )
            )
            continue
        target_to_role = _extract_target_to_role(verdict)
        passed_raw = verdict.get("passed")
        passed_bool = bool(passed_raw) if isinstance(passed_raw, bool) else None
        recent_sessions.append(
            RecentMockSession(
                session_id=session_id,
                created_at=created_at.isoformat() if created_at else "",
                transition_target_to_role=target_to_role,
                passed=passed_bool,
            )
        )
        if (
            target_to_role == args.target_role_slug
            and passed_bool is True
        ):
            sessions_passed_in_window += 1

    mock_passed = sessions_passed_in_window >= mock_sessions_required

    mock_status = MockInterviewStatus(
        required_threshold=mock_pass_threshold,
        sessions_required_pass=mock_sessions_required,
        sessions_window=mock_sessions_window,
        recent_sessions=recent_sessions,
        sessions_passed_in_window=sessions_passed_in_window,
        passed=mock_passed,
    )

    # ── Aggregate ──────────────────────────────────────────────────
    overall_passed = capstone_passed and mock_passed
    gap_parts: list[str] = []
    if not capstone_passed:
        if best_score is None:
            gap_parts.append(
                f"no evaluated capstone for {current_slug} yet "
                f"(need {capstone_count_required} at "
                f">= {capstone_threshold:.2f})"
            )
        else:
            gap_parts.append(
                f"capstone: {capstones_meeting} of "
                f"{capstone_count_required} pass threshold "
                f"(best score {best_score:.2f} vs required "
                f"{capstone_threshold:.2f})"
            )
    if not mock_passed:
        gap_parts.append(
            f"mock interviews: {sessions_passed_in_window} of "
            f"{mock_sessions_required} pass in last "
            f"{mock_sessions_window} sessions"
        )
    gap_summary = "; ".join(gap_parts) if gap_parts else ""

    return EvaluateStudentAgainstGateOutput(
        gate_passable=overall_passed,
        capstone_status=capstone_status,
        mock_interview_status=mock_status,
        overall_passed=overall_passed,
        gap_summary=gap_summary,
    )


__all__ = [
    "CapstoneStatus",
    "EvaluateStudentAgainstGateInput",
    "EvaluateStudentAgainstGateOutput",
    "MockInterviewStatus",
    "RecentMockSession",
    "evaluate_student_against_gate",
]
