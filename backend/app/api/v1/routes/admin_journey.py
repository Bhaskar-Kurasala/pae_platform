"""D9 / Pass 3i §F — admin trace endpoints.

Two endpoints:
  GET /api/v1/admin/students/{student_id}/journey
  GET /api/v1/admin/agents/{agent_name}/recent-decisions

Both are read-only, admin-only, point at the primary DB (Tier 1
sizing per Pass 3i §F.2). Returns structured timelines reconstructable
into a UI view.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User

log = structlog.get_logger().bind(layer="admin_journey_route")


router = APIRouter(prefix="/admin", tags=["admin"])


# ── Admin gate ──────────────────────────────────────────────────────


async def _require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Reject non-admin callers with 403.

    Mirrors the existing admin.py pattern. Centralized here so the
    trace endpoints share the same gate without import-cycling
    through admin.py.
    """
    role = getattr(current_user, "role", None)
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# ── Response shapes ────────────────────────────────────────────────


class ActionEntry(BaseModel):
    id: uuid.UUID
    agent_name: str
    action_type: str
    summary: str | None = None
    status: str
    duration_ms: int | None = None
    cost_inr: float | None = None
    created_at: datetime


class ChainEntry(BaseModel):
    id: uuid.UUID
    root_id: uuid.UUID
    parent_id: uuid.UUID | None
    caller_agent: str | None
    callee_agent: str
    depth: int
    status: str
    duration_ms: int | None = None
    created_at: datetime


class MemoryEntry(BaseModel):
    id: uuid.UUID
    agent_name: str
    scope: str
    key: str
    created_at: datetime


class EscalationEntry(BaseModel):
    id: uuid.UUID
    agent_name: str
    reason: str
    notified_admin: bool
    created_at: datetime


class SafetyEntry(BaseModel):
    id: uuid.UUID
    agent_name: str | None
    incident_type: str
    severity: str
    decision: str
    detector: str
    occurred_at: datetime


class JourneySummary(BaseModel):
    total_actions: int
    total_chains: int
    total_safety_incidents: int
    total_escalations: int
    distinct_agents: list[str] = Field(default_factory=list)


class StudentJourney(BaseModel):
    student_id: uuid.UUID
    window_from: datetime
    window_to: datetime
    actions: list[ActionEntry] = Field(default_factory=list)
    chains: list[ChainEntry] = Field(default_factory=list)
    memory_writes: list[MemoryEntry] = Field(default_factory=list)
    escalations: list[EscalationEntry] = Field(default_factory=list)
    safety_incidents: list[SafetyEntry] = Field(default_factory=list)
    summary: JourneySummary


class RecentDecisionEntry(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID | None = None
    action_type: str
    summary: str | None = None
    output_data: dict[str, Any] | None = None
    created_at: datetime


class RecentDecisionsResponse(BaseModel):
    agent_name: str
    since: datetime
    count: int
    decisions: list[RecentDecisionEntry]


# ── /admin/students/{student_id}/journey ────────────────────────────


@router.get(
    "/students/{student_id}/journey",
    response_model=StudentJourney,
)
async def student_journey(
    student_id: uuid.UUID = Path(...),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> StudentJourney:
    """Return a structured timeline of platform activity for one student.

    Pass 3i §F.1 spec. Reads from agent_actions, agent_call_chain,
    agent_memory, agent_escalations, safety_incidents.

    Default window: last 7 days. Override with `from` / `to`
    query params (ISO-8601 timestamps).

    Limit applies *per category* — actions, chains, memory writes,
    etc. each get up to `limit` rows. Default 200, max 1000.
    """
    now = datetime.now(UTC)
    window_to = to or now
    window_from = from_ or (window_to - timedelta(days=7))
    if window_from >= window_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`from` must be earlier than `to`",
        )

    # ── Actions ────────────────────────────────────────────────────
    actions_result = await db.execute(
        text(
            """
            SELECT id, agent_name, action_type, summary, status,
                   duration_ms, cost_inr, created_at
            FROM agent_actions
            WHERE student_id = :uid
              AND created_at >= :from_t
              AND created_at <= :to_t
            ORDER BY created_at DESC
            LIMIT :lim
            """
        ),
        {"uid": student_id, "from_t": window_from, "to_t": window_to, "lim": limit},
    )
    actions = [
        ActionEntry(
            id=row[0],
            agent_name=row[1],
            action_type=row[2],
            summary=row[3],
            status=row[4],
            duration_ms=row[5],
            cost_inr=float(row[6]) if row[6] is not None else None,
            created_at=row[7],
        )
        for row in actions_result.all()
    ]

    # ── Chains ─────────────────────────────────────────────────────
    chains_result = await db.execute(
        text(
            """
            SELECT id, root_id, parent_id, caller_agent, callee_agent,
                   depth, status, duration_ms, created_at
            FROM agent_call_chain
            WHERE user_id = :uid
              AND created_at >= :from_t
              AND created_at <= :to_t
            ORDER BY created_at DESC
            LIMIT :lim
            """
        ),
        {"uid": student_id, "from_t": window_from, "to_t": window_to, "lim": limit},
    )
    chains = [
        ChainEntry(
            id=row[0],
            root_id=row[1],
            parent_id=row[2],
            caller_agent=row[3],
            callee_agent=row[4],
            depth=row[5],
            status=row[6],
            duration_ms=row[7],
            created_at=row[8],
        )
        for row in chains_result.all()
    ]

    # ── Memory writes ──────────────────────────────────────────────
    memory_result = await db.execute(
        text(
            """
            SELECT id, agent_name, scope::text, key, created_at
            FROM agent_memory
            WHERE user_id = :uid
              AND created_at >= :from_t
              AND created_at <= :to_t
            ORDER BY created_at DESC
            LIMIT :lim
            """
        ),
        {"uid": student_id, "from_t": window_from, "to_t": window_to, "lim": limit},
    )
    memory_writes = [
        MemoryEntry(
            id=row[0],
            agent_name=row[1],
            scope=row[2],
            key=row[3],
            created_at=row[4],
        )
        for row in memory_result.all()
    ]

    # ── Escalations ────────────────────────────────────────────────
    escalation_result = await db.execute(
        text(
            """
            SELECT id, agent_name, reason, notified_admin, created_at
            FROM agent_escalations
            WHERE user_id = :uid
              AND created_at >= :from_t
              AND created_at <= :to_t
            ORDER BY created_at DESC
            LIMIT :lim
            """
        ),
        {"uid": student_id, "from_t": window_from, "to_t": window_to, "lim": limit},
    )
    escalations = [
        EscalationEntry(
            id=row[0],
            agent_name=row[1],
            reason=row[2],
            notified_admin=bool(row[3]),
            created_at=row[4],
        )
        for row in escalation_result.all()
    ]

    # ── Safety incidents ───────────────────────────────────────────
    safety_result = await db.execute(
        text(
            """
            SELECT id, agent_name, incident_type, severity, decision,
                   detector, occurred_at
            FROM safety_incidents
            WHERE user_id = :uid
              AND occurred_at >= :from_t
              AND occurred_at <= :to_t
            ORDER BY occurred_at DESC
            LIMIT :lim
            """
        ),
        {"uid": student_id, "from_t": window_from, "to_t": window_to, "lim": limit},
    )
    safety_incidents = [
        SafetyEntry(
            id=row[0],
            agent_name=row[1],
            incident_type=row[2],
            severity=row[3],
            decision=row[4],
            detector=row[5],
            occurred_at=row[6],
        )
        for row in safety_result.all()
    ]

    distinct_agents = sorted(
        {a.agent_name for a in actions if a.agent_name}
        | {c.callee_agent for c in chains}
    )

    return StudentJourney(
        student_id=student_id,
        window_from=window_from,
        window_to=window_to,
        actions=actions,
        chains=chains,
        memory_writes=memory_writes,
        escalations=escalations,
        safety_incidents=safety_incidents,
        summary=JourneySummary(
            total_actions=len(actions),
            total_chains=len(chains),
            total_safety_incidents=len(safety_incidents),
            total_escalations=len(escalations),
            distinct_agents=distinct_agents,
        ),
    )


# ── /admin/agents/{agent_name}/recent-decisions ────────────────────


@router.get(
    "/agents/{agent_name}/recent-decisions",
    response_model=RecentDecisionsResponse,
)
async def agent_recent_decisions(
    agent_name: str = Path(...),
    limit: int = Query(50, ge=1, le=200),
    since: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> RecentDecisionsResponse:
    """Recent decisions for one agent.

    Pass 3b §9.2 / Pass 3i §F.3 spec. Used by ops to investigate
    routing patterns + Critic sampling.
    """
    cutoff = since or (datetime.now(UTC) - timedelta(hours=24))

    result = await db.execute(
        text(
            """
            SELECT id, student_id, action_type, summary, output_data,
                   created_at
            FROM agent_actions
            WHERE agent_name = :name
              AND created_at >= :cutoff
            ORDER BY created_at DESC
            LIMIT :lim
            """
        ),
        {"name": agent_name, "cutoff": cutoff, "lim": limit},
    )
    decisions = [
        RecentDecisionEntry(
            id=row[0],
            student_id=row[1],
            action_type=row[2],
            summary=row[3],
            output_data=row[4],
            created_at=row[5],
        )
        for row in result.all()
    ]
    return RecentDecisionsResponse(
        agent_name=agent_name,
        since=cutoff,
        count=len(decisions),
        decisions=decisions,
    )
