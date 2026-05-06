"""D12 / Pass 3d §E.2 — read_mastery_summary for career_coach.

Returns top strengths and weaknesses by mastery score from agent_memory.
Reads memory keys under mastery:* for this student.

Permissions: read:student_data
"""

from __future__ import annotations

import uuid

import structlog
from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.memory import MemoryStore
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.career_coach.read_mastery_summary"
)


class ReadMasterySummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student whose mastery to summarize.")
    top_n: int = Field(default=5, ge=1, le=20)


class MasteryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept: str
    mastery_score: float
    valence: float


class ReadMasterySummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strengths: list[MasteryEntry] = Field(default_factory=list)
    weaknesses: list[MasteryEntry] = Field(default_factory=list)
    total_concepts_tracked: int = Field(ge=0)


@tool(
    name="read_mastery_summary",
    description=(
        "Returns the student's top strengths and weaknesses by mastery. "
        "Reads mastery:* memory keys, ranks by valence. Used by "
        "career_coach to surface real skill gaps and strengths when "
        "building a personalized career plan."
    ),
    input_schema=ReadMasterySummaryInput,
    output_schema=ReadMasterySummaryOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def read_mastery_summary(
    args: ReadMasterySummaryInput,
) -> ReadMasterySummaryOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_mastery_summary called without an active session."
        )

    try:
        store = MemoryStore(session)
        rows = await store.recall(
            "mastery:",
            user_id=args.student_id,
            agent_name="career_coach",
            scope="user",
            k=50,
            mode="structured",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_mastery_summary.recall_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "read_mastery_summary.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return ReadMasterySummaryOutput(
            strengths=[], weaknesses=[], total_concepts_tracked=0
        )

    entries: list[MasteryEntry] = []
    for row in rows:
        if not row.key.startswith("mastery:"):
            continue
        concept = row.key.removeprefix("mastery:")
        score = float(row.value.get("score", 0.0)) if isinstance(row.value, dict) else 0.0
        entries.append(
            MasteryEntry(
                concept=concept,
                mastery_score=score,
                valence=float(row.valence or 0.0),
            )
        )

    strengths = sorted(
        [e for e in entries if e.valence >= 0], key=lambda e: e.valence, reverse=True
    )[: args.top_n]
    weaknesses = sorted(
        [e for e in entries if e.valence < 0], key=lambda e: e.valence
    )[: args.top_n]

    return ReadMasterySummaryOutput(
        strengths=strengths,
        weaknesses=weaknesses,
        total_concepts_tracked=len(entries),
    )


__all__ = [
    "MasteryEntry",
    "ReadMasterySummaryInput",
    "ReadMasterySummaryOutput",
    "read_mastery_summary",
]
