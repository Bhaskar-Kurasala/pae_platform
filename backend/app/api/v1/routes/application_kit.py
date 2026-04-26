"""Application Kit API routes.

Mounted under `/readiness/kit`. Routes let the user build, list, fetch,
download, and delete kits — full CRUD minus update (kits are immutable
snapshots; rebuild = new row).
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.application_kit import ApplicationKit
from app.models.user import User
from app.schemas.application_kit import (
    ApplicationKitListItem,
    ApplicationKitResponse,
    BuildKitRequest,
)
from app.services.application_kit_service import (
    build_kit,
    delete_kit_for_user,
    get_kit_for_user,
    list_kits_for_user,
)

log = structlog.get_logger()

router = APIRouter(prefix="/readiness/kit", tags=["application-kit"])


_NON_SECTION_KEYS = {"label", "target_role", "built_at"}


def _manifest_section_keys(manifest: dict | None) -> list[str]:
    """Return the list of source-section keys present in *manifest*.

    Excludes scaffolding keys (label/target_role/built_at) — only the rows
    that were actually resolved (resume, tailored_resume, jd, mock_report,
    autopsy) are returned.
    """
    if not manifest:
        return []
    return sorted(k for k in manifest if k not in _NON_SECTION_KEYS)


def _to_list_item(kit: ApplicationKit) -> ApplicationKitListItem:
    return ApplicationKitListItem(
        id=kit.id,
        label=kit.label,
        target_role=kit.target_role,
        status=kit.status,
        generated_at=kit.generated_at,
        created_at=kit.created_at,
        manifest_keys=_manifest_section_keys(kit.manifest),
    )


def _to_response(kit: ApplicationKit) -> ApplicationKitResponse:
    return ApplicationKitResponse(
        id=kit.id,
        label=kit.label,
        target_role=kit.target_role,
        status=kit.status,
        generated_at=kit.generated_at,
        created_at=kit.created_at,
        manifest=dict(kit.manifest or {}),
        has_pdf=kit.pdf_blob is not None,
    )


@router.post(
    "",
    response_model=ApplicationKitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_kit(
    body: BuildKitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplicationKitResponse:
    """Build a new Application Kit. Returns the ready (or failed) row."""
    kit = await build_kit(db, user=current_user, request=body)
    log.info(
        "application_kit.created",
        user_id=str(current_user.id),
        kit_id=str(kit.id),
        status=kit.status,
    )
    return _to_response(kit)


@router.get("", response_model=list[ApplicationKitListItem])
async def list_kits(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ApplicationKitListItem]:
    """Return the current user's kits, newest first."""
    rows = await list_kits_for_user(db, user_id=current_user.id)
    return [_to_list_item(k) for k in rows]


@router.get("/{kit_id}", response_model=ApplicationKitResponse)
async def get_kit(
    kit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplicationKitResponse:
    """Return the full manifest snapshot for a kit owned by the user."""
    kit = await get_kit_for_user(db, user_id=current_user.id, kit_id=kit_id)
    if kit is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Application kit not found"
        )
    return _to_response(kit)


@router.get("/{kit_id}/download")
async def download_kit(
    kit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Stream the kit's rendered PDF. 404 if the row has no blob."""
    kit = await get_kit_for_user(db, user_id=current_user.id, kit_id=kit_id)
    if kit is None or kit.pdf_blob is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application kit PDF not found",
        )
    safe_label = (kit.label or "kit").replace('"', "").strip() or "kit"
    return Response(
        content=kit.pdf_blob,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="application-kit-{safe_label}.pdf"'
            ),
        },
    )


@router.delete("/{kit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kit(
    kit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a kit. 404 if not owned."""
    deleted = await delete_kit_for_user(
        db, user_id=current_user.id, kit_id=kit_id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Application kit not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
