"""AgentInvocationLog — unified per-LLM-call cost log across agents.

Replaces the per-agent ad-hoc cost tables. As of migration 0040 every new
agent (readiness diagnostic, JD decoder, future agents) writes directly to
this table; the resume agent and mock interview agent dual-write here while
their legacy tables (``generation_logs``, ``mock_cost_log``) remain the
authoritative source of truth for one release. Once the parallel-read
verification gate passes for 100 consecutive checks, the read path flips.

Sunset target for the dual-write window: **2026-05-09**.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgentInvocationLog(Base):
    __tablename__ = "agent_invocation_log"
    __table_args__ = (
        sa.Index("ix_agent_invocation_log_user_source", "user_id", "source"),
        sa.Index("ix_agent_invocation_log_source_id", "source", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # source: which agent / feature emitted this invocation
    #   resume_generation | mock_session | diagnostic_session | jd_decode
    source: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    # source_id: parent business object (TailoredResume.id, InterviewSession.id,
    # ReadinessDiagnosticSession.id, JdAnalysis.id). Stored as string so we
    # don't have to fan out FKs across heterogeneous parents.
    source_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    # sub_agent: granular role within the source — interviewer, scorer,
    # verdict_generator, jd_analyst, match_scorer, tailoring_agent, ...
    sub_agent: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    model: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    tokens_in: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    tokens_out: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    cost_inr: Mapped[float] = mapped_column(
        sa.Float, nullable=False, default=0.0, server_default="0.0"
    )
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    # status: cost-bearing outcome only.
    #   succeeded     — call returned a usable response
    #   failed        — call raised; tokens / cost may still be non-zero
    #   cap_exceeded  — circuit breaker fired before the call
    # Lifecycle stages (started, downloaded, quota_blocked, ...) belong to
    # the agent's own state machine, NOT here.
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )


# Source / status constants — keep in lockstep with the column comments.
SOURCE_RESUME = "resume_generation"
SOURCE_MOCK = "mock_session"
SOURCE_DIAGNOSTIC = "diagnostic_session"
SOURCE_JD_DECODE = "jd_decode"

STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CAP_EXCEEDED = "cap_exceeded"

# The two statuses that count toward the resume agent's quota check.
# `failed` is included by deliberate design — see quota_service for the rationale.
QUOTA_CONSUMING_STATUSES: tuple[str, ...] = (STATUS_SUCCEEDED, STATUS_FAILED)
