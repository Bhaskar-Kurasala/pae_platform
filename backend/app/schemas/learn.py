"""Pydantic schemas for the lesson player ("Learn") feature.

Boundary contract for /api/v1/learn routes. The timeline endpoint is the
single payload that hydrates the Learn screen — one round-trip surfaces
every lesson, its assets, the per-lesson lock state, and the per-asset
progress for the current student.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Asset + progress projections
# ---------------------------------------------------------------------------


AssetKind = Literal[
    "learning_notebook",
    "practice_notebook",
    "video",
    "capstone_brief",
    "reading",
]

AssetStatus = Literal["not_started", "in_progress", "completed"]
LessonLockState = Literal["locked", "unlocked", "completed"]


class AssetProgressOut(BaseModel):
    status: AssetStatus = "not_started"
    watch_pct: float = 0.0
    last_position_seconds: int = 0
    watched_seconds: int = 0
    execution_count: int = 0
    executed_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class LessonAssetOut(BaseModel):
    id: uuid.UUID
    kind: AssetKind
    order: int
    title: str
    description: str | None = None
    duration_seconds: int | None = None
    # storage_ref is INTENTIONALLY excluded — clients fetch the signed
    # URL or playback token through dedicated endpoints rather than ever
    # seeing the opaque key. Prevents leaking R2 keys / Mux playback IDs
    # to anyone who calls /api/v1/learn/timeline without entitlement.
    progress: AssetProgressOut = Field(default_factory=AssetProgressOut)

    model_config = ConfigDict(from_attributes=True)


class LessonNodeOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    slug: str
    order: int
    description: str | None = None
    duration_seconds: int = 0
    is_capstone: bool = False
    lock_state: LessonLockState = "locked"
    locked_reason: str | None = None
    completion_pct: float = 0.0
    completed_at: datetime | None = None
    assets: list[LessonAssetOut] = Field(default_factory=list)
    requires_lesson_ids: list[uuid.UUID] = Field(default_factory=list)


class LearnTimelineResponse(BaseModel):
    course_id: uuid.UUID
    course_slug: str
    course_title: str
    is_entitled: bool
    lessons: list[LessonNodeOut] = Field(default_factory=list)
    capstone_unlocked: bool = False
    progress_pct: float = 0.0


# ---------------------------------------------------------------------------
# Asset access (signed URLs / playback tokens)
# ---------------------------------------------------------------------------


class NotebookSignedUrlResponse(BaseModel):
    asset_id: uuid.UUID
    url: str
    expires_at: datetime
    # The JupyterLite-prefilled launch URL: pointed at our hosted
    # JupyterLite, with the signed notebook URL passed as the `fromURL`
    # query parameter so the kernel fetches and opens it on load.
    launch_url: str


class VideoPlaybackTokenResponse(BaseModel):
    asset_id: uuid.UUID
    playback_id: str
    token: str
    expires_at: datetime


# ---------------------------------------------------------------------------
# Progress mutations
# ---------------------------------------------------------------------------


class AssetProgressUpdate(BaseModel):
    """Client → server delta. All fields optional; only set what changed.

    Watch position updates flow primarily through the Mux webhook, but
    the player also POSTs `last_position_seconds` periodically so a
    refresh resumes near the right spot even before the webhook lands.
    """

    watch_pct: float | None = Field(default=None, ge=0.0, le=1.0)
    watched_seconds: int | None = Field(default=None, ge=0)
    last_position_seconds: int | None = Field(default=None, ge=0)
    mark_executed: bool = False


class MarkLessonCompleteRequest(BaseModel):
    """Manual "I'm done with this lesson" trigger.

    Server still re-verifies the completion policy — this endpoint
    cannot bypass policy, only trigger the check explicitly so the UI
    can prompt the student.
    """

    note: str | None = None


class LessonCompletionResponse(BaseModel):
    lesson_id: uuid.UUID
    completed: bool
    completion_pct: float
    # Lessons that just unlocked because of this completion. The frontend
    # uses this to animate the next-card.
    newly_unlocked_lesson_ids: list[uuid.UUID] = Field(default_factory=list)
    # When `completed` is False, this names the missing requirement(s).
    blocking_reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Active-course / enrolled-courses summary — drives the merged Path screen.
# ---------------------------------------------------------------------------


class EnrolledCourseSummary(BaseModel):
    """One row per course the student has actually started studying.

    "Started" = at least one student_asset_progress row exists. Free
    catalog browse access alone does NOT enroll a student here.
    """

    course_id: uuid.UUID
    course_slug: str
    course_title: str
    progress_pct: float = 0.0
    total_lessons: int = 0
    completed_lessons: int = 0
    last_touched_at: datetime | None = None


class ActiveCourseResponse(BaseModel):
    """The single course the student should resume on the Path screen.

    Resolution order (Path-merge §A):
      1. Most-recently-touched (max student_asset_progress.updated_at).
      2. None if the student hasn't started any course yet — frontend
         then renders the catalog upsell card.
    """

    active_course_id: uuid.UUID | None = None
    enrolled_courses: list[EnrolledCourseSummary] = Field(default_factory=list)
