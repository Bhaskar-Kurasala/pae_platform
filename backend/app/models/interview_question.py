"""InterviewQuestion model for career module (#169)."""

import uuid

from sqlalchemy import JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)  # ["python", "llm"]
    difficulty: Mapped[str] = mapped_column(
        String(20), default="medium", nullable=False
    )  # easy|medium|hard
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        String(50), default="technical", nullable=False
    )  # technical|behavioral
