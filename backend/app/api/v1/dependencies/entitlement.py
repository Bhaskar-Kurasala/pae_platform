"""FastAPI dependency: gate a route on the user's course entitlement.

Usage in a route file:

    from fastapi import APIRouter, Depends
    from app.api.v1.dependencies.entitlement import require_course_access

    router = APIRouter()

    @router.get(
        "/courses/{course_id}/lessons/{lesson_id}",
        dependencies=[Depends(require_course_access())],
    )
    async def read_lesson(...):
        ...

The dependency reads the path param (default name ``course_id``) off
the request, calls ``entitlement_service.is_entitled``, and 403s when
the user hasn't unlocked the course. Returns ``None`` on success — it
exists for its side-effect of raising.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.entitlement import EntitlementContext
from app.services.entitlement_service import (
    compute_active_entitlements,
    is_entitled,
)


def require_course_access(
    course_id_param: str = "course_id",
) -> Callable[..., object]:
    """Build a dependency that 403s if the current user isn't entitled.

    ``course_id_param`` is the name of the path parameter that holds the
    course UUID. We read it off the request rather than declaring it as
    a function arg so the same dependency works for routes whose course
    id arrives under a different name (e.g. via a join through a lesson).
    """

    async def dep(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        raw = request.path_params.get(course_id_param)
        if raw is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing path param '{course_id_param}'",
            )
        try:
            course_id = (
                raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid course_id: {raw!r}",
            ) from exc

        if not await is_entitled(
            db, user_id=current_user.id, course_id=course_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Course not unlocked",
            )

    return dep


async def require_active_entitlement(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EntitlementContext:
    """D9 / Pass 3f §A.1 — Layer 1 entitlement gate for the canonical
    agentic endpoint.

    Computes a fresh EntitlementContext for the current user. If the
    context is empty (no paid entitlements AND no free-tier grant),
    raises 402 Payment Required with a structured detail body.

    Returns the EntitlementContext on success — the route handler
    receives it as a dependency-injected param and threads it into
    AgenticOrchestratorService.process_request so Layer 2 + 3 don't
    re-fetch.

    Mounted on POST /api/v1/agentic/{flow}/chat (the canonical
    endpoint). Other routes — billing, course detail, etc. — use the
    coarser require_course_access(course_id_param=...) instead.
    """
    ctx = await compute_active_entitlements(db, current_user.id)

    if ctx.is_empty():
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error_code": "no_active_entitlement",
                "message": (
                    "Your AICareerOS subscription has expired or you "
                    "haven't purchased a course yet. Browse available "
                    "courses to continue."
                ),
                "next_action": "browse_catalog",
                "next_url": "/catalog",
            },
        )

    return ctx
