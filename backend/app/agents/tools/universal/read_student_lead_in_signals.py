"""D17b/ITEM 3 Phase 0 — read_student_lead_in_signals universal tool.

Aggregates the deterministic state signals career_coach + study_planner
prompts branch on for their D17b state-aware lead-in sections. Single
tool call returns a flat record; the prompt's lead-in firing decision
is computable from these structured fields without LLM judgment
(Pattern 26 canonical shape: deterministic state aggregation, LLM
fills templates).

Signal sources (all read in one tool body, single round-trip-friendly):

  * days_since_last_session — student_risk_signals.days_since_last_session
    when present (populated nightly by F1 risk_scoring); falls back to
    `(now() - users.last_login_at) days` when no risk row exists yet
    (new user, never scored).
  * most_recent_mock_pass_at — most recent agent_actions row where
    agent_name='mock_interview', status='completed', and the JSONB
    output_data['session_verdict']['passed'] is true. Mirrors the verdict
    extraction in evaluate_student_against_gate (single source of truth
    for what "passed" means; do not reinvent).
  * most_recent_transition_completed_at — last element of
    student_role_state.transitions_completed JSONB array (.completed_at).
    Same shape read_student_role_state already projects, surfaced flat
    here for trigger-decision ergonomics.
  * current_slip_type — student_risk_signals.slip_type (or None).
  * recent_activity_days_count_7d — distinct-DATE count of
    learning_sessions.started_at in last 7 days. The "activity" proxy
    used by study_planner's momentum trigger (relaxed from "consecutive
    days" because consecutive-streak data isn't queryable cheaply; this
    proxy is "≥3 active days in last 7" per the Option A scope).

Edge cases:
  * Student with no student_risk_signals row → days_since_last_session
    derives from last_login_at; current_slip_type=None.
  * Student with no learning_sessions → recent_activity_days_count_7d=0.
  * Student with no completed mock interviews → most_recent_mock_pass_at=None.
  * Student who has never transitioned → most_recent_transition_completed_at=None.

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

log = structlog.get_logger().bind(
    layer="tools.universal.read_student_lead_in_signals"
)


# ── Input ─────────────────────────────────────────────────────────────


class ReadStudentLeadInSignalsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(
        description=(
            "The student whose lead-in signals to aggregate. Required; "
            "the tool does NOT fall back to the active-session user_id "
            "because admin/simulator paths may need to read other "
            "students' state."
        ),
    )


# ── Output ────────────────────────────────────────────────────────────


class ReadStudentLeadInSignalsOutput(BaseModel):
    """Flat structured signals the prompt branches on.

    Every field is independently None-able: a brand-new student with
    no signals at all returns the all-None / zero shape, and the
    prompt's lead-in decision logic correctly resolves to "no lead-in
    fires; handle the question directly."
    """

    model_config = ConfigDict(extra="forbid")

    days_since_last_session: int | None = Field(
        default=None,
        description=(
            "Days since the student's most recent session; None if "
            "no sessions ever exist (e.g. fresh signup who has never "
            "logged in)."
        ),
    )
    most_recent_mock_pass_at: datetime | None = Field(
        default=None,
        description=(
            "Timestamp of the most recent mock_interview agent_action "
            "where session_verdict.passed=true; None if no passing "
            "mocks exist."
        ),
    )
    most_recent_transition_completed_at: datetime | None = Field(
        default=None,
        description=(
            "Timestamp when the student last cleared a role gate; None "
            "if never transitioned. Read from "
            "student_role_state.transitions_completed[-1].completed_at."
        ),
    )
    current_slip_type: str | None = Field(
        default=None,
        description=(
            "Current student_risk_signals.slip_type or None (no risk "
            "row yet, or slip_type='none')."
        ),
    )
    recent_activity_days_count_7d: int = Field(
        default=0,
        ge=0,
        le=7,
        description=(
            "Number of distinct calendar days in the last 7 with at "
            "least one learning_sessions.started_at row. Used by "
            "study_planner's momentum trigger as a proxy for "
            "consecutive-days streak (the strict streak shape isn't "
            "queryable cheaply from the existing schema)."
        ),
    )


# ── Implementation ────────────────────────────────────────────────────


@tool(
    name="read_student_lead_in_signals",
    description=(
        "Aggregates deterministic state signals career_coach + "
        "study_planner branch on for their state-aware lead-in "
        "sections: days_since_last_session, most_recent_mock_pass_at, "
        "most_recent_transition_completed_at, current_slip_type, "
        "recent_activity_days_count_7d. Single tool call; the prompt "
        "decides which lead-in template to fill based on the returned "
        "structured fields."
    ),
    input_schema=ReadStudentLeadInSignalsInput,
    output_schema=ReadStudentLeadInSignalsOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=8.0,
)
async def read_student_lead_in_signals(
    args: ReadStudentLeadInSignalsInput,
) -> ReadStudentLeadInSignalsOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_student_lead_in_signals called without an active "
            "session. The tool body relies on the contextvar set by "
            "call_agent."
        )

    sid = args.student_id

    # ── Defensive aggregation: each signal in its own try/except so
    # one bad row doesn't blank the whole record. asyncpg-rollback
    # discipline applies — a failed query rolls back the session
    # before the next one runs.

    days_since_last_session: int | None = None
    current_slip_type: str | None = None
    try:
        risk_row = (
            await session.execute(
                sql_text(
                    """
                    SELECT days_since_last_session, slip_type
                    FROM student_risk_signals
                    WHERE user_id = :sid
                    """
                ),
                {"sid": sid},
            )
        ).first()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_student_lead_in_signals.risk_query_failed",
            error=str(exc),
            student_id=str(sid),
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        risk_row = None

    if risk_row is not None:
        raw_days, raw_slip = risk_row
        days_since_last_session = (
            int(raw_days) if raw_days is not None else None
        )
        # Treat slip_type='none' as None for the prompt's branching
        # ergonomics — "no slip" should not trigger a stalled lead-in.
        if isinstance(raw_slip, str) and raw_slip and raw_slip != "none":
            current_slip_type = raw_slip

    # Fallback: when no risk row, derive days from users.last_login_at.
    if days_since_last_session is None:
        try:
            login_row = (
                await session.execute(
                    sql_text(
                        """
                        SELECT
                            EXTRACT(DAY FROM (now() - last_login_at))::int
                              AS days_since_last_login
                        FROM users
                        WHERE id = :sid
                        """
                    ),
                    {"sid": sid},
                )
            ).first()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "read_student_lead_in_signals.login_query_failed",
                error=str(exc),
                student_id=str(sid),
            )
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            login_row = None
        if login_row is not None and login_row[0] is not None:
            days_since_last_session = int(login_row[0])

    # ── Most recent passing mock_interview action ──────────────────
    # Mirror evaluate_student_against_gate's verdict-extraction logic:
    # output_data['session_verdict']['passed'] is the canonical pass
    # signal. We project the row in SQL with a JSONB filter so the
    # tool doesn't pull every mock action into Python.
    most_recent_mock_pass_at: datetime | None = None
    try:
        mock_row = (
            await session.execute(
                sql_text(
                    """
                    SELECT created_at
                    FROM agent_actions
                    WHERE agent_name = 'mock_interview'
                      AND student_id = :sid
                      AND status = 'completed'
                      AND output_data->'session_verdict'->>'passed' = 'true'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"sid": sid},
            )
        ).first()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_student_lead_in_signals.mock_query_failed",
            error=str(exc),
            student_id=str(sid),
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        mock_row = None
    if mock_row is not None:
        most_recent_mock_pass_at = mock_row[0]

    # ── Most recent transition completion ──────────────────────────
    # transitions_completed is a JSONB array of {from_slug, to_slug,
    # completed_at, ...}. Extract the highest-timestamp .completed_at
    # in SQL; null when array is empty or no .completed_at field.
    most_recent_transition_completed_at: datetime | None = None
    try:
        trans_row = (
            await session.execute(
                sql_text(
                    """
                    SELECT MAX(
                        (elem->>'completed_at')::timestamptz
                    ) AS most_recent
                    FROM student_role_state s,
                         jsonb_array_elements(s.transitions_completed) AS elem
                    WHERE s.student_id = :sid
                      AND elem->>'completed_at' IS NOT NULL
                    """
                ),
                {"sid": sid},
            )
        ).first()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_student_lead_in_signals.transition_query_failed",
            error=str(exc),
            student_id=str(sid),
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        trans_row = None
    if trans_row is not None and trans_row[0] is not None:
        most_recent_transition_completed_at = trans_row[0]

    # ── Recent activity proxy ──────────────────────────────────────
    # Distinct-DATE count over the 7-day window. The activity bar is
    # at least one learning_sessions.started_at row that day — same
    # signal the today/page surfaces, so prompt + UX stay aligned.
    recent_activity_days_count_7d = 0
    try:
        activity_row = (
            await session.execute(
                sql_text(
                    """
                    SELECT COUNT(DISTINCT DATE(started_at))
                    FROM learning_sessions
                    WHERE user_id = :sid
                      AND started_at > now() - interval '7 days'
                    """
                ),
                {"sid": sid},
            )
        ).first()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_student_lead_in_signals.activity_query_failed",
            error=str(exc),
            student_id=str(sid),
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        activity_row = None
    if activity_row is not None and activity_row[0] is not None:
        recent_activity_days_count_7d = min(7, int(activity_row[0]))

    return ReadStudentLeadInSignalsOutput(
        days_since_last_session=days_since_last_session,
        most_recent_mock_pass_at=most_recent_mock_pass_at,
        most_recent_transition_completed_at=most_recent_transition_completed_at,
        current_slip_type=current_slip_type,
        recent_activity_days_count_7d=recent_activity_days_count_7d,
    )


__all__ = [
    "ReadStudentLeadInSignalsInput",
    "ReadStudentLeadInSignalsOutput",
    "read_student_lead_in_signals",
]
