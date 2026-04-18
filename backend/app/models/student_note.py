import uuid

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class StudentNote(Base, UUIDMixin, TimestampMixin):
    """Admin-authored intervention note on a specific student.

    The admin support ticket (P3 3A-18): when an admin sees a struggling
    student in the at-risk list, they need a place to jot "saw him stuck
    on embeddings, reached out 3/14" so the next admin in the rotation
    has continuity. Notes are append-only — edits and deletes would
    destroy the audit trail we want.

    Both FKs cascade on user deletion so notes don't survive a GDPR
    erase of either party.
    """

    __tablename__ = "student_notes"

    admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
