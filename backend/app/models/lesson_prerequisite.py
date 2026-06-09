"""LessonPrerequisite — directed edges in the lesson DAG.

`(lesson_id, requires_lesson_id)` means: lesson_id is locked for a student
until they have completed requires_lesson_id. Composite PK prevents
duplicate edges; the CHECK constraint blocks self-loops.

There is no model-level cycle check — admins authoring the DAG are
trusted, and the prerequisite walker in LessonAccessService is depth-
limited as a defensive backstop.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LessonPrerequisite(Base):
    __tablename__ = "lesson_prerequisites"
    __table_args__ = (
        PrimaryKeyConstraint("lesson_id", "requires_lesson_id"),
        CheckConstraint(
            "lesson_id <> requires_lesson_id",
            name="ck_lesson_prerequisites_no_self_loop",
        ),
    )

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    requires_lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
