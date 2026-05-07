"""Role progression models — D15 CP1.

Three models — `Role`, `RoleTransition`, `StudentRoleState` — that back
the runtime role progression infrastructure. Six roles + five transitions
are seeded by alembic migration 0061; existing students are backfilled
to python_developer by 0062.

Agents read these tables via three new tools (CP2):
  * read_student_role_state(student_id)
  * read_student_accessible_content(student_id, role_slug=None)
  * evaluate_student_against_gate(student_id, target_role_slug)

The models are intentionally thin — no behavior, no relationships beyond
the FK shapes the tools and tests depend on. Business logic (gate
evaluation, transition completion) lives at the tool/agent layer, not on
the model.

Slug constants below mirror the seeded roles. Importing modules should
prefer these constants over string literals so a future rename surfaces
as a type-check error rather than a silent miss.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ROLE_SLUG_PYTHON_DEVELOPER = "python_developer"
ROLE_SLUG_DATA_ANALYST = "data_analyst"
ROLE_SLUG_DATA_SCIENTIST = "data_scientist"
ROLE_SLUG_ML_ENGINEER = "ml_engineer"
ROLE_SLUG_GENAI_ENGINEER = "genai_engineer"
ROLE_SLUG_SENIOR_GENAI_ENGINEER = "senior_genai_engineer"

ROLE_SLUGS_IN_ORDER: list[str] = [
    ROLE_SLUG_PYTHON_DEVELOPER,
    ROLE_SLUG_DATA_ANALYST,
    ROLE_SLUG_DATA_SCIENTIST,
    ROLE_SLUG_ML_ENGINEER,
    ROLE_SLUG_GENAI_ENGINEER,
    ROLE_SLUG_SENIOR_GENAI_ENGINEER,
]


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("slug", name="roles_slug_key"),
        UniqueConstraint("sequence_order", name="roles_sequence_order_key"),
        CheckConstraint("sequence_order >= 1", name="roles_sequence_order_pos"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_terminal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    role_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default="{}",
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RoleTransition(Base):
    __tablename__ = "role_transitions"
    __table_args__ = (
        UniqueConstraint(
            "from_role_id", "to_role_id", name="role_transitions_pair_key"
        ),
        CheckConstraint(
            "capstone_threshold BETWEEN 0.0 AND 1.0",
            name="role_transitions_capstone_threshold_range",
        ),
        CheckConstraint(
            "mock_interview_pass_threshold BETWEEN 0.0 AND 1.0",
            name="role_transitions_mock_threshold_range",
        ),
        CheckConstraint(
            "capstone_count_required >= 1",
            name="role_transitions_capstone_count_pos",
        ),
        CheckConstraint(
            "mock_interview_sessions_required_pass >= 1",
            name="role_transitions_mock_sessions_required_pos",
        ),
        CheckConstraint(
            "mock_interview_sessions_window >= mock_interview_sessions_required_pass",
            name="role_transitions_window_gte_required",
        ),
        CheckConstraint(
            "from_role_id <> to_role_id", name="role_transitions_no_self_loop"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    from_role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    to_role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    capstone_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    capstone_count_required: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1", default=1
    )
    mock_interview_dimensions: Mapped[dict[str, float]] = mapped_column(
        JSONB, nullable=False
    )
    mock_interview_pass_threshold: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    mock_interview_sessions_required_pass: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="2", default=2
    )
    mock_interview_sessions_window: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="3", default=3
    )
    additional_gate_logic: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StudentRoleState(Base):
    __tablename__ = "student_role_state"
    __table_args__ = (
        UniqueConstraint("student_id", name="student_role_state_student_uniq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    current_role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    transitions_completed: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    gates_attempted: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    state_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default="{}",
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
