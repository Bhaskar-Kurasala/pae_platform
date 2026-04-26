"""Readiness diagnostic data models.

Four tables back the conversational "Am I Ready?" diagnostic agent:

* ``ReadinessStudentSnapshot`` — denormalized cache of verified student
  data at a point in time. Shared with the JD decoder (its match scorer
  reads the same evidence). TTL ~1h.
* ``ReadinessDiagnosticSession`` — one row per conversation. Holds the
  snapshot ref, lifecycle timestamps, and the north-star fields
  (``next_action_clicked_at``, ``next_action_completed_at``).
* ``ReadinessDiagnosticTurn`` — message-level transcript for the
  conversation (role + content).
* ``ReadinessVerdict`` — structured output (headline / evidence /
  next-action) emitted by the VerdictGenerator at the end of a session.

Cost is recorded externally via ``agent_invocation_log`` (source =
``diagnostic_session``, source_id = the session UUID). No ``cost_inr``
column on these tables — see ``cost-log-refactor.IMPLEMENTATION_NOTES.md``
for the rationale.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReadinessStudentSnapshot(Base):
    """Cached, denormalized view of the student's verified evidence.

    Both the diagnostic and the JD decoder read this. The
    ``evidence_allowlist`` is the only set of ``evidence_id`` values that
    downstream LLM outputs are permitted to cite — see
    ``readiness_evidence_validator.py``.
    """

    __tablename__ = "readiness_student_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Compact JSON the LLM sees. Contains: lessons_completed,
    # exercises_submitted, capstones_shipped, mocks_taken, recent_mock_scores,
    # peer_review_count, weakness_ledger_open, resume_freshness_days,
    # time_on_task_minutes, target_role, ...
    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    # Set of evidence_id strings the LLM may cite. Stored as a JSON list
    # for portability between SQLite (tests) and Postgres (prod).
    evidence_allowlist: Mapped[list[str]] = mapped_column(
        sa.JSON, nullable=False, default=list
    )
    built_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )


class ReadinessDiagnosticSession(Base):
    """One row per conversational diagnostic session."""

    __tablename__ = "readiness_diagnostic_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "readiness_student_snapshots.id", ondelete="SET NULL"
        ),
        nullable=True,
    )
    verdict_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "readiness_verdicts.id", ondelete="SET NULL", use_alter=True
        ),
        nullable=True,
    )
    # active | finalizing | completed | abandoned
    status: Mapped[str] = mapped_column(
        sa.String(20), nullable=False, default="active"
    )
    turns_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0
    )
    # North-star metric fields (populated by the click-beacon endpoint
    # and the 24h completion check; see commit 10).
    next_action_clicked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    next_action_completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class ReadinessDiagnosticTurn(Base):
    """One row per conversation message."""

    __tablename__ = "readiness_diagnostic_turns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "readiness_diagnostic_sessions.id", ondelete="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    # student | agent
    role: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Free-form metadata: control tokens captured from the agent
    # (READY_FOR_VERDICT, INVOKE_JD_DECODER, ...), latency, etc.
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        sa.JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )


class ReadinessVerdict(Base):
    """Structured output of the VerdictGenerator.

    The ``evidence`` list is an array of ``{text, evidence_id, source_url,
    kind}`` dicts where ``kind`` is one of ``strength | gap | neutral``.
    The validator rejects rows where any ``evidence_id`` is not in the
    paired snapshot's ``evidence_allowlist``.
    """

    __tablename__ = "readiness_verdicts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "readiness_diagnostic_sessions.id", ondelete="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    headline: Mapped[str] = mapped_column(sa.String(280), nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        sa.JSON, nullable=False, default=list
    )
    # Action intent (e.g. skills_gap, interview_gap, jd_target_unclear,
    # ready_but_stalling, thin_data) — feeds the rule-based router.
    next_action_intent: Mapped[str] = mapped_column(
        sa.String(40), nullable=False
    )
    # Resolved deep-link route the UI deep-links to.
    next_action_route: Mapped[str] = mapped_column(
        sa.String(255), nullable=False
    )
    # Short user-facing label for the CTA button.
    next_action_label: Mapped[str] = mapped_column(
        sa.String(120), nullable=False
    )
    # Snapshot of the model used and validation outcome for audit /
    # anti-sycophancy review. Never gates the user-facing path.
    model: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    validation: Mapped[dict[str, Any] | None] = mapped_column(
        sa.JSON, nullable=True
    )
    sycophancy_flags: Mapped[list[str] | None] = mapped_column(
        sa.JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


# Status / next-action constants — keep in lockstep with the route table
# in app/services/readiness_action_router.py.

DIAGNOSTIC_STATUS_ACTIVE = "active"
DIAGNOSTIC_STATUS_FINALIZING = "finalizing"
DIAGNOSTIC_STATUS_COMPLETED = "completed"
DIAGNOSTIC_STATUS_ABANDONED = "abandoned"

# Conversational soft cap. After 8 turns the orchestrator gracefully
# wraps and finalizes — see readiness_orchestrator.py.
MAX_TURNS = 8
