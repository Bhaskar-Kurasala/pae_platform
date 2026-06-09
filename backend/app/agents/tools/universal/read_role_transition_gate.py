"""D15 CP4 — read_role_transition_gate universal tool.

Returns a single role_transitions row's gate definition for a specific
adjacent (from_role, to_role) pair. Used by:

  * project_evaluator (CP4b D-G gate-context awareness): when evaluating
    a capstone, fetch the gate threshold for the student's current role
    so transition_gate_status can be populated.
  * mock_interview (CP4c gate-prep verdict): when the candidate signals
    gate-prep intent, fetch the relevant transition's
    mock_interview_dimensions + threshold so the session can score
    against the correct rubric.

Distinct from evaluate_student_against_gate (CP2): that tool consumes
student state + capstone history + recent mock sessions to produce a
pass/fail verdict. THIS tool is a pure read of the transition's
DEFINITION — no student state, no aggregation. Cheap, deterministic.

Adjacency check: same as evaluate_student_against_gate (D-A invariant).
Raises ValueError if (from, to) doesn't exist OR is non-adjacent. The
caller is expected to derive (from, to) from authoritative role state,
so this is a programmer-error guard rather than a user-facing message.

Permissions: read:student_data — same convention as the other CP2 tools.
The data is platform metadata, but accessing it from agent code goes
through the same per-student execution context, so the permission tier
matches.
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sql_text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.universal.read_role_transition_gate"
)


# ── Input ─────────────────────────────────────────────────────────────


class ReadRoleTransitionGateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_role_slug: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "The role being transitioned OUT of (the student's "
            "current role at evaluation time)."
        ),
    )
    to_role_slug: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "The role being transitioned INTO. MUST be sequence_order = "
            "from.sequence_order + 1; non-adjacent values raise."
        ),
    )


# ── Output ────────────────────────────────────────────────────────────


class ReadRoleTransitionGateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    found: bool = Field(
        description=(
            "True iff the (from, to) pair resolves to a real adjacent "
            "transition. False collapses every other field to defaults."
        ),
    )
    from_role_slug: str
    to_role_slug: str
    capstone_threshold: float = Field(
        description="Per role_transitions.capstone_threshold (0.0-1.0).",
    )
    capstone_count_required: int = Field(
        description="How many capstones must meet the threshold.",
    )
    mock_interview_dimensions: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Rubric mapping dimension_name → weight. Weights sum to 1.0. "
            "mock_interview reads this to score the session."
        ),
    )
    mock_interview_pass_threshold: float = Field(
        description=(
            "Weighted-score threshold for a single session to count as "
            "passing."
        ),
    )
    mock_interview_sessions_required_pass: int
    mock_interview_sessions_window: int
    gate_summary: str = Field(
        description=(
            "One-line human-readable summary; agents may quote into "
            "narrative feedback."
        ),
    )


# ── Implementation ────────────────────────────────────────────────────


@tool(
    name="read_role_transition_gate",
    description=(
        "Returns the gate definition (capstone threshold + mock "
        "interview dimensions/threshold + window) for a specific "
        "adjacent (from_role, to_role) pair. Pure read of "
        "role_transitions metadata — no student state. Used by "
        "project_evaluator for D-G gate-context awareness and "
        "mock_interview for gate-prep session scoring. Raises on "
        "non-adjacent pair."
    ),
    input_schema=ReadRoleTransitionGateInput,
    output_schema=ReadRoleTransitionGateOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def read_role_transition_gate(
    args: ReadRoleTransitionGateInput,
) -> ReadRoleTransitionGateOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_role_transition_gate called without an active session."
        )

    try:
        row = (
            await session.execute(
                sql_text(
                    """
                    SELECT
                        rt.capstone_threshold,
                        rt.capstone_count_required,
                        rt.mock_interview_dimensions,
                        rt.mock_interview_pass_threshold,
                        rt.mock_interview_sessions_required_pass,
                        rt.mock_interview_sessions_window,
                        f.sequence_order AS from_order,
                        t.sequence_order AS to_order
                    FROM role_transitions rt
                    JOIN roles f ON f.id = rt.from_role_id
                    JOIN roles t ON t.id = rt.to_role_id
                    WHERE f.slug = :from_slug AND t.slug = :to_slug
                    """
                ),
                {
                    "from_slug": args.from_role_slug,
                    "to_slug": args.to_role_slug,
                },
            )
        ).first()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_role_transition_gate.query_failed",
            error=str(exc),
            from_slug=args.from_role_slug,
            to_slug=args.to_role_slug,
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        # Empty-output projection on query failure — keeps callers'
        # downstream handling consistent with "transition not found".
        return ReadRoleTransitionGateOutput(
            found=False,
            from_role_slug=args.from_role_slug,
            to_role_slug=args.to_role_slug,
            capstone_threshold=0.0,
            capstone_count_required=0,
            mock_interview_dimensions={},
            mock_interview_pass_threshold=0.0,
            mock_interview_sessions_required_pass=0,
            mock_interview_sessions_window=0,
            gate_summary="(transition not found)",
        )

    if row is None:
        raise ValueError(
            f"no role_transitions row from {args.from_role_slug!r} to "
            f"{args.to_role_slug!r}"
        )

    (
        capstone_t,
        capstone_n,
        mock_dims_raw,
        mock_pass_t,
        mock_required,
        mock_window,
        from_order,
        to_order,
    ) = row

    if to_order != from_order + 1:
        raise ValueError(
            f"non-adjacent transition: {args.from_role_slug!r} (order "
            f"{from_order}) → {args.to_role_slug!r} (order {to_order}); "
            f"only sequence_order={from_order + 1} is allowed (D-A)."
        )

    mock_dims: dict[str, float] = {}
    if isinstance(mock_dims_raw, dict):
        for k, v in mock_dims_raw.items():
            if isinstance(v, (int, float)):
                mock_dims[str(k)] = float(v)

    capstone_t_f = float(capstone_t)
    mock_pass_t_f = float(mock_pass_t)

    return ReadRoleTransitionGateOutput(
        found=True,
        from_role_slug=args.from_role_slug,
        to_role_slug=args.to_role_slug,
        capstone_threshold=capstone_t_f,
        capstone_count_required=capstone_n,
        mock_interview_dimensions=mock_dims,
        mock_interview_pass_threshold=mock_pass_t_f,
        mock_interview_sessions_required_pass=mock_required,
        mock_interview_sessions_window=mock_window,
        gate_summary=(
            f"capstone score >= {capstone_t_f:.2f} (need {capstone_n}) "
            f"AND {mock_required} of last {mock_window} mock interviews "
            f">= {mock_pass_t_f:.2f}"
        ),
    )


__all__ = [
    "ReadRoleTransitionGateInput",
    "ReadRoleTransitionGateOutput",
    "read_role_transition_gate",
]
