"""Impersonation primitive — admin "view as student" mode.

Contract:
  * The JWT identifying the request is ALWAYS the admin's. We never
    swap tokens or mint new ones for the target student. This keeps
    the principal stable for audit, rate-limit, and Sentry attribution.
  * Admins request a "view target" by sending the
    ``X-Impersonate-Student-Id`` header. The header is honored ONLY
    when the authenticated user has role=admin; non-admins sending it
    receive 403.
  * The dependency returns the *target* user when impersonation is
    active, else the calling user. Read endpoints depend on this —
    write endpoints stay on get_current_user, so impersonation is
    structurally read-only (admin can browse a student's view but
    cannot mutate as them).
  * Every successful impersonation request emits one
    AdminAuditLog row (action_type='impersonate_view'). Failures
    (logging, DB, etc.) never break the request — same contract as
    AdminAuditService.

Why a header (not a query param or session cookie):
  * Headers are easy to thread through fetch() in one place
    (api-client.ts) without polluting URLs.
  * Browser refresh keeps the header (it lives in the auth-store) but
    the URL stays clean and shareable.
  * Server-side it's a single Header(...) dependency — no per-route
    signature changes beyond swapping the user dep.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.admin_audit_service import AdminAuditService

log = structlog.get_logger()


IMPERSONATION_HEADER = "X-Impersonate-Student-Id"
IMPERSONATION_AUDIT_ACTION = "impersonate_view"


async def _resolve_target(
    db: AsyncSession, target_id: uuid.UUID
) -> User:
    user = await UserRepository(db).get(target_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Impersonation target not found",
        )
    if user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Impersonation target is deactivated",
        )
    return user


async def get_view_target_user(
    request: Request,
    current_user: User = Depends(get_current_user),
    impersonate_id: str | None = Header(default=None, alias=IMPERSONATION_HEADER),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Return the user whose data this request should READ.

    Rules:
      * No header → return current_user (the common case).
      * Header present + caller is admin → resolve and return the
        target user; emit one audit row.
      * Header present + caller is NOT admin → 403. Non-admins must
        not be able to read another user's data even if they craft
        the header by hand.
      * Header present but malformed UUID → 400.
      * Target user missing → 404.

    The current_user is preserved on ``request.state.actor`` so any
    audit downstream (e.g. write endpoints that add ``on_behalf_of``)
    can still attribute the action to the admin's identity, not the
    target's.
    """
    request.state.actor = current_user

    if not impersonate_id:
        return current_user

    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Impersonation requires admin role",
        )

    try:
        target_uuid = uuid.UUID(impersonate_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid impersonation target id",
        ) from exc

    target = await _resolve_target(db, target_uuid)

    # Fire-and-forget audit — failures swallowed inside the service.
    await AdminAuditService.log(
        db,
        admin=current_user,
        action_type=IMPERSONATION_AUDIT_ACTION,
        resource_type="user",
        resource_id=str(target.id),
        metadata={
            "target_email": target.email,
            "path": request.url.path,
        },
        request=request,
    )

    log.info(
        "impersonation.view",
        admin_id=str(current_user.id),
        admin_email=current_user.email,
        target_id=str(target.id),
        target_email=target.email,
        path=request.url.path,
    )
    return target


def actor_from_request(request: Request, fallback: User) -> User:
    """Recover the admin identity even from a route that uses get_view_target_user.

    Useful inside services that need to log "admin X did Y on behalf of student Z"
    when the route handler only had access to the target user.
    """
    return getattr(request.state, "actor", None) or fallback


def is_impersonating(request: Request) -> bool:
    actor = getattr(request.state, "actor", None)
    return actor is not None and actor.role == "admin"
