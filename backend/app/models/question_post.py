"""Question wall (P3 3B #102, folds #103 upvote, #108 flag).

One table for questions *and* answers — `parent_id` is null for
top-level questions, set for replies. Upvote / flag counters are
denormalized integers; individual vote/flag rows live in the separate
`question_votes` table.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDMixin


class QuestionPost(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "question_posts"

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("question_posts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    body: Mapped[str] = mapped_column(String(4000), nullable=False)
    upvote_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    flag_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class QuestionVote(Base, UUIDMixin, TimestampMixin):
    """Per-user upvote/flag record; dedups via (post, voter, kind)."""

    __tablename__ = "question_votes"
    __table_args__ = (
        UniqueConstraint(
            "post_id",
            "voter_id",
            "kind",
            name="uq_question_votes_post_voter_kind",
        ),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("question_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    voter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "upvote" or "flag"
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
