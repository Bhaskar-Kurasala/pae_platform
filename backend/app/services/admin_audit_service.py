"""AdminAuditService — record every privileged action for compliance traceability."""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_audit_log import AdminAuditLog
from app.models.user import User

log = structlog.get_logger(__name__)


class AdminAuditService:
    @staticmethod
    async def log(
        db: AsyncSession,
        admin: User,
        action_type: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        request: Request | None = None,
    ) -> None:
        """Record an admin action. Failures are logged but never raised — audit must not break the request path."""
        try:
            entry = AdminAuditLog(
                admin_id=admin.id,
                admin_email=admin.email,
                action_type=action_type,
                resource_type=resource_type,
                resource_id=resource_id,
                before_value=before,
                after_value=after,
                extra=metadata,
                ip_address=request.client.host if request and request.client else None,
                user_agent=request.headers.get("user-agent") if request else None,
                trace_id=request.headers.get("x-request-id") if request else None,
            )
            db.add(entry)
            await db.flush()
            log.info(
                "admin.audit",
                action_type=action_type,
                admin_email=admin.email,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        except Exception:
            log.exception(
                "admin.audit.failed",
                action_type=action_type,
                admin_email=getattr(admin, "email", "unknown"),
            )
