"""LessonAsset — multi-asset attachment for a lesson.

A lesson is composed of one or more assets:
  * 1 learning_notebook  — the lecture notebook the student reads/runs first
  * 2-3 practice_notebook — reinforcement notebooks (each runnable)
  * 1 video              — Mux-hosted explainer
  * 0-1 capstone_brief   — markdown brief for the course-end capstone
  * 0-N reading          — auxiliary markdown reading

`storage_ref` is opaque and decoded by the asset's kind:
  - kind='video'  → Mux playback_id (signed playback JWTs minted at request time)
  - kind in {learning_notebook, practice_notebook} → R2 object key for the .ipynb
  - kind in {capstone_brief, reading} → R2 object key for markdown
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin

ASSET_KIND_LEARNING_NOTEBOOK = "learning_notebook"
ASSET_KIND_PRACTICE_NOTEBOOK = "practice_notebook"
ASSET_KIND_VIDEO = "video"
ASSET_KIND_CAPSTONE_BRIEF = "capstone_brief"
ASSET_KIND_READING = "reading"
# Admin pastes a public GitHub URL (or org/repo[#branch]); the player
# renders an "Open in GitHub" / "Open in Colab" link. Repo content is
# NOT proxied — we trust the host. For private repo proxying use the
# existing GITHUB_CONTENT_TOKEN flow.
ASSET_KIND_GIT_REPO = "git_repo"

ASSET_KINDS: frozenset[str] = frozenset(
    {
        ASSET_KIND_LEARNING_NOTEBOOK,
        ASSET_KIND_PRACTICE_NOTEBOOK,
        ASSET_KIND_VIDEO,
        ASSET_KIND_CAPSTONE_BRIEF,
        ASSET_KIND_READING,
        ASSET_KIND_GIT_REPO,
    }
)

NOTEBOOK_KINDS: frozenset[str] = frozenset(
    {ASSET_KIND_LEARNING_NOTEBOOK, ASSET_KIND_PRACTICE_NOTEBOOK}
)


class LessonAsset(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "lesson_assets"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('learning_notebook','practice_notebook','video',"
            "'capstone_brief','reading','git_repo')",
            name="ck_lesson_assets_kind",
        ),
        Index("ix_lesson_assets_lesson_id_order", "lesson_id", "order"),
    )

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    lesson: Mapped["Lesson"] = relationship(back_populates="assets")  # noqa: F821


from app.models.lesson import Lesson  # noqa: E402,F401
