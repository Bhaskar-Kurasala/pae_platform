import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class SkillEdge(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "skill_edges"
    __table_args__ = (
        UniqueConstraint(
            "from_skill_id", "to_skill_id", "edge_type",
            name="uq_skill_edges_triple",
        ),
        CheckConstraint(
            "from_skill_id <> to_skill_id",
            name="ck_skill_edges_no_self_loop",
        ),
    )

    from_skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    to_skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    edge_type: Mapped[str] = mapped_column(String(16), nullable=False)
