"""Student-state tools.

Read + write the per-student signals every agent ends up needing
(progress, skill mastery, in-app messages, scheduled review prompts).

These are the four tools that drive most "Engagement Watchdog" /
"Learning Coach" behavior — agents read state, decide an action,
write state or queue a message.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.tools import tool


# ── get_student_state ───────────────────────────────────────────────


class GetStudentStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    include_progress: bool = True
    include_skills: bool = True
    include_recent_activity: bool = True


class StudentSnapshot(BaseModel):
    """Compact summary an agent reads on entry.

    Designed so a single recall_memory + get_student_state pair gives
    the agent enough context to reason without burning more tool
    calls. Keep this lean — wide nested structures bloat prompts.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    full_name: str | None = None
    email: str | None = None
    is_active: bool = True
    days_since_signup: int | None = None
    days_since_last_login: int | None = None
    overall_progress_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    active_course_title: str | None = None
    skill_summary: dict[str, str] | None = Field(
        default=None,
        description=(
            "skill_slug → mastery_level (novice|proficient|mastered) for "
            "the top ~10 most-recently-touched skills."
        ),
    )
    last_activity_at: datetime | None = None


class GetStudentStateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: StudentSnapshot


@tool(
    name="get_student_state",
    description=(
        "Read a compact snapshot of the student: identity, progress, "
        "skill summary, recency of last activity. Designed to be the "
        "first call most agents make on entry."
    ),
    input_schema=GetStudentStateInput,
    output_schema=GetStudentStateOutput,
    requires=("read:student",),
    cost_estimate=0.0,  # pure DB read
    is_stub=True,
)
async def get_student_state(args: GetStudentStateInput) -> GetStudentStateOutput:
    raise NotImplementedError(
        "stub: real implementation joins users, enrollments, "
        "student_progress, user_skill_states. Lands in DX after the "
        "AgenticBaseAgent wires session injection."
    )


# ── update_mastery ──────────────────────────────────────────────────


class UpdateMasteryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    skill_id: uuid.UUID
    mastery_level: Literal["novice", "proficient", "mastered"]
    confidence_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    source_event: str = Field(
        ...,
        max_length=120,
        description=(
            "Free-form anchor for the audit trail — e.g. "
            "'lesson:completed:<id>' or 'quiz:passed:<id>'. Helps "
            "answer 'why did mastery move?' six weeks from now."
        ),
    )


class UpdateMasteryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updated: bool
    previous_level: Literal["novice", "proficient", "mastered"] | None
    new_level: Literal["novice", "proficient", "mastered"]


@tool(
    name="update_mastery",
    description=(
        "Set or update the student's mastery level for a single skill. "
        "Includes a `source_event` audit anchor so we can trace why "
        "mastery moved without spelunking through agent_actions."
    ),
    input_schema=UpdateMasteryInput,
    output_schema=UpdateMasteryOutput,
    requires=("write:student_skill_state",),
    cost_estimate=0.0,
    is_stub=True,
)
async def update_mastery(args: UpdateMasteryInput) -> UpdateMasteryOutput:
    raise NotImplementedError(
        "stub: real implementation upserts user_skill_states with the "
        "audit anchor. Lands once the AgenticBaseAgent wires session "
        "injection (DX)."
    )


# ── send_student_message ────────────────────────────────────────────


class SendStudentMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    kind: Literal["nudge", "celebration", "job_brief", "review_due", "insight"]
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    cta_label: str | None = Field(default=None, max_length=80)
    cta_url: str | None = Field(default=None, max_length=2000)
    expires_at: datetime | None = None
    idempotency_key: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Per-user dedup key. If present, a second call with the "
            "same (user_id, idempotency_key) is a no-op upsert "
            "instead of a duplicate inbox row. Required for any "
            "send fired from a Celery task or webhook."
        ),
    )


class SendStudentMessageOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbox_id: uuid.UUID
    deduped: bool = Field(
        description=(
            "True iff a row already existed for this idempotency key; "
            "in that case `inbox_id` points to the existing row."
        ),
    )


@tool(
    name="send_student_message",
    description=(
        "Post a card to the student_inbox table. Visible in the "
        "in-app inbox. Honours idempotency_key so cron / webhook "
        "retries don't multiply cards."
    ),
    input_schema=SendStudentMessageInput,
    output_schema=SendStudentMessageOutput,
    requires=("write:student_inbox",),
    cost_estimate=0.0,
    is_stub=True,
)
async def send_student_message(
    args: SendStudentMessageInput,
) -> SendStudentMessageOutput:
    raise NotImplementedError(
        "stub: real implementation inserts into student_inbox with the "
        "partial unique index handling for idempotency_key. Lands once "
        "AgenticBaseAgent wires session injection."
    )


# ── schedule_review ─────────────────────────────────────────────────


class ScheduleReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    skill_id: uuid.UUID | None = None
    lesson_id: uuid.UUID | None = None
    due_at: datetime
    reason: str = Field(
        max_length=200,
        description=(
            "Why we're scheduling this — e.g. 'mastery dropped to "
            "novice after quiz fail'. Surfaced to the student in the "
            "inbox card we eventually fire from this entry."
        ),
    )


class ScheduleReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: uuid.UUID
    due_at: datetime


@tool(
    name="schedule_review",
    description=(
        "Schedule a spaced-repetition review prompt for a skill or "
        "lesson. Drops a row that the proactive primitive picks up "
        "via cron, computes a card, and posts to student_inbox at "
        "`due_at`."
    ),
    input_schema=ScheduleReviewInput,
    output_schema=ScheduleReviewOutput,
    requires=("write:srs_cards",),
    cost_estimate=0.0,
    is_stub=True,
)
async def schedule_review(args: ScheduleReviewInput) -> ScheduleReviewOutput:
    raise NotImplementedError(
        "stub: real implementation queues a row in srs_cards (or a "
        "new table dedicated to agentic reviews) with due_at. Lands "
        "once AgenticBaseAgent wires session injection."
    )
