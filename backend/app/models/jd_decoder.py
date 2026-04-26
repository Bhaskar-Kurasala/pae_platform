"""JD decoder data models.

Two tables back the JD Decoder agent:

* ``JdAnalysis`` — hash-keyed cache of decoded JDs. The decode itself is
  user-independent (must-haves, wishlist, filler flags, seniority read,
  culture signals are all properties of the JD text), so the cache is
  shared across students. Hash collisions on a 64-char SHA-256 hex are
  not a practical concern.
* ``JdMatchScore`` — per-student × JD score. Distinct from JdAnalysis
  because the score depends on the student's ``StudentSnapshot`` at
  scoring time.

Distinct from ``jd_library`` (which is the user's saved-JD list with
its own keyword-extraction lineage). JdAnalysis is the LLM-decoded
artifact; jd_library is the student's bookmark.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JdAnalysis(Base):
    """Decoded JD — universal across users."""

    __tablename__ = "jd_analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # SHA-256 hex of the normalized JD text. Unique — cache key.
    jd_hash: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, unique=True, index=True
    )
    # Truncated JD text (first 4000 chars) so analysts can spot-check the
    # decode against the source. Full text lives on jd_library if the
    # student saved it.
    jd_text_truncated: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Output of the JDParser stage (parse_jd) — must_haves, nice_to_haves,
    # role, seniority, etc. Same shape as ParsedJd.to_dict().
    parsed: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    # Output of the JDAnalyst stage. Adds: filler_flags (list of phrases
    # explained), seniority_read (string), culture_signals (list of
    # {pattern, severity, note}), wishlist_inflated (bool: "12 must-haves
    # listed but only 4 are real").
    analysis: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    model: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )


class JdMatchScore(Base):
    """Per-student × JD match score. Score is null when snapshot is too
    thin to ground a faithful match — see MatchScorer."""

    __tablename__ = "jd_match_scores"
    __table_args__ = (
        sa.Index("ix_jd_match_scores_user_jd", "user_id", "jd_analysis_id"),
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
    jd_analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("jd_analyses.id", ondelete="CASCADE"),
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
    # 0–100, or null when the snapshot was too thin to ground a score.
    score: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    # Short headline for the user — e.g. "Strong match on Python and APIs;
    # missing system design exposure."
    headline: Mapped[str] = mapped_column(sa.String(280), nullable=False)
    # 3-5 evidence chips (same shape as ReadinessVerdict.evidence). Each
    # cites an evidence_id from the paired snapshot's allowlist.
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        sa.JSON, nullable=False, default=list
    )
    # Action intent — same vocabulary as the diagnostic's
    # next_action_intent. Lets the action router treat both surfaces
    # identically.
    next_action_intent: Mapped[str] = mapped_column(
        sa.String(40), nullable=False
    )
    next_action_route: Mapped[str] = mapped_column(
        sa.String(255), nullable=False
    )
    next_action_label: Mapped[str] = mapped_column(
        sa.String(120), nullable=False
    )
    model: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    validation: Mapped[dict[str, Any] | None] = mapped_column(
        sa.JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
