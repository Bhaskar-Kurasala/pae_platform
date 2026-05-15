"""Admin lesson-asset CRUD — backs the "Assets" subsection of the
lesson editor at /admin/courses/[id]/edit.

Mounted at ``/api/v1/admin``. All endpoints require role=admin.

Why a separate file from admin.py: admin.py is already 7000+ lines.
The lesson-player feature gets its own admin file so the asset surface
can evolve without touching the rest. AdminAuditService logs each
mutation so the audit trail stays unified.

Asset CRUD reuses the LessonAsset model directly — no service layer
needed because the operations are thin (validate → upsert → log).
The student-facing read path (`/api/v1/learn/courses/{id}/timeline`)
queries the same rows, so admin's saves are immediately visible to
students on the next refresh.

Sync-from-legacy helper builds a video LessonAsset from the legacy
``Lesson.youtube_video_id`` so admins don't have to re-enter YouTube
references manually for each existing lesson.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.lesson import Lesson
from app.models.lesson_asset import (
    ASSET_KIND_VIDEO,
    ASSET_KINDS,
    LessonAsset,
)
from app.models.user import User
from app.schemas.learn import (
    AdminAssetCreate,
    AdminAssetOut,
    AdminAssetReorderRequest,
    AdminAssetUpdate,
    AdminLegacySyncResponse,
)
from app.services.admin_audit_service import AdminAuditService

log = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin-lesson-assets"])


def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin only"
        )
    return current_user


async def _ensure_lesson(db: AsyncSession, lesson_id: uuid.UUID) -> Lesson:
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None or getattr(lesson, "is_deleted", False):
        raise HTTPException(status_code=404, detail="Lesson not found")
    return lesson


def _to_out(asset: LessonAsset) -> AdminAssetOut:
    # Pydantic from_attributes can't see metadata_ (Python-side rename)
    # and we want to surface it as `metadata`. Hand-build the projection.
    return AdminAssetOut(
        id=asset.id,
        lesson_id=asset.lesson_id,
        kind=asset.kind,  # type: ignore[arg-type]
        order=asset.order,
        title=asset.title,
        description=asset.description,
        storage_ref=asset.storage_ref,
        duration_seconds=asset.duration_seconds,
        is_published=asset.is_published,
        metadata=asset.metadata_,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get(
    "/lessons/{lesson_id}/assets",
    response_model=list[AdminAssetOut],
)
async def list_lesson_assets(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[AdminAssetOut]:
    await _ensure_lesson(db, lesson_id)
    rows = (
        await db.execute(
            select(LessonAsset)
            .where(LessonAsset.lesson_id == lesson_id)
            .order_by(LessonAsset.order.asc(), LessonAsset.created_at.asc())
        )
    ).scalars().all()
    return [_to_out(r) for r in rows]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post(
    "/lessons/{lesson_id}/assets",
    response_model=AdminAssetOut,
    status_code=201,
)
async def create_lesson_asset(
    lesson_id: uuid.UUID,
    payload: AdminAssetCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> AdminAssetOut:
    lesson = await _ensure_lesson(db, lesson_id)

    if payload.kind not in ASSET_KINDS:
        raise HTTPException(
            status_code=400, detail=f"Invalid asset kind {payload.kind!r}"
        )

    asset = LessonAsset(
        lesson_id=lesson.id,
        kind=payload.kind,
        title=payload.title,
        description=payload.description,
        storage_ref=payload.storage_ref,
        order=payload.order,
        duration_seconds=payload.duration_seconds,
        is_published=payload.is_published,
        metadata_=payload.metadata,
    )
    db.add(asset)
    await db.flush()

    await AdminAuditService.log(
        db,
        admin=admin,
        action_type="lesson_asset_create",
        resource_type="lesson_asset",
        resource_id=str(asset.id),
        after={
            "lesson_id": str(lesson.id),
            "kind": payload.kind,
            "title": payload.title,
            "storage_ref_present": bool(payload.storage_ref),
        },
        request=request,
    )
    log.info(
        "admin.lesson_asset.created",
        admin_id=str(admin.id),
        lesson_id=str(lesson.id),
        asset_id=str(asset.id),
        kind=payload.kind,
    )
    return _to_out(asset)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@router.patch(
    "/lesson-assets/{asset_id}", response_model=AdminAssetOut,
)
async def update_lesson_asset(
    asset_id: uuid.UUID,
    payload: AdminAssetUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> AdminAssetOut:
    asset = await db.get(LessonAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    before = {
        "kind": asset.kind,
        "title": asset.title,
        "storage_ref": asset.storage_ref,
        "order": asset.order,
        "is_published": asset.is_published,
    }

    if payload.kind is not None:
        if payload.kind not in ASSET_KINDS:
            raise HTTPException(
                status_code=400, detail=f"Invalid asset kind {payload.kind!r}"
            )
        asset.kind = payload.kind
    if payload.title is not None:
        asset.title = payload.title
    if payload.description is not None:
        asset.description = payload.description
    if payload.storage_ref is not None:
        asset.storage_ref = payload.storage_ref
    if payload.order is not None:
        asset.order = payload.order
    if payload.duration_seconds is not None:
        asset.duration_seconds = payload.duration_seconds
    if payload.is_published is not None:
        asset.is_published = payload.is_published
    if payload.metadata is not None:
        asset.metadata_ = payload.metadata

    asset.updated_at = datetime.now(UTC)
    await db.flush()

    after = {
        "kind": asset.kind,
        "title": asset.title,
        "storage_ref": asset.storage_ref,
        "order": asset.order,
        "is_published": asset.is_published,
    }
    await AdminAuditService.log(
        db,
        admin=admin,
        action_type="lesson_asset_update",
        resource_type="lesson_asset",
        resource_id=str(asset.id),
        before=before,
        after=after,
        request=request,
    )
    return _to_out(asset)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete(
    "/lesson-assets/{asset_id}", status_code=204,
)
async def delete_lesson_asset(
    asset_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> None:
    asset = await db.get(LessonAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    snapshot = {
        "lesson_id": str(asset.lesson_id),
        "kind": asset.kind,
        "title": asset.title,
        "storage_ref": asset.storage_ref,
    }
    await db.delete(asset)
    await db.flush()

    await AdminAuditService.log(
        db,
        admin=admin,
        action_type="lesson_asset_delete",
        resource_type="lesson_asset",
        resource_id=str(asset_id),
        before=snapshot,
        request=request,
    )
    log.info(
        "admin.lesson_asset.deleted",
        admin_id=str(admin.id),
        asset_id=str(asset_id),
    )


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


@router.post(
    "/lessons/{lesson_id}/assets/reorder",
    response_model=list[AdminAssetOut],
)
async def reorder_lesson_assets(
    lesson_id: uuid.UUID,
    payload: AdminAssetReorderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> list[AdminAssetOut]:
    lesson = await _ensure_lesson(db, lesson_id)

    rows = (
        await db.execute(
            select(LessonAsset).where(LessonAsset.lesson_id == lesson.id)
        )
    ).scalars().all()
    by_id = {a.id: a for a in rows}

    for item in payload.items:
        asset = by_id.get(item.asset_id)
        if asset is None:
            raise HTTPException(
                status_code=400,
                detail=f"Asset {item.asset_id} does not belong to lesson",
            )
        asset.order = item.order
    await db.flush()

    await AdminAuditService.log(
        db,
        admin=admin,
        action_type="lesson_asset_reorder",
        resource_type="lesson",
        resource_id=str(lesson.id),
        after={
            "order": [
                {"asset_id": str(i.asset_id), "order": i.order}
                for i in payload.items
            ]
        },
        request=request,
    )
    rows = (
        await db.execute(
            select(LessonAsset)
            .where(LessonAsset.lesson_id == lesson.id)
            .order_by(LessonAsset.order.asc(), LessonAsset.created_at.asc())
        )
    ).scalars().all()
    return [_to_out(r) for r in rows]


# ---------------------------------------------------------------------------
# Sync-from-legacy helper
# ---------------------------------------------------------------------------


@router.post(
    "/lessons/{lesson_id}/assets/sync-from-legacy",
    response_model=AdminLegacySyncResponse,
)
async def sync_legacy_assets(
    lesson_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> AdminLegacySyncResponse:
    """Backfill lesson_assets from the legacy Lesson.* fields.

    Today this only handles ``Lesson.youtube_video_id`` → a video asset
    (kind='video', storage_ref=youtube_id, metadata={"source": "youtube"}).
    Skips when a video asset already exists for the lesson — admin can
    delete the asset and re-sync if they want a clean slate.

    For YouTube assets the player needs special handling — the existing
    Mux player iframe won't work. Frontend treats metadata.source ==
    'youtube' as a YouTube embed.
    """
    lesson = await _ensure_lesson(db, lesson_id)
    created: list[LessonAsset] = []
    skipped: list[str] = []

    existing_video = (
        await db.execute(
            select(LessonAsset).where(
                LessonAsset.lesson_id == lesson.id,
                LessonAsset.kind == ASSET_KIND_VIDEO,
            ).limit(1)
        )
    ).scalar_one_or_none()

    youtube_id = lesson.youtube_video_id
    if not youtube_id:
        skipped.append("Lesson has no youtube_video_id")
    elif existing_video is not None:
        skipped.append(
            f"Video asset already exists ({existing_video.title}); "
            "delete it first to re-sync"
        )
    else:
        asset = LessonAsset(
            lesson_id=lesson.id,
            kind=ASSET_KIND_VIDEO,
            title=f"{lesson.title} (YouTube)",
            storage_ref=youtube_id,
            order=0,
            duration_seconds=lesson.duration_seconds or None,
            is_published=True,
            metadata_={"source": "youtube"},
        )
        db.add(asset)
        await db.flush()
        created.append(asset)

    if created:
        await AdminAuditService.log(
            db,
            admin=admin,
            action_type="lesson_asset_sync_legacy",
            resource_type="lesson",
            resource_id=str(lesson.id),
            after={"created_count": len(created)},
            request=request,
        )

    return AdminLegacySyncResponse(
        lesson_id=lesson.id,
        created_assets=[_to_out(a) for a in created],
        skipped_reasons=skipped,
    )
