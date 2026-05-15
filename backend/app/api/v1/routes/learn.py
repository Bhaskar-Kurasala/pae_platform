"""Learn — course-locked notebook + video lesson player routes.

Single namespace ``/api/v1/learn`` for the entire feature surface:

  GET  /learn/courses/{course_id}/timeline
       Timeline payload: every lesson, lock state, per-asset progress.

  GET  /learn/assets/{asset_id}/notebook-url
       Mint a 5-min R2 presigned GET + JupyterLite launch URL.

  POST /learn/assets/{asset_id}/video-token
       Mint a short-lived Mux playback JWT.

  PATCH /learn/assets/{asset_id}/progress
       Apply a partial asset-progress delta (watch_pct, executed, etc.).

  POST /learn/lessons/{lesson_id}/complete
       Re-evaluate completion policy explicitly; flips lesson to done
       when all gates pass.

  POST /learn/webhooks/mux
       Mux webhook receiver. Signature-verified, dedup'd by event_id.

Every read/write enforces:
  1. Authenticated user (Depends(get_current_user))
  2. Course entitlement via LessonAccessService.has_course_access
  3. Per-asset/lesson lock check via prerequisite walker

The timeline endpoint never returns ``storage_ref`` — clients MUST
re-call /notebook-url or /video-token to get a freshly-signed URL,
which is the access-control boundary.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.impersonation import get_view_target_user
from app.core.security import get_current_user
from app.models.course import Course
from app.models.lesson import Lesson
from app.models.lesson_asset import (
    ASSET_KIND_VIDEO,
    NOTEBOOK_KINDS,
    LessonAsset,
)
from app.models.mux_webhook_event import MuxWebhookEvent
from app.models.user import User
from app.schemas.learn import (
    ActiveCourseResponse,
    AssetProgressOut,
    AssetProgressUpdate,
    EnrolledCourseSummary,
    LearnTimelineResponse,
    LessonAssetOut,
    LessonCompletionResponse,
    LessonNodeOut,
    MarkLessonCompleteRequest,
    NotebookSignedUrlResponse,
    VideoPlaybackTokenResponse,
)
from app.services import (
    asset_storage_service,
    enrolled_course_service,
    lesson_access_service,
    lesson_progress_service,
    mux_service,
)
from app.services.lesson_progress_service import AssetProgressDelta

log = structlog.get_logger()

router = APIRouter(prefix="/learn", tags=["learn"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_asset_with_access(
    db: AsyncSession, *, user: User, asset_id: uuid.UUID
) -> tuple[LessonAsset, Lesson]:
    """Load asset → lesson → course; enforce entitlement + unlock.

    Raises HTTPException with the right status code on failure so the
    callers stay one-line. Returns (asset, lesson) on success.
    """
    asset = await db.get(LessonAsset, asset_id)
    if asset is None or not asset.is_published:
        raise HTTPException(status_code=404, detail="Asset not found")
    lesson = await db.get(Lesson, asset.lesson_id)
    if lesson is None or not lesson.is_published:
        raise HTTPException(status_code=404, detail="Lesson not found")

    if user.role != "admin":
        entitled = await lesson_access_service.has_course_access(
            db, user_id=user.id, course_id=lesson.course_id
        )
        if not entitled:
            raise HTTPException(
                status_code=402,
                detail={
                    "reason": "enroll_required",
                    "course_id": str(lesson.course_id),
                },
            )
        unlocked, reason = (
            await lesson_access_service.is_lesson_unlocked_for_student(
                db, student_id=user.id, lesson_id=lesson.id
            )
        )
        if not unlocked:
            raise HTTPException(
                status_code=403,
                detail={
                    "reason": "lesson_locked",
                    "lesson_id": str(lesson.id),
                    "message": reason or "Lesson is locked",
                },
            )

    return asset, lesson


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


@router.get(
    "/courses/{course_id}/timeline",
    response_model=LearnTimelineResponse,
)
async def get_course_timeline(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    view_target: User = Depends(get_view_target_user),
) -> LearnTimelineResponse:
    """Single-payload state for the Learn screen.

    When admin is impersonating a student, ``view_target`` IS the
    student — we deliberately surface that student's exact lock states
    and progress so admin can reproduce what the student sees. The
    "admin sees everything" bypass below applies only when admin is
    viewing the timeline as themselves.
    """
    course = await db.get(Course, course_id)
    if course is None or not course.is_published:
        raise HTTPException(status_code=404, detail="Course not found")

    is_entitled = await lesson_access_service.has_course_access(
        db, user_id=view_target.id, course_id=course_id
    )

    if not is_entitled and view_target.role != "admin":
        # Render a "preview" timeline: lesson titles only, all locked.
        # The frontend uses this to show the upsell card without making
        # a separate "list lessons" call.
        lessons = await lesson_access_service.load_course_lessons(db, course_id)
        return LearnTimelineResponse(
            course_id=course.id,
            course_slug=course.slug,
            course_title=course.title,
            is_entitled=False,
            lessons=[
                LessonNodeOut(
                    id=lesson.id,
                    course_id=lesson.course_id,
                    title=lesson.title,
                    slug=lesson.slug,
                    order=lesson.order,
                    description=lesson.description,
                    duration_seconds=lesson.duration_seconds,
                    is_capstone=False,
                    lock_state="locked",
                    locked_reason="Enroll to unlock this lesson",
                    completion_pct=0.0,
                )
                for lesson in lessons
            ],
            capstone_unlocked=False,
            progress_pct=0.0,
        )

    states = await lesson_access_service.build_course_state(
        db, student_id=view_target.id, course_id=course_id
    )

    nodes: list[LessonNodeOut] = []
    completed_count = 0
    for state in states:
        if state.lock_state == "completed":
            completed_count += 1
        is_capstone = bool(
            state.lesson.metadata_
            and state.lesson.metadata_.get("is_capstone")
        )
        nodes.append(
            LessonNodeOut(
                id=state.lesson.id,
                course_id=state.lesson.course_id,
                title=state.lesson.title,
                slug=state.lesson.slug,
                order=state.lesson.order,
                description=state.lesson.description,
                duration_seconds=state.lesson.duration_seconds,
                is_capstone=is_capstone,
                lock_state=state.lock_state,  # type: ignore[arg-type]
                locked_reason=state.locked_reason,
                completion_pct=state.completion.completion_pct,
                completed_at=None,
                requires_lesson_ids=state.requires_lesson_ids,
                assets=[
                    LessonAssetOut(
                        id=asset.id,
                        kind=asset.kind,  # type: ignore[arg-type]
                        order=asset.order,
                        title=asset.title,
                        description=asset.description,
                        duration_seconds=asset.duration_seconds,
                        progress=AssetProgressOut.model_validate(
                            state.progress_by_asset[asset.id]
                        )
                        if asset.id in state.progress_by_asset
                        else AssetProgressOut(),
                    )
                    for asset in state.assets
                ],
            )
        )

    capstone_unlocked = (
        all(s.lock_state == "completed" for s in states[:-1]) if states else False
    )
    progress_pct = (completed_count / len(states)) if states else 0.0

    return LearnTimelineResponse(
        course_id=course.id,
        course_slug=course.slug,
        course_title=course.title,
        is_entitled=True,
        lessons=nodes,
        capstone_unlocked=capstone_unlocked,
        progress_pct=progress_pct,
    )


# ---------------------------------------------------------------------------
# Asset access
# ---------------------------------------------------------------------------


@router.get(
    "/assets/{asset_id}/notebook-url",
    response_model=NotebookSignedUrlResponse,
)
async def get_notebook_signed_url(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotebookSignedUrlResponse:
    asset, _lesson = await _resolve_asset_with_access(
        db, user=current_user, asset_id=asset_id
    )
    if asset.kind not in NOTEBOOK_KINDS and asset.kind not in {
        "capstone_brief",
        "reading",
    }:
        raise HTTPException(
            status_code=400,
            detail=f"Asset kind '{asset.kind}' is not a notebook/markdown asset",
        )

    signed = asset_storage_service.signed_notebook_url(asset.storage_ref)
    launch = asset_storage_service.jupyterlite_launch_url(signed.url)
    log.info(
        "learn.notebook_url_minted",
        student_id=str(current_user.id),
        asset_id=str(asset_id),
        signed=signed.signed,
    )
    return NotebookSignedUrlResponse(
        asset_id=asset_id,
        url=signed.url,
        expires_at=signed.expires_at,
        launch_url=launch,
    )


@router.post(
    "/assets/{asset_id}/video-token",
    response_model=VideoPlaybackTokenResponse,
)
async def mint_video_token(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VideoPlaybackTokenResponse:
    asset, _lesson = await _resolve_asset_with_access(
        db, user=current_user, asset_id=asset_id
    )
    if asset.kind != ASSET_KIND_VIDEO:
        raise HTTPException(
            status_code=400, detail="Asset is not a video"
        )
    token = mux_service.mint_playback_token(asset.storage_ref)
    log.info(
        "learn.video_token_minted",
        student_id=str(current_user.id),
        asset_id=str(asset_id),
        signed=token.signed,
    )
    return VideoPlaybackTokenResponse(
        asset_id=asset_id,
        playback_id=token.playback_id,
        token=token.token,
        expires_at=token.expires_at,
    )


# ---------------------------------------------------------------------------
# Progress + completion mutations
# ---------------------------------------------------------------------------


@router.patch("/assets/{asset_id}/progress", response_model=AssetProgressOut)
async def update_asset_progress(
    asset_id: uuid.UUID,
    payload: AssetProgressUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssetProgressOut:
    await _resolve_asset_with_access(db, user=current_user, asset_id=asset_id)
    delta = AssetProgressDelta(
        watch_pct=payload.watch_pct,
        watched_seconds=payload.watched_seconds,
        last_position_seconds=payload.last_position_seconds,
        mark_executed=payload.mark_executed,
    )
    result = await lesson_progress_service.apply_asset_delta(
        db, student_id=current_user.id, asset_id=asset_id, delta=delta
    )
    return AssetProgressOut.model_validate(result.asset_progress)


@router.post(
    "/lessons/{lesson_id}/complete",
    response_model=LessonCompletionResponse,
)
async def mark_lesson_complete(
    lesson_id: uuid.UUID,
    payload: MarkLessonCompleteRequest,  # noqa: ARG001 — note kept for future audit
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LessonCompletionResponse:
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None or not lesson.is_published:
        raise HTTPException(status_code=404, detail="Lesson not found")

    if current_user.role != "admin":
        entitled = await lesson_access_service.has_course_access(
            db, user_id=current_user.id, course_id=lesson.course_id
        )
        if not entitled:
            raise HTTPException(status_code=402, detail="Course not entitled")
        unlocked, reason = (
            await lesson_access_service.is_lesson_unlocked_for_student(
                db, student_id=current_user.id, lesson_id=lesson_id
            )
        )
        if not unlocked:
            raise HTTPException(
                status_code=403,
                detail={"reason": "lesson_locked", "message": reason},
            )

    completed, newly_unlocked, missing = (
        await lesson_progress_service.force_lesson_check(
            db, student_id=current_user.id, lesson_id=lesson_id
        )
    )

    # Recompute completion_pct for the response so the UI doesn't need
    # a follow-up timeline refresh just to show the bar.
    states = await lesson_access_service.build_course_state(
        db, student_id=current_user.id, course_id=lesson.course_id
    )
    pct = next(
        (s.completion.completion_pct for s in states if s.lesson.id == lesson_id),
        0.0,
    )

    return LessonCompletionResponse(
        lesson_id=lesson_id,
        completed=completed,
        completion_pct=pct,
        newly_unlocked_lesson_ids=newly_unlocked,
        blocking_reasons=missing,
    )


# ---------------------------------------------------------------------------
# Mux webhook
# ---------------------------------------------------------------------------


@router.post("/webhooks/mux", status_code=200)
async def mux_webhook(
    request: Request,
    mux_signature: str | None = Header(default=None, alias="Mux-Signature"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Mux at-least-once webhook receiver.

    We dedup on event_id (UNIQUE in mux_webhook_events) and apply the
    watched-time payload to the matching asset_progress row. Returns 200
    even on unknown event types so Mux doesn't keep retrying noise.
    """
    raw = await request.body()
    if not mux_service.verify_webhook_signature(
        signature_header=mux_signature or "", body=raw
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Mux signature",
        )

    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    event_id = payload.get("id")
    event_type = payload.get("type", "")
    if not event_id or not event_type:
        raise HTTPException(
            status_code=400, detail="Missing event id or type"
        )

    data = payload.get("data") or {}
    playback_ids = data.get("playback_ids") or []
    playback_id = (
        playback_ids[0].get("id") if playback_ids else data.get("playback_id")
    )
    asset_ref = data.get("id")

    # Insert dedup ledger row first; if the UNIQUE fires we return early.
    ledger = MuxWebhookEvent(
        event_id=event_id,
        event_type=event_type,
        playback_id=playback_id,
        asset_ref=asset_ref,
        payload=payload,
    )
    db.add(ledger)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        log.info("mux.webhook.duplicate_event", event_id=event_id)
        return {"status": "duplicate"}

    handled = False
    if event_type in {"video.asset.ready", "video.asset.errored"}:
        handled = True  # nothing to write yet — the asset is informational.
    elif event_type == "video.asset.live_stream_completed":
        handled = True
    elif (
        event_type.startswith("video.view.")
        or event_type == "video.asset.master.ready"
    ):
        # Watched-seconds events come through video.view.* in Mux Data.
        # Payload shape varies; we look for `data.watch_time` / `data.percent`.
        watch_time = data.get("watch_time") or data.get("watched_time")
        percent = data.get("percent_watched") or data.get("percent")
        if playback_id is not None and (watch_time or percent):
            await _apply_view_event(
                db,
                playback_id=playback_id,
                watched_seconds=int(watch_time) if watch_time else None,
                watch_pct=(float(percent) / 100.0)
                if percent is not None
                else None,
            )
            handled = True

    ledger.processed_at = datetime.now(UTC)
    await db.flush()

    log.info(
        "mux.webhook.processed",
        event_id=event_id,
        event_type=event_type,
        handled=handled,
    )
    return {"status": "ok" if handled else "ignored"}


async def _apply_view_event(
    db: AsyncSession,
    *,
    playback_id: str,
    watched_seconds: int | None,
    watch_pct: float | None,
) -> None:
    """Look up the asset by playback_id and bump its progress for every
    student who has ever opened it.

    Mux Data view events are anonymized at the playback_id level, so we
    can't attribute a single watched-time event to a single student.
    Instead we rely on the per-student player heartbeat (PATCH
    /assets/{id}/progress) for personal progress, and use the webhook
    only as the "asset is healthy / reaching threshold" signal that
    invalidates per-student rows that are stale.

    For now this is intentionally a no-op against student rows — the
    ledger captures the event and it remains available for a
    re-processing pass once Mux Data passport_id is wired.
    """
    log.info(
        "mux.webhook.view_event",
        playback_id=playback_id,
        watched_seconds=watched_seconds,
        watch_pct=watch_pct,
    )


# ---------------------------------------------------------------------------
# Active-course summary — drives the merged Path screen.
# ---------------------------------------------------------------------------


@router.get("/me/active-course", response_model=ActiveCourseResponse)
async def get_active_course(
    db: AsyncSession = Depends(get_db),
    view_target: User = Depends(get_view_target_user),
) -> ActiveCourseResponse:
    """Return the student's most-recently-touched course + the full enrolled set.

    "Enrolled" here means "has at least one student_asset_progress row";
    free catalog browse access alone is excluded by design. The Path
    screen uses `active_course_id` as the spine and renders
    `enrolled_courses` as a "switch course" chip row.

    During admin impersonation, ``view_target`` is the student — so
    /path renders the student's exact spine and chip row, which is the
    whole point of the support flow.
    """
    rows = await enrolled_course_service.list_enrolled_courses(
        db, student_id=view_target.id
    )
    return ActiveCourseResponse(
        active_course_id=rows[0].course_id if rows else None,
        enrolled_courses=[
            EnrolledCourseSummary(
                course_id=r.course_id,
                course_slug=r.course_slug,
                course_title=r.course_title,
                progress_pct=r.progress_pct,
                total_lessons=r.total_lessons,
                completed_lessons=r.completed_lessons,
                last_touched_at=r.last_touched_at,
            )
            for r in rows
        ],
        viewer_role=view_target.role,
    )


# ---------------------------------------------------------------------------
# Operator health endpoint — surfaces Mux + R2 config without exposing keys.
# ---------------------------------------------------------------------------


@router.get("/health/storage")
async def storage_health(
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    from app.core.config import settings as _settings

    return {
        "mux": mux_service.signing_health(),
        "r2": {
            "bucket": _settings.r2_bucket,
            "endpoint_present": bool(_settings.r2_endpoint),
            "credentials_present": bool(
                _settings.r2_access_key and _settings.r2_secret_key
            ),
        },
        "jupyterlite_base_url": _settings.jupyterlite_base_url,
    }
