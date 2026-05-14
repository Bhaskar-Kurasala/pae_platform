import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel as PydanticModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.coupon import CouponCreate, CouponRead, CouponUpdate
from app.models.agent_action import AgentAction
from app.models.user import User
from app.schemas.student_note import StudentNoteCreate, StudentNoteResponse
from app.services import refund_offer_service
from app.services.admin_audit_service import AdminAuditService
from app.services.at_risk_student_service import compute_at_risk_students
from app.services.confusion_heatmap_service import compute_heatmap
from app.services.student_note_service import add_note, list_notes

log = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])

log = structlog.get_logger()


# ── Pydantic schemas ─────────────────────────────────────────────────────────


class AuditLogItem(PydanticModel):
    id: str
    student_id: str | None
    agent_name: str
    action_type: str
    status: str
    duration_ms: int | None
    created_at: datetime
    # DISC-57 — surface the new actor columns so the admin audit UI can render
    # "admin → student" attribution. Legacy rows before migration 0027 have
    # NULL for these, which renders as "(unknown)".
    actor_id: str | None = None
    actor_role: str | None = None
    on_behalf_of: str | None = None


class StudentTimelineEvent(PydanticModel):
    """DISC-55 — one event on a student's activity timeline.

    D16/CP3.3 added the "outreach" kind so WhatsApp / phone /
    email / in_app contacts surface alongside agent actions. The
    detail dict carries `channel` for the kind="outreach" case so the
    frontend can render the right channel badge.
    """

    kind: str  # "login" | "lesson_completed" | "agent_action" | "submission" | "outreach"
    at: datetime
    summary: str
    detail: dict[str, Any] | None = None


class TriggerAgentRequest(PydanticModel):
    """DISC-57 — admin invokes an agent against a named student."""

    student_id: str
    task: str | None = None


class TriggerAgentResponse(PydanticModel):
    agent_name: str
    status: str
    duration_ms: int
    response_preview: str


class LessonPerformance(PydanticModel):
    lesson_id: str
    lesson_title: str
    question_count: int
    confusion_count: int


class CourseUpdateRequest(PydanticModel):
    title: str | None = None
    description: str | None = None
    is_published: bool | None = None
    price_cents: int | None = None
    difficulty: str | None = None
    is_featured: bool | None = None


class ExerciseRubricUpdateRequest(PydanticModel):
    rubric: dict[str, Any]
    test_cases: list[dict[str, Any]] | None = None


class HealthMetric(PydanticModel):
    key: str
    label: str
    value: str
    sub: str
    tone: str
    delta: float | None
    delta_text: str | None


class HealthStripResponse(PydanticModel):
    metrics: list[HealthMetric]
    generated_at: datetime


def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return current_user


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> dict[str, Any]:
    """Platform overview stats."""
    from app.models.enrollment import Enrollment
    from app.models.exercise_submission import ExerciseSubmission
    from app.models.payment import Payment

    total_students = (
        await db.execute(
            select(func.count(User.id)).where(User.role == "student", User.is_deleted.is_(False))
        )
    ).scalar_one()

    total_enrollments = (await db.execute(select(func.count(Enrollment.id)))).scalar_one()

    total_submissions = (await db.execute(select(func.count(ExerciseSubmission.id)))).scalar_one()

    total_agent_actions = (await db.execute(select(func.count(AgentAction.id)))).scalar_one()

    total_revenue_cents = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
                Payment.status == "succeeded"
            )
        )
    ).scalar_one()

    return {
        "total_students": total_students,
        "total_enrollments": total_enrollments,
        "total_submissions": total_submissions,
        "total_agent_actions": total_agent_actions,
        "mrr_cents": total_revenue_cents,
        "mrr_usd": round(float(total_revenue_cents) / 100, 2),
    }


@router.get("/agents/health")
async def get_agents_health(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Per-agent action stats.

    DISC-54 — exposes `last_called_at` (ISO8601 or null) and `success_rate`
    (0.0–1.0 over `total_actions`, or null when total_actions == 0) so the
    Agent Monitor table renders the full row AD3 expects.
    """
    from app.agents.registry import _ensure_registered, list_agents

    _ensure_registered()
    all_agents = list_agents()

    result = []
    for agent_info in all_agents:
        name = agent_info["name"]

        total_actions = (
            await db.execute(
                select(func.count(AgentAction.id)).where(AgentAction.agent_name == name)
            )
        ).scalar_one()

        avg_duration = (
            await db.execute(
                select(func.avg(AgentAction.duration_ms)).where(AgentAction.agent_name == name)
            )
        ).scalar_one()

        errors = (
            await db.execute(
                select(func.count(AgentAction.id)).where(
                    AgentAction.agent_name == name,
                    AgentAction.status == "error",
                )
            )
        ).scalar_one()

        last_called_at = (
            await db.execute(
                select(func.max(AgentAction.created_at)).where(
                    AgentAction.agent_name == name
                )
            )
        ).scalar_one()

        success_rate: float | None
        if total_actions > 0:
            success_rate = round(1.0 - (errors / total_actions), 3)
        else:
            success_rate = None

        result.append(
            {
                "name": name,
                "description": agent_info["description"],
                "total_actions": total_actions,
                "error_count": errors,
                "avg_duration_ms": round(float(avg_duration or 0), 1),
                "last_called_at": last_called_at.isoformat() if last_called_at else None,
                "success_rate": success_rate,
                "status": "healthy" if errors == 0 else "degraded",
            }
        )

    return result


@router.get("/students")
async def list_students(
    skip: int = 0,
    limit: int = Query(200, ge=1, le=500),
    q: str | None = Query(None, description="Case-insensitive substring match on email OR full_name"),
    sort: str = Query(
        "joined_desc",
        description=(
            "Sort key: joined_asc, joined_desc (default), name_asc, name_desc, "
            "last_seen_asc, last_seen_desc"
        ),
    ),
    slip_type: str | None = Query(
        None,
        pattern="^(paid_silent|capstone_stalled|streak_broken|promotion_avoidant|cold_signup|unpaid_stalled)$",
        description=(
            "Filter to students whose F1 slip pattern matches. Used by the "
            "retention-panel 'See all N →' deep-link."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Paginated student list with engagement data.

    DISC-56 — `q` is a server-side filter. The old client-side filter loaded
    every student into the browser before filtering; past a few hundred rows
    that stops scaling. Passing `?q=autop` now narrows at the DB and keeps
    p95 well under the 500 ms SLO at any catalog size.

    F13 — `sort` lets the operator order by joined date, name, or last
    login. Sorting on lessons/agent_interactions is intentionally
    client-side: those are derived per-row counts that don't index well
    here, and the page is capped at `limit` rows anyway.

    Slip-type filter — `slip_type` joins against student_risk_signals
    so the retention-panel "See all 92 →" link lands on a roster page
    that shows only the matching slip pattern (e.g. all 92 cold_signup
    students, sorted by risk score DESC by default for that view).
    """
    from app.models.student_progress import StudentProgress
    from app.models.student_risk_signals import StudentRiskSignals

    stmt = select(User).where(User.role == "student", User.is_deleted.is_(False))
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.where(
            func.lower(User.email).like(pattern) | func.lower(User.full_name).like(pattern)
        )

    # Slip-type filter — restrict to students whose F1-classified
    # slip pattern matches. Implemented via a join + WHERE rather
    # than a subquery so the existing sort still applies.
    if slip_type is not None:
        stmt = stmt.join(
            StudentRiskSignals, StudentRiskSignals.user_id == User.id
        ).where(StudentRiskSignals.slip_type == slip_type)

    # F13 — sort whitelist. NULLS LAST on last_seen so never-logged-in
    # students don't pollute the top of the asc list.
    sort_map = {
        "joined_asc": User.created_at.asc(),
        "joined_desc": User.created_at.desc(),
        "name_asc": func.lower(User.full_name).asc(),
        "name_desc": func.lower(User.full_name).desc(),
        "last_seen_asc": User.last_login_at.asc().nulls_last(),
        "last_seen_desc": User.last_login_at.desc().nulls_last(),
    }
    order_by = sort_map.get(sort, User.created_at.desc())
    stmt = stmt.offset(skip).limit(limit).order_by(order_by)
    students_result = await db.execute(stmt)
    students = list(students_result.scalars().all())

    result = []
    for student in students:
        lessons_completed = (
            await db.execute(
                select(func.count(StudentProgress.id)).where(
                    StudentProgress.student_id == student.id,
                    StudentProgress.status == "completed",
                )
            )
        ).scalar_one()

        agent_interactions = (
            await db.execute(
                select(func.count(AgentAction.id)).where(AgentAction.student_id == student.id)
            )
        ).scalar_one()

        result.append(
            {
                "id": str(student.id),
                "email": student.email,
                "full_name": student.full_name,
                "created_at": student.created_at.isoformat(),
                "last_login_at": student.last_login_at.isoformat()
                if student.last_login_at
                else None,
                "lessons_completed": lessons_completed,
                "agent_interactions": agent_interactions,
                "is_active": student.is_active,
                # D16/CP3.2 — feeds the cockpit's wa.me deep-link button.
                "whatsapp_number": student.whatsapp_number,
            }
        )

    return result


@router.get("/confusion-heatmap")
async def get_confusion_heatmap(
    days: int = Query(30, ge=1, le=180),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Top confusing concepts over the last `days` days (P2-13).

    Each bucket is one topic with help-request count, distinct students,
    last-seen timestamp, ranking score, and up to 3 sample questions.
    """
    buckets = await compute_heatmap(db, days=days, limit=limit)
    return [
        {
            "topic": b.topic,
            "help_count": b.help_count,
            "distinct_students": b.distinct_students,
            "last_seen": b.last_seen.isoformat() if b.last_seen else None,
            "score": b.score,
            "sample_questions": b.sample_questions,
        }
        for b in buckets
    ]


@router.get("/at-risk-students")
async def get_at_risk_students(
    limit: int = Query(25, ge=1, le=100),
    min_score: float = Query(0.35, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Students likely to churn with human-readable reasons (P2-14).

    Filter with `min_score` — default 0.35 — so admins see actionable names,
    not a full leaderboard. Each entry names the 1-3 dominant risk factors.
    """
    students = await compute_at_risk_students(db, limit=limit, min_score=min_score)
    return [
        {
            "student_id": s.student_id,
            "email": s.email,
            "full_name": s.full_name,
            "risk_score": s.risk_score,
            "reasons": s.reasons,
            "no_login_days": s.no_login_days,
            "lesson_stall_days": s.lesson_stall_days,
            "help_requests_recent": s.help_requests_recent,
            "help_requests_prior": s.help_requests_prior,
            "low_mood_count": s.low_mood_count,
            "progress_pct": s.progress_pct,
            "signals": [
                {"name": sig.name, "weight": sig.weight, "reason": sig.reason} for sig in s.signals
            ],
        }
        for s in students
    ]


async def _require_student(db: AsyncSession, student_id: uuid.UUID) -> User:
    user = (
        await db.execute(
            select(User).where(
                User.id == student_id, User.is_deleted.is_(False)
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Student not found"
        )
    return user


@router.get("/risk-panels")
async def get_risk_panels(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> dict[str, Any]:
    """F4 — five real retention-engine panels keyed off student_risk_signals.

    Returns the 5 slip-pattern panels in priority order. Each panel
    has its top-N students (by risk_score DESC) plus a total count
    so the UI can show "see all (N)" links.

    Schema (each panel):
      {
        "students": [{"user_id", "name", "email", "risk_score",
                      "risk_reason", "days_since_last_session",
                      "max_streak_ever", "paid"}, ...],
        "total": int
      }

    The 5 panels (ordered for triage):
      paid_silent       — refund risk, top of admin's morning queue
      capstone_stalled  — confidence churn, near-payoff
      streak_broken     — most recoverable
      promotion_avoidant — easy wins
      cold_signup       — bigger volume, lower per-student value

    Reads from student_risk_signals (computed by F1 nightly task).
    Cheap query — single index scan per panel.
    """
    from app.models.student_risk_signals import StudentRiskSignals

    PANELS = [
        "paid_silent",
        "capstone_stalled",
        "streak_broken",
        "promotion_avoidant",
        "cold_signup",
    ]
    PANEL_LIMIT = 10  # show top 10 per panel; UI can load-more later

    result: dict[str, Any] = {}
    # Both queries (top-N rows AND the total count) filter to real
    # students only — no admins, no deleted users. Without this filter
    # the panel total inflated by ~7 because F1's nightly task had
    # been scoring admin accounts too (now also fixed in the task).
    student_filter = (User.role == "student") & (User.is_deleted.is_(False))

    for slip_type in PANELS:
        # Top-N rows for the panel, joined with users for display name.
        rows_q = await db.execute(
            select(StudentRiskSignals, User)
            .join(User, StudentRiskSignals.user_id == User.id)
            .where(StudentRiskSignals.slip_type == slip_type, student_filter)
            .order_by(StudentRiskSignals.risk_score.desc())
            .limit(PANEL_LIMIT)
        )
        students = []
        for signal, user in rows_q.all():
            students.append(
                {
                    "user_id": str(user.id),
                    "name": user.full_name,
                    "email": user.email,
                    "risk_score": signal.risk_score,
                    "risk_reason": signal.risk_reason,
                    "days_since_last_session": signal.days_since_last_session,
                    "max_streak_ever": signal.max_streak_ever,
                    "paid": signal.paid,
                    "recommended_intervention": signal.recommended_intervention,
                }
            )

        # Total count for "see all (N)" links — same join + filter so
        # the displayed count equals the number of rows the panel can
        # actually surface.
        count_q = await db.execute(
            select(func.count(StudentRiskSignals.id))
            .join(User, StudentRiskSignals.user_id == User.id)
            .where(StudentRiskSignals.slip_type == slip_type, student_filter)
        )
        total = count_q.scalar() or 0
        result[slip_type] = {"students": students, "total": total}

    return result


@router.post(
    "/students/{student_id}/notes",
    response_model=StudentNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_student_note(
    student_id: uuid.UUID,
    payload: StudentNoteCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> StudentNoteResponse:
    """Record an admin intervention note on a student (P3 3A-18)."""
    await _require_student(db, student_id)
    note = await add_note(
        db,
        admin_id=admin.id,
        student_id=student_id,
        body_md=payload.body_md.strip(),
    )
    return StudentNoteResponse.model_validate(note)


@router.get(
    "/students/{student_id}/notes",
    response_model=list[StudentNoteResponse],
)
async def list_student_notes(
    student_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[StudentNoteResponse]:
    """Return notes for a student, newest first."""
    await _require_student(db, student_id)
    notes = await list_notes(db, student_id=student_id, limit=limit)
    return [StudentNoteResponse.model_validate(n) for n in notes]


# ── F11 — Refund offer routes ────────────────────────────────────────────────


class RefundOfferCreate(PydanticModel):
    """POST body for `/admin/students/{id}/refund-offer`."""

    reason: str | None = None


class RefundOfferResponse(PydanticModel):
    """Wire shape for refund_offers rows surfaced to the admin UI."""

    id: str
    user_id: str
    proposed_by: str | None
    status: str
    reason: str | None
    outreach_log_id: str | None
    proposed_at: datetime
    responded_at: datetime | None


def _refund_offer_to_response(offer: Any) -> RefundOfferResponse:
    return RefundOfferResponse(
        id=str(offer.id),
        user_id=str(offer.user_id),
        proposed_by=str(offer.proposed_by) if offer.proposed_by else None,
        status=offer.status,
        reason=offer.reason,
        outreach_log_id=str(offer.outreach_log_id) if offer.outreach_log_id else None,
        proposed_at=offer.proposed_at,
        responded_at=offer.responded_at,
    )


@router.post(
    "/students/{student_id}/refund-offer",
    response_model=RefundOfferResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_and_send_refund_offer(
    student_id: uuid.UUID,
    payload: RefundOfferCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> RefundOfferResponse:
    """F11 — propose + send a refund offer in one call.

    Two operations stitched together so the operator's "Send offer" click
    always lands a row + an email attempt. The send_refund_offer step is
    soft-fail: if SendGrid is mocked or throttled the row stays at
    status='sent' (mocked) or 'proposed' (throttled), so a retry button
    in the UI works against the same offer rather than spawning duplicates.
    """
    await _require_student(db, student_id)
    offer = await refund_offer_service.propose_refund(
        db,
        user_id=student_id,
        proposed_by_admin_id=admin.id,
        reason=payload.reason,
    )
    offer = await refund_offer_service.send_refund_offer(db, offer_id=offer.id)
    log.info(
        "admin.refund_offer.sent",
        admin_id=str(admin.id),
        student_id=str(student_id),
        offer_id=str(offer.id),
        status=offer.status,
    )
    return _refund_offer_to_response(offer)


@router.get(
    "/students/{student_id}/refund-offers",
    response_model=list[RefundOfferResponse],
)
async def list_student_refund_offers(
    student_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[RefundOfferResponse]:
    """Audit trail of every refund offer proposed for a student."""
    await _require_student(db, student_id)
    offers = await refund_offer_service.list_open_for_user(db, user_id=student_id)
    return [_refund_offer_to_response(o) for o in offers]


# ── #142: Audit log viewer ────────────────────────────────────────────────────


class AdminAuditLogItem(PydanticModel):
    id: str
    source: str  # "admin_audit_log" | "agent_actions"
    admin_email: str | None
    action_type: str
    resource_type: str | None
    resource_id: str | None
    summary: str
    created_at: datetime
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None


@router.get("/admin-audit-log", response_model=list[AdminAuditLogItem])
async def get_admin_audit_log(
    admin_id: uuid.UUID | None = Query(None),
    action_type: str | None = Query(None),
    resource_type: str | None = Query(None),
    resource_id: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[AdminAuditLogItem]:
    """Unified admin audit log — merges new admin_audit_log rows with legacy
    agent_actions rows (filtered to admin actors), sorted desc by created_at, capped at 200.
    """
    from app.models.admin_audit_log import AdminAuditLog

    stmt = select(AdminAuditLog)
    if admin_id is not None:
        stmt = stmt.where(AdminAuditLog.admin_id == admin_id)
    if action_type is not None:
        stmt = stmt.where(AdminAuditLog.action_type == action_type)
    if resource_type is not None:
        stmt = stmt.where(AdminAuditLog.resource_type == resource_type)
    if resource_id is not None:
        stmt = stmt.where(AdminAuditLog.resource_id == resource_id)
    if since is not None:
        stmt = stmt.where(AdminAuditLog.created_at >= since)
    if until is not None:
        stmt = stmt.where(AdminAuditLog.created_at <= until)
    stmt = stmt.order_by(AdminAuditLog.created_at.desc()).limit(200)
    new_rows = (await db.execute(stmt)).scalars().all()

    legacy_stmt = select(AgentAction).where(AgentAction.actor_role == "admin")
    if admin_id is not None:
        legacy_stmt = legacy_stmt.where(AgentAction.actor_id == admin_id)
    if action_type is not None:
        legacy_stmt = legacy_stmt.where(AgentAction.action_type == action_type)
    if since is not None:
        legacy_stmt = legacy_stmt.where(AgentAction.created_at >= since)
    if until is not None:
        legacy_stmt = legacy_stmt.where(AgentAction.created_at <= until)
    legacy_stmt = legacy_stmt.order_by(AgentAction.created_at.desc()).limit(200)
    legacy_rows = (await db.execute(legacy_stmt)).scalars().all()

    items: list[AdminAuditLogItem] = []
    for r in new_rows:
        items.append(
            AdminAuditLogItem(
                id=str(r.id),
                source="admin_audit_log",
                admin_email=r.admin_email,
                action_type=r.action_type,
                resource_type=r.resource_type,
                resource_id=r.resource_id,
                summary=f"{r.admin_email} · {r.action_type}"
                + (f" · {r.resource_type}:{r.resource_id}" if r.resource_type else ""),
                created_at=r.created_at,
                before=r.before_value,
                after=r.after_value,
                extra=r.extra,
            )
        )
    for r in legacy_rows:
        items.append(
            AdminAuditLogItem(
                id=str(r.id),
                source="agent_actions",
                admin_email=None,
                action_type=r.action_type,
                resource_type="agent",
                resource_id=r.agent_name,
                summary=f"admin · agent {r.agent_name} ({r.status})",
                created_at=r.created_at,
                before=r.input_data,
                after=r.output_data,
                extra=None,
            )
        )
    items.sort(key=lambda i: i.created_at, reverse=True)
    items = items[:200]
    log.info("admin.admin_audit_log_viewed", count=len(items))
    return items


@router.get("/audit-log", response_model=list[AuditLogItem])
async def get_audit_log(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[AuditLogItem]:
    """Paginated agent action audit log (#142)."""
    result = await db.execute(
        select(AgentAction)
        .order_by(AgentAction.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    log.info("admin.audit_log_viewed", limit=limit, offset=offset, count=len(rows))
    return [
        AuditLogItem(
            id=str(r.id),
            student_id=str(r.student_id) if r.student_id else None,
            agent_name=r.agent_name,
            action_type=r.action_type,
            status=r.status,
            duration_ms=r.duration_ms,
            created_at=r.created_at,
            actor_id=str(r.actor_id) if r.actor_id else None,
            actor_role=r.actor_role,
            on_behalf_of=str(r.on_behalf_of) if r.on_behalf_of else None,
        )
        for r in rows
    ]


# ── DISC-55: Student activity timeline ──────────────────────────────────────


# Friendly labels for every agent the student can interact with. The
# timeline becomes prose ("Generated a weekly progress report") instead
# of raw audit-log identifiers ("Agent `progress_report` (completed)").
# Add new agents here as they ship.
_AGENT_VERBS: dict[str, str] = {
    "adaptive_path": "Suggested a learning path",
    "adaptive_quiz": "Ran an adaptive quiz",
    "billing_support": "Answered a billing question",
    "career_coach": "Coached on career direction",
    # code_review + coding_assistant — D11 cutover absorbed both into
    # senior_engineer (Pass 3c E2). Activity-feed strings keyed by
    # "senior_engineer" cover both legacy paths going forward; the
    # 0059 data migration consolidates historical agent_actions rows
    # so the dashboard query stays consistent across pre/post-cutover.
    "senior_engineer": "Reviewed code or helped debug",
    "community_celebrator": "Celebrated a milestone",
    "content_ingestion": "Ingested new course content",
    "curriculum_mapper": "Mapped curriculum",
    "deep_capturer": "Captured a weekly synthesis",
    "disrupt_prevention": "Sent a re-engagement nudge",
    "job_match": "Matched against open roles",
    "knowledge_graph": "Updated the knowledge graph",
    "mcq_factory": "Generated quiz questions",
    "mock_interview": "Ran a mock interview",
    "moa": "Routed a request",
    "peer_matching": "Matched with study peers",
    "portfolio_builder": "Built a portfolio entry",
    "progress_report": "Generated a weekly progress report",
    "project_evaluator": "Evaluated a project",
    "socratic_tutor": "Answered with the Socratic tutor",
    "spaced_repetition": "Scheduled spaced-repetition review",
    "student_buddy": "Gave a quick explanation",
}


def _humanize_agent_event(agent_name: str, status: str) -> str:
    """Turn an agent_action row into prose.

    Examples:
      ("disrupt_prevention", "completed")    → "Sent a re-engagement nudge"
      ("progress_report",     "failed")      → "Weekly progress report failed to run"
      ("unknown_agent",       "completed")   → "Ran the unknown_agent agent"
    """
    verb = _AGENT_VERBS.get(agent_name)
    if verb is None:
        # Fallback for agents not yet in the map — humanize the key but
        # keep the snake_case readable rather than backtick-quoting it.
        pretty = agent_name.replace("_", " ")
        verb = f"Ran the {pretty} agent"
    if status == "completed":
        return verb
    if status == "failed":
        # Lowercase the first word so "X failed to run" reads naturally.
        first, _, rest = verb.partition(" ")
        return f"{first.lower()} {rest} — failed to run".capitalize()
    # Pending / running / cancelled — surface status as a soft suffix.
    return f"{verb} ({status})"


def _humanize_submission(
    lab_title: str | None, status: str, score: int | None
) -> str:
    """Turn an exercise_submission row into prose.

    Examples:
      ("Async retries", "passed",  91) → "Passed “Async retries” with score 91 / 100"
      ("Async retries", "failed",  None) → "Submitted “Async retries” — needs another try"
      (None,            "graded",  85) → "Submission graded · score 85"
    """
    title_quoted = f"“{lab_title}”" if lab_title else None
    if status == "passed":
        if score is not None and title_quoted:
            return f"Passed {title_quoted} with score {score} / 100"
        if score is not None:
            return f"Passed a lab with score {score} / 100"
        return f"Passed {title_quoted}" if title_quoted else "Passed a lab"
    if status == "failed":
        if title_quoted:
            return f"Submitted {title_quoted} — needs another try"
        return "Submitted a lab — needs another try"
    if status == "graded":
        if score is not None and title_quoted:
            return f"Graded {title_quoted} · score {score} / 100"
        if score is not None:
            return f"Submission graded · score {score} / 100"
        return f"Graded {title_quoted}" if title_quoted else "Submission graded"
    # pending / submitted / etc. — neutral phrasing.
    if title_quoted:
        return f"Submitted {title_quoted}"
    return "Submitted a lab"


@router.get(
    "/students/{student_id}/timeline",
    response_model=list[StudentTimelineEvent],
)
async def get_student_timeline(
    student_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = Query(
        None,
        description=(
            "F14 — paginate older. Returns events strictly older than this "
            "ISO-8601 timestamp. Pass the `at` of the oldest event from the "
            "previous page as a cursor."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[StudentTimelineEvent]:
    """Merged activity timeline for admin drilldown (DISC-55).

    Pulls from three sources — agent actions, lesson completions, exercise
    submissions — and merges newest-first. `login` events are derived from
    `users.last_login_at` as a best-effort anchor since we don't persist a
    login-history table yet.

    F14 — pagination via `?before=<iso-ts>` cursor. The page is the next
    `limit` events strictly older than `before`. Skips the synthetic
    "Last login" anchor on paginated requests since it's a single point,
    not a series.
    """
    from app.models.exercise import Exercise
    from app.models.exercise_submission import ExerciseSubmission
    from app.models.lesson import Lesson
    from app.models.student_progress import StudentProgress

    await _require_student(db, student_id)
    events: list[StudentTimelineEvent] = []

    agent_stmt = (
        select(AgentAction)
        .where(AgentAction.student_id == student_id)
        .order_by(AgentAction.created_at.desc())
        .limit(limit)
    )
    if before is not None:
        agent_stmt = agent_stmt.where(AgentAction.created_at < before)
    agent_rows = (await db.execute(agent_stmt)).scalars().all()
    for row in agent_rows:
        events.append(
            StudentTimelineEvent(
                kind="agent_action",
                at=row.created_at,
                summary=_humanize_agent_event(row.agent_name, row.status),
                detail={
                    "agent_name": row.agent_name,
                    "duration_ms": row.duration_ms,
                    "actor_role": row.actor_role,
                },
            )
        )

    lesson_stmt = (
        select(StudentProgress, Lesson.title)
        .join(Lesson, StudentProgress.lesson_id == Lesson.id)
        .where(
            StudentProgress.student_id == student_id,
            StudentProgress.status == "completed",
        )
        .order_by(StudentProgress.completed_at.desc())
        .limit(limit)
    )
    if before is not None:
        lesson_stmt = lesson_stmt.where(StudentProgress.completed_at < before)
    lesson_rows = (await db.execute(lesson_stmt)).all()
    for rec, title in lesson_rows:
        if rec.completed_at is None:
            continue
        events.append(
            StudentTimelineEvent(
                kind="lesson_completed",
                at=rec.completed_at,
                summary=f"Completed lesson: {title}",
                detail={"lesson_id": str(rec.lesson_id)},
            )
        )

    sub_stmt = (
        select(ExerciseSubmission, Exercise.title)
        .join(Exercise, ExerciseSubmission.exercise_id == Exercise.id)
        .where(ExerciseSubmission.student_id == student_id)
        .order_by(ExerciseSubmission.created_at.desc())
        .limit(limit)
    )
    if before is not None:
        sub_stmt = sub_stmt.where(ExerciseSubmission.created_at < before)
    sub_rows = (await db.execute(sub_stmt)).all()
    for sub, lab_title in sub_rows:
        events.append(
            StudentTimelineEvent(
                kind="submission",
                at=sub.created_at,
                summary=_humanize_submission(lab_title, sub.status, sub.score),
                detail={
                    "exercise_id": str(sub.exercise_id),
                    "status": sub.status,
                    "score": sub.score,
                },
            )
        )

    # D16/CP3.3 — outreach_log entries on the timeline. Surfaces every
    # contact (email, in_app DM, WhatsApp, phone) as a single event kind
    # with channel in the detail dict. The frontend renders a channel
    # badge per row so admin sees "WhatsApp · 5d ago, email · 3d ago,
    # ghosted both" at a glance.
    from app.models.outreach_log import OutreachLog as _OutreachLog

    outreach_stmt = (
        select(_OutreachLog)
        .where(_OutreachLog.user_id == student_id)
        .order_by(_OutreachLog.sent_at.desc())
        .limit(limit)
    )
    if before is not None:
        outreach_stmt = outreach_stmt.where(_OutreachLog.sent_at < before)
    outreach_rows = (await db.execute(outreach_stmt)).scalars().all()
    for out in outreach_rows:
        # Summary varies by trigger source: admin_manual is a deliberate
        # operator action (worth highlighting); system_nightly is the F9
        # automated outreach. Channel is always in the detail dict so
        # the frontend can pick the right badge.
        if out.triggered_by == "admin_manual":
            verb = "Admin contacted via" if out.channel != "in_app" else "Admin DM via"
        else:
            verb = "System sent via"
        summary = f"{verb} {out.channel}"
        if out.template_key:
            summary += f" · {out.template_key}"
        events.append(
            StudentTimelineEvent(
                kind="outreach",
                at=out.sent_at,
                summary=summary,
                detail={
                    "channel": out.channel,
                    "triggered_by": out.triggered_by,
                    "template_key": out.template_key,
                    "status": out.status,
                    "body_preview": out.body_preview,
                    "replied_at": out.replied_at.isoformat()
                    if out.replied_at
                    else None,
                },
            )
        )

    # The synthetic "Last login" anchor is a single point in time, not a
    # series — including it on every page would duplicate it forever.
    # Only include on the first page (no `before` cursor).
    if before is None:
        user_row = (
            await db.execute(select(User).where(User.id == student_id))
        ).scalar_one_or_none()
        if user_row and user_row.last_login_at:
            events.append(
                StudentTimelineEvent(
                    kind="login",
                    at=user_row.last_login_at,
                    summary="Last signed in",
                )
            )

    events.sort(key=lambda e: e.at, reverse=True)
    return events[:limit]


# ── DISC-57: Admin agent trigger ────────────────────────────────────────────


@router.post(
    "/agents/{agent_name}/trigger",
    response_model=TriggerAgentResponse,
)
async def trigger_agent(
    agent_name: str,
    payload: TriggerAgentRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> TriggerAgentResponse:
    """Admin invokes a named agent against a student (DISC-57).

    The run logs to `agent_actions` with `actor_id=admin.id`,
    `actor_role="admin"`, and `on_behalf_of=student.id`, producing the audit
    attribution AD8 verifies. Default task defers to the agent's own
    description when the caller didn't supply one.
    """
    from app.agents.base_agent import AgentState
    from app.agents.registry import _ensure_registered, get_agent

    try:
        student_uuid = uuid.UUID(payload.student_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid student_id") from exc

    student = await _require_student(db, student_uuid)

    _ensure_registered()
    try:
        agent = get_agent(agent_name)
    except KeyError as exc:
        log.warning("admin.agent_trigger.unknown_agent", agent=agent_name, error=str(exc))
        raise HTTPException(status_code=404, detail="Agent not found.") from exc

    task = payload.task or f"Admin-triggered run of {agent_name} for {student.email}."
    state = AgentState(
        student_id=str(student.id),
        task=task,
        context={
            "actor_id": str(admin.id),
            "actor_role": "admin",
            "on_behalf_of": str(student.id),
            "trigger": "admin_manual",
        },
    )

    start = datetime.now(UTC)
    try:
        result = await agent.run(state)
        status_out = "completed"
    except Exception as exc:  # log_action already persists the failure
        log.exception("admin.agent_trigger.failed", agent=agent_name, error=str(exc))
        raise HTTPException(
            status_code=500, detail="Agent run failed. Please try again."
        ) from exc
    duration = int((datetime.now(UTC) - start).total_seconds() * 1000)

    preview = (result.response or "").strip()
    if len(preview) > 280:
        preview = preview[:277] + "..."

    log.info(
        "admin.agent_triggered",
        agent=agent_name,
        admin_id=str(admin.id),
        student_id=str(student.id),
        duration_ms=duration,
    )
    return TriggerAgentResponse(
        agent_name=agent_name,
        status=status_out,
        duration_ms=duration,
        response_preview=preview,
    )


# ── #148: Content performance per-lesson stats ───────────────────────────────


@router.get("/content-performance", response_model=list[LessonPerformance])
async def get_content_performance(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[LessonPerformance]:
    """Per-lesson confusion and question event counts (#148)."""
    from app.models.lesson import Lesson

    # Fetch up to 1000 recent actions; group in Python to stay DB-agnostic
    result = await db.execute(
        select(AgentAction).order_by(AgentAction.created_at.desc()).limit(1000)
    )
    actions = result.scalars().all()

    # Extract lesson_id from input_data JSON (key: "lesson_id")
    from collections import defaultdict

    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "confusion": 0})
    for action in actions:
        lid: str | None = None
        if isinstance(action.input_data, dict):
            lid = action.input_data.get("lesson_id")
        if not lid:
            continue
        counts[lid]["total"] += 1
        if action.agent_name == "socratic_tutor":
            counts[lid]["confusion"] += 1

    if not counts:
        return []

    lesson_ids = [uuid.UUID(lid) for lid in counts if lid]
    lessons_result = await db.execute(
        select(Lesson.id, Lesson.title).where(Lesson.id.in_(lesson_ids))
    )
    title_map = {str(r.id): r.title for r in lessons_result.all()}

    rows = sorted(counts.items(), key=lambda kv: kv[1]["total"], reverse=True)[:50]
    log.info("admin.content_performance_viewed", lesson_count=len(rows))
    return [
        LessonPerformance(
            lesson_id=lid,
            lesson_title=title_map.get(lid, lid),
            question_count=vals["total"],
            confusion_count=vals["confusion"],
        )
        for lid, vals in rows
    ]


# ── Course + rubric JSON editor (folds #144 + #145) ──────────────────────────


@router.patch("/courses/{course_id}", status_code=204)
async def update_course(
    course_id: uuid.UUID,
    body: CourseUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> None:
    """Update course title/description/pricing/featured (#144)."""
    from app.models.course import Course

    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    if body.difficulty is not None and body.difficulty not in {
        "beginner",
        "intermediate",
        "advanced",
    }:
        raise HTTPException(status_code=400, detail="invalid difficulty")

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}

    def _track(field: str, new_val: Any) -> None:
        cur = getattr(course, field)
        if cur != new_val:
            before[field] = cur
            after[field] = new_val

    if body.title is not None:
        _track("title", body.title)
        course.title = body.title
    if body.description is not None:
        _track("description", body.description)
        course.description = body.description
    if body.is_published is not None:
        _track("is_published", body.is_published)
        course.is_published = body.is_published
    if body.price_cents is not None:
        _track("price_cents", body.price_cents)
        course.price_cents = body.price_cents
    if body.difficulty is not None:
        _track("difficulty", body.difficulty)
        course.difficulty = body.difficulty
    if body.is_featured is not None:
        _track("is_featured", body.is_featured)
        course.is_featured = body.is_featured

    if after:
        await AdminAuditService.log(
            db=db,
            admin=admin_user,
            action_type="course.update",
            resource_type="course",
            resource_id=str(course_id),
            before=before,
            after=after,
            request=request,
        )
    await db.commit()
    log.info("admin.course_updated", course_id=str(course_id))


@router.patch("/exercises/{exercise_id}/rubric", status_code=204)
async def update_exercise_rubric(
    exercise_id: uuid.UUID,
    body: ExerciseRubricUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> None:
    """Update exercise rubric and test cases (#145)."""
    from app.models.exercise import Exercise

    result = await db.execute(select(Exercise).where(Exercise.id == exercise_id))
    exercise = result.scalar_one_or_none()
    if not exercise:
        raise HTTPException(status_code=404, detail="Exercise not found")
    before = {"rubric": exercise.rubric, "test_cases": exercise.test_cases}
    exercise.rubric = body.rubric
    if body.test_cases is not None:
        exercise.test_cases = body.test_cases  # type: ignore[assignment]
    await AdminAuditService.log(
        db=db,
        admin=admin_user,
        action_type="exercise.rubric_update",
        resource_type="exercise",
        resource_id=str(exercise_id),
        before=before,
        after={"rubric": body.rubric, "test_cases": body.test_cases},
        request=request,
    )
    await db.commit()
    log.info("admin.rubric_updated", exercise_id=str(exercise_id))


@router.get("/pulse")
async def get_pulse(
    window: str = Query(
        "24h",
        pattern="^(24h|7d|30d)$",
        description="F12 — rolling window for activity metrics: 24h, 7d, or 30d.",
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> dict[str, Any]:
    """5-metric platform health view (#180).

    F12 — `window` controls active students / agent calls / avg eval
    score windows. New enrollments stays 7d (it's a leading-edge funnel
    signal, not an activity series), and open feedback is a snapshot
    count regardless of window. Legacy `_24h` / `_7d` suffixed keys are
    preserved for backwards-compat with any existing consumers; new
    callers should read the unsuffixed keys + `window` field.
    """
    from app.models.enrollment import Enrollment
    from app.models.feedback import Feedback

    window_map = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }
    delta = window_map[window]

    now = datetime.now(UTC)
    cutoff = now - delta
    week_ago = now - timedelta(days=7)

    active_students: int = (
        await db.execute(
            select(func.count(func.distinct(AgentAction.student_id))).where(
                AgentAction.created_at >= cutoff
            )
        )
    ).scalar() or 0

    agent_calls: int = (
        await db.execute(
            select(func.count(AgentAction.id)).where(AgentAction.created_at >= cutoff)
        )
    ).scalar() or 0

    # evaluation_score is not a dedicated column — derive from output_data or use 0
    # (future: add evaluation_score column to agent_actions)
    avg_score_raw = (
        await db.execute(
            select(func.avg(AgentAction.duration_ms)).where(
                AgentAction.created_at >= cutoff,
                AgentAction.duration_ms.isnot(None),
            )
        )
    ).scalar()
    # Normalise: treat 0 ms → 0.0, ≥2000 ms → 1.0 as a proxy quality indicator
    avg_duration = float(avg_score_raw or 0)
    avg_score: float = round(min(avg_duration / 2000.0, 1.0), 2)

    new_enrollments: int = (
        await db.execute(select(func.count(Enrollment.id)).where(Enrollment.created_at >= week_ago))
    ).scalar() or 0

    open_feedback: int = (
        await db.execute(
            select(func.count(Feedback.id)).where(Feedback.resolved.is_(False))  # noqa: E712
        )
    ).scalar() or 0

    log.info("admin.pulse_viewed", window=window, active_students=active_students)
    return {
        "window": window,
        "active_students": active_students,
        "agent_calls": agent_calls,
        "avg_eval_score": avg_score,
        "new_enrollments_7d": new_enrollments,
        "open_feedback": open_feedback,
        # Legacy aliases — only populated for the 24h window so existing
        # consumers reading `_24h` keys see the same value they did
        # before. For 7d/30d these are intentionally absent so a stale
        # consumer fails loudly instead of silently mixing windows.
        **(
            {
                "active_students_24h": active_students,
                "agent_calls_24h": agent_calls,
                "avg_eval_score_24h": avg_score,
            }
            if window == "24h"
            else {}
        ),
    }


# P1-5 — weekly rollup of thumbs up/down feedback per agent. The service layer
# (`ChatService.feedback_rollup`) joins `chat_message_feedback` against
# `chat_messages` so we can filter by agent name, then aggregates reason
# counts + sample comments in Python (avoids dialect-specific JSON unnesting).
@router.get("/chat-feedback")
async def get_chat_feedback_rollup(
    agent_name: str | None = Query(default=None, max_length=100),
    since_days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> dict[str, Any]:
    """Aggregate thumbs feedback across a recent window for an agent.

    Response shape:
      `{up_count, down_count, top_reasons: [{reason, count}],
        sample_comments: [str, ...]}`
    """
    from app.services.chat_service import ChatService

    since = datetime.now(UTC) - timedelta(days=since_days)
    service = ChatService(db)
    return await service.feedback_rollup(agent_name=agent_name, since=since)


# ── Admin Console v1 (CareerForge_admin_v1.html) ─────────────────────────────


class AdminConsoleStudent(PydanticModel):
    id: str
    name: str
    track: str
    stage: str
    progress: int
    streak: int
    last_seen: int
    risk: int
    paid: bool
    joined: str
    city: str | None
    email: str | None
    sessions14: int
    flashcards: int
    agent_q: int
    reviews: int
    notes: int
    labs: int
    capstones: int
    purchases: int
    risk_reason: str | None = None
    # D16/CP3.2 — manual-WhatsApp outreach destination. Empty/None ⇒
    # cockpit hides the wa.me deep-link button on the per-student panel.
    whatsapp_number: str | None = None


class AdminConsolePulseCard(PydanticModel):
    metric_key: str
    label: str
    value: str
    unit: str
    delta: int
    delta_text: str
    color: str
    invert_delta: bool
    spark: list[float]


class AdminConsoleFunnelStage(PydanticModel):
    name: str
    count: int


class AdminConsoleFeatureTile(PydanticModel):
    feature_key: str
    name: str
    count: str
    sub: str
    cold: bool
    bars: list[int]


class AdminConsoleCallItem(PydanticModel):
    student_id: str
    time: str
    reason: str


class AdminConsoleEventItem(PydanticModel):
    student_id: str | None
    kind: str
    text: str
    time_label: str


class AdminConsoleRevenue(PydanticModel):
    month_total: str
    new_purchases: str
    renewals: str
    refunds: str
    spark: list[float]


class AdminConsoleResponse(PydanticModel):
    students: list[AdminConsoleStudent]
    pulse: list[AdminConsolePulseCard]
    funnel: list[AdminConsoleFunnelStage]
    features: list[AdminConsoleFeatureTile]
    calls: list[AdminConsoleCallItem]
    events: list[AdminConsoleEventItem]
    revenue: AdminConsoleRevenue
    synced_at: datetime


def _format_event_time(occurred_at: datetime) -> str:
    delta = datetime.now(UTC) - occurred_at
    minutes = int(delta.total_seconds() // 60)
    if minutes <= 1:
        return "now"
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    return f"{hours // 24}d"


def _fmt_int(n: int | float) -> str:
    """Format a count for the pulse strip display_value field."""
    n = int(n)
    if n < 1000:
        return str(n)
    if n < 10000:
        return f"{n:,}"
    return f"{n / 1000:.1f}k"


def _delta_pct(curr: float, prior: float) -> int:
    if prior <= 0:
        return 100 if curr > 0 else 0
    return int(round((curr - prior) / prior * 100))


async def _daily_buckets(
    db: AsyncSession,
    column,
    where_clause,
    now: datetime,
    days: int = 14,
) -> list[float]:
    """Group `where_clause` rows by UTC day for the last `days` days.

    Returns a list of length `days`, oldest first. Days with no rows = 0.
    """
    start = (now - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    bucket_col = func.date_trunc("day", column).label("bucket")
    rows = (
        await db.execute(
            select(bucket_col, func.count())
            .where(where_clause, column >= start)
            .group_by(bucket_col)
        )
    ).all()
    by_day: dict[date, int] = {row[0].date(): int(row[1]) for row in rows}
    out: list[float] = []
    for i in range(days):
        d = (start + timedelta(days=i)).date()
        out.append(float(by_day.get(d, 0)))
    return out


async def _compute_live_calls(
    db: AsyncSession,
    now: datetime,
) -> list[AdminConsoleCallItem]:
    """LD-5: today's call list. We don't have a dedicated
    `scheduled_call` outreach kind yet, so for now we surface the
    students that the operator has reached out to manually today
    via outreach_log (triggered_by='admin_manual'). The future
    F-extension introduces a proper scheduled_at column.
    """
    from app.models.outreach_log import OutreachLog

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    rows = (
        await db.execute(
            select(OutreachLog, User)
            .join(User, User.id == OutreachLog.user_id)
            .where(
                OutreachLog.triggered_by == "admin_manual",
                OutreachLog.sent_at >= today_start,
            )
            .order_by(OutreachLog.sent_at.asc())
            .limit(20)
        )
    ).all()

    out: list[AdminConsoleCallItem] = []
    for log_row, user in rows:
        out.append(
            AdminConsoleCallItem(
                student_id=str(user.id),
                time=log_row.sent_at.strftime("%H:%M"),
                reason=log_row.body_preview[:60] if log_row.body_preview else "Manual outreach",
            )
        )
    return out


async def _compute_live_events(
    db: AsyncSession,
    now: datetime,
) -> list[AdminConsoleEventItem]:
    """LD-5: live event feed from cohort_events.

    cohort_events is populated by various agents on lifecycle
    moments (promotion, capstone shipped, streak started, milestone).
    Already uses masked actor_handle so first-name + last-initial
    privacy is preserved.
    """
    from app.models.cohort_event import CohortEvent

    rows = (
        await db.execute(
            select(CohortEvent)
            .order_by(CohortEvent.occurred_at.desc())
            .limit(20)
        )
    ).scalars().all()

    # Map cohort_event.kind to the UI's CSS color class. The UI
    # already styles 5 known kinds: promo, capstone, purchase,
    # review, signup. Map the cohort_event vocabulary onto those.
    KIND_MAP = {
        "level_up": "promo",
        "promotion_earned": "promo",
        "capstone_shipped": "capstone",
        "purchase": "purchase",
        "purchase_made": "purchase",
        "review_requested": "review",
        "signup": "signup",
        "streak_started": "signup",
        "milestone": "promo",
    }

    out: list[AdminConsoleEventItem] = []
    for ev in rows:
        ui_kind = KIND_MAP.get(ev.kind, ev.kind)
        out.append(
            AdminConsoleEventItem(
                student_id=str(ev.actor_id) if ev.actor_id else None,
                kind=ui_kind,
                text=ev.label,
                time_label=_format_event_time(ev.occurred_at),
            )
        )
    return out


async def _compute_live_revenue(
    db: AsyncSession,
    now: datetime,
    pulse: list[AdminConsolePulseCard],
) -> AdminConsoleRevenue:
    """LD-5: revenue card from payments + refunds tables.

    Surfaces month-to-date total, count + total of new purchases this
    month, count + total of renewals this month (proxied as repeat
    payments from same user), and refunds this month. Spark reuses
    the MRR pulse card's spark for cohesion.
    """
    from app.models.payment import Payment
    from app.models.refund import Refund

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Month total ($)
    month_total_cents = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
                Payment.created_at >= month_start,
                Payment.status == "succeeded",
            )
        )
    ).scalar() or 0
    month_total_dollars = float(month_total_cents) / 100.0

    # All succeeded payments this month — used to split into "new"
    # vs "renewal" (a user's first-ever payment is new; subsequent
    # are renewals).
    pay_rows = (
        await db.execute(
            select(Payment.user_id, Payment.amount_cents, Payment.created_at).where(
                Payment.status == "succeeded",
                Payment.created_at >= month_start,
            )
        )
    ).all()

    # Per user: was this month their first-ever payment?
    first_pay_cache: dict[uuid.UUID, datetime] = {}
    if pay_rows:
        user_ids = {row[0] for row in pay_rows}
        first_rows = (
            await db.execute(
                select(Payment.user_id, func.min(Payment.created_at))
                .where(
                    Payment.status == "succeeded",
                    Payment.user_id.in_(user_ids),
                )
                .group_by(Payment.user_id)
            )
        ).all()
        first_pay_cache = {uid: ts for uid, ts in first_rows}

    new_count = 0
    new_cents = 0
    renew_count = 0
    renew_cents = 0
    for user_id, cents, created in pay_rows:
        first = first_pay_cache.get(user_id)
        if first is not None and first >= month_start:
            new_count += 1
            new_cents += cents
        else:
            renew_count += 1
            renew_cents += cents

    # Refunds this month — count rows.
    refund_count = (
        await db.execute(
            select(func.count(Refund.id)).where(Refund.created_at >= month_start)
        )
    ).scalar() or 0

    def _money(d: float) -> str:
        if d >= 1000:
            return f"${d / 1000:.1f}k"
        return f"${int(d)}"

    mrr_pulse = next((p for p in pulse if p.metric_key == "mrr"), None)
    return AdminConsoleRevenue(
        month_total=_money(month_total_dollars),
        new_purchases=f"{new_count} · {_money(new_cents / 100.0)}",
        renewals=f"{renew_count} · {_money(renew_cents / 100.0)}",
        refunds=str(int(refund_count)),
        spark=mrr_pulse.spark if mrr_pulse else [],
    )


async def _compute_live_features(
    db: AsyncSession,
    now: datetime,
) -> list[AdminConsoleFeatureTile]:
    """LD-4: Compute the 8 feature-pulse tiles from live data.

    Each tile shows current week count + delta vs prior week + 7-day
    daily sparkline. Dimming (`cold`) flag fires when current week
    is less than half of prior week.
    """
    from app.models.ai_review import AIReview
    from app.models.exercise import Exercise
    from app.models.exercise_submission import ExerciseSubmission
    from app.models.interview_session import InterviewSession
    from app.models.jd_decoder import JdMatchScore
    from app.models.notebook_entry import NotebookEntry
    from app.models.srs_card import SRSCard

    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    async def _count_and_spark(column, where_filter) -> tuple[int, int, list[int]]:
        """Returns (current_week_count, prior_week_count, 7-day spark)."""
        curr = (
            await db.execute(
                select(func.count())
                .select_from(where_filter.froms[0] if hasattr(where_filter, "froms") else None)
                .where(column >= week_ago)
            )
        ).scalar() if False else None
        # Simpler: use the same filter, just adjust the time window.
        curr = (
            await db.execute(where_filter.where(column >= week_ago))
        ).scalar() or 0
        prior = (
            await db.execute(
                where_filter.where(column >= two_weeks_ago, column < week_ago)
            )
        ).scalar() or 0

        # 7-day spark.
        spark_start = (now - timedelta(days=6)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        bucket_col = func.date_trunc("day", column)
        spark_rows = (
            await db.execute(
                where_filter.with_only_columns(
                    bucket_col.label("bucket"), func.count()
                ).where(column >= spark_start).group_by(bucket_col)
            )
        ).all()
        by_day: dict[date, int] = {row[0].date(): int(row[1]) for row in spark_rows}
        spark = []
        for i in range(7):
            d = (spark_start + timedelta(days=i)).date()
            spark.append(by_day.get(d, 0))
        return int(curr), int(prior), spark

    def _make_tile(
        feature_key: str,
        name: str,
        curr: int,
        prior: int,
        bars: list[int],
    ) -> AdminConsoleFeatureTile:
        if prior == 0:
            sub = "this week · new" if curr > 0 else "no activity yet"
            cold = False
        else:
            pct = int(round((curr - prior) / prior * 100))
            arrow = "▲" if pct >= 0 else "▼"
            sub = f"this week · {arrow} {abs(pct)}%"
            cold = curr < 0.5 * prior
        return AdminConsoleFeatureTile(
            feature_key=feature_key,
            name=name,
            count=_fmt_int(curr),
            sub=sub,
            cold=cold,
            bars=bars,
        )

    # Each feature's base SELECT — count over the appropriate column.
    flashcards_curr, flashcards_prior, flashcards_bars = await _count_and_spark(
        SRSCard.last_reviewed_at,
        select(func.count(SRSCard.id)).where(SRSCard.last_reviewed_at.is_not(None)),
    )
    agent_q_curr, agent_q_prior, agent_q_bars = await _count_and_spark(
        AgentAction.created_at,
        select(func.count(AgentAction.id)).where(
            AgentAction.agent_name == "socratic_tutor"
        ),
    )
    senior_curr, senior_prior, senior_bars = await _count_and_spark(
        AIReview.created_at,
        select(func.count(AIReview.id)),
    )
    notes_curr, notes_prior, notes_bars = await _count_and_spark(
        NotebookEntry.graduated_at,
        select(func.count(NotebookEntry.id)).where(
            NotebookEntry.graduated_at.is_not(None)
        ),
    )
    labs_curr, labs_prior, labs_bars = await _count_and_spark(
        ExerciseSubmission.created_at,
        select(func.count(ExerciseSubmission.id))
        .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
        .where(Exercise.is_capstone.is_(False)),
    )
    cap_curr, cap_prior, cap_bars = await _count_and_spark(
        ExerciseSubmission.created_at,
        select(func.count(ExerciseSubmission.id))
        .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
        .where(Exercise.is_capstone.is_(True)),
    )
    jd_curr, jd_prior, jd_bars = await _count_and_spark(
        JdMatchScore.created_at,
        select(func.count(JdMatchScore.id)),
    )
    iv_curr, iv_prior, iv_bars = await _count_and_spark(
        InterviewSession.created_at,
        select(func.count(InterviewSession.id)),
    )

    return [
        _make_tile("flashcards", "Flashcard reviews", flashcards_curr, flashcards_prior, flashcards_bars),
        _make_tile("agent_q", "Agent questions", agent_q_curr, agent_q_prior, agent_q_bars),
        _make_tile("senior_reviews", "Senior reviews", senior_curr, senior_prior, senior_bars),
        _make_tile("notes", "Notes graduated", notes_curr, notes_prior, notes_bars),
        _make_tile("labs", "Lab completions", labs_curr, labs_prior, labs_bars),
        _make_tile("capstones", "Capstone submissions", cap_curr, cap_prior, cap_bars),
        _make_tile("jd_match", "JD Match runs", jd_curr, jd_prior, jd_bars),
        _make_tile("interview", "Interview Coach", iv_curr, iv_prior, iv_bars),
    ]


async def _compute_live_funnel(
    db: AsyncSession,
) -> list[AdminConsoleFunnelStage]:
    """LD-3: Compute the 7-stage learner funnel from live data.

    Stages, all over the entire student population:
      Signups       — every student in users table
      Onboarded     — has a goal_contracts row (completed onboarding)
      First lesson  — has at least one student_progress completed
      Paid          — has at least one course_entitlements row
      Capstone      — has submitted at least one capstone exercise
      Promoted      — users.promoted_at IS NOT NULL
      Hired         — placeholder; we don't track hires yet, returns 0
    """
    from app.models.course_entitlement import CourseEntitlement
    from app.models.exercise import Exercise
    from app.models.exercise_submission import ExerciseSubmission
    from app.models.goal_contract import GoalContract
    from app.models.student_progress import StudentProgress

    # Signups — every student.
    signups = (
        await db.execute(
            select(func.count(User.id)).where(
                User.role == "student", User.is_deleted.is_(False)
            )
        )
    ).scalar() or 0

    # Onboarded — has ever created a goal_contracts row.
    # Intentionally NO expires_at filter: "has onboarded" is a lifetime
    # event; a student remains counted even after their contract expires.
    # D12 CP3 Part D.5 — do not add expires_at here without a product decision.
    onboarded = (
        await db.execute(
            select(func.count(func.distinct(GoalContract.user_id)))
            .join(User, User.id == GoalContract.user_id)
            .where(User.role == "student", User.is_deleted.is_(False))
        )
    ).scalar() or 0

    # First lesson — has at least one completed student_progress row.
    first_lesson = (
        await db.execute(
            select(func.count(func.distinct(StudentProgress.student_id)))
            .join(User, User.id == StudentProgress.student_id)
            .where(
                User.role == "student",
                User.is_deleted.is_(False),
                StudentProgress.status == "completed",
            )
        )
    ).scalar() or 0

    # Paid — has at least one entitlement row.
    paid = (
        await db.execute(
            select(func.count(func.distinct(CourseEntitlement.user_id)))
            .join(User, User.id == CourseEntitlement.user_id)
            .where(User.role == "student", User.is_deleted.is_(False))
        )
    ).scalar() or 0

    # Capstone — has submitted at least one capstone exercise.
    capstone = (
        await db.execute(
            select(func.count(func.distinct(ExerciseSubmission.student_id)))
            .join(User, User.id == ExerciseSubmission.student_id)
            .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
            .where(
                User.role == "student",
                User.is_deleted.is_(False),
                Exercise.is_capstone.is_(True),
            )
        )
    ).scalar() or 0

    # Promoted — users.promoted_at IS NOT NULL.
    promoted = (
        await db.execute(
            select(func.count(User.id)).where(
                User.role == "student",
                User.is_deleted.is_(False),
                User.promoted_at.is_not(None),
            )
        )
    ).scalar() or 0

    # Hired — we don't track hires yet. Future: a `users.hired_at`
    # column or a separate `placements` table.
    hired = 0

    return [
        AdminConsoleFunnelStage(name="Signups", count=int(signups)),
        AdminConsoleFunnelStage(name="Onboarded", count=int(onboarded)),
        AdminConsoleFunnelStage(name="First lesson", count=int(first_lesson)),
        AdminConsoleFunnelStage(name="Paid", count=int(paid)),
        AdminConsoleFunnelStage(name="Capstone", count=int(capstone)),
        AdminConsoleFunnelStage(name="Promoted", count=int(promoted)),
        AdminConsoleFunnelStage(name="Hired", count=hired),
    ]


async def _compute_live_pulse(
    db: AsyncSession,
    now: datetime,
    window: str = "24h",
) -> list[AdminConsolePulseCard]:
    """LD-2: Compute the 6 pulse-strip cards from live data with 14-day
    sparklines. Replaces the seeded admin_console_pulse_metrics read.

    `window` controls the lookback for the activity-style cards
    (active learners, sessions, capstones, promotions). It does NOT
    affect MRR (always 30d, since "monthly" is in the name) or the
    at-risk count (a snapshot, not a window). The 14-day sparkline is
    fixed regardless of window — it's a 2-week trend, the value above
    is "what's happening in the chosen window right now".
    """
    from app.models.enrollment import Enrollment
    from app.models.exercise import Exercise
    from app.models.exercise_submission import ExerciseSubmission
    from app.models.learning_session import LearningSession
    from app.models.payment import Payment
    from app.models.student_risk_signals import StudentRiskSignals

    # Window mapping for the activity-style cards. The "label" is what
    # gets shown in the card eyebrow ("Active learners (24h)" etc.) and
    # in the delta_text suffix ("vs yesterday" / "vs last week" / "vs
    # last 30d").
    window_specs = {
        "24h": {
            "delta": timedelta(hours=24),
            "label_suffix": "(24h)",
            "delta_text": "vs yesterday",
            "session_label": "Sessions today",
            "session_delta_text": "vs yesterday",
        },
        "7d": {
            "delta": timedelta(days=7),
            "label_suffix": "(7d)",
            "delta_text": "vs prior week",
            "session_label": "Sessions this week",
            "session_delta_text": "vs prior week",
        },
        "30d": {
            "delta": timedelta(days=30),
            "label_suffix": "(30d)",
            "delta_text": "vs prior 30d",
            "session_label": "Sessions this month",
            "session_delta_text": "vs prior 30d",
        },
    }
    spec = window_specs.get(window, window_specs["24h"])
    win_delta: timedelta = spec["delta"]  # type: ignore[assignment]

    cutoff = now - win_delta
    prior_cutoff = now - 2 * win_delta
    month_ago = now - timedelta(days=30)
    two_months_ago = now - timedelta(days=60)

    # ── 1. Active learners (window) ──
    active_24h = (
        await db.execute(
            select(func.count(func.distinct(AgentAction.student_id))).where(
                AgentAction.created_at >= cutoff
            )
        )
    ).scalar() or 0
    active_prior = (
        await db.execute(
            select(func.count(func.distinct(AgentAction.student_id))).where(
                AgentAction.created_at >= prior_cutoff,
                AgentAction.created_at < cutoff,
            )
        )
    ).scalar() or 0
    active_spark = await _daily_buckets(
        db, AgentAction.created_at, AgentAction.id.is_not(None), now
    )

    # ── 2. Sessions in chosen window ──
    sessions_today = (
        await db.execute(
            select(func.count(LearningSession.id)).where(
                LearningSession.created_at >= cutoff
            )
        )
    ).scalar() or 0
    sessions_yday = (
        await db.execute(
            select(func.count(LearningSession.id)).where(
                LearningSession.created_at >= prior_cutoff,
                LearningSession.created_at < cutoff,
            )
        )
    ).scalar() or 0
    sessions_spark = await _daily_buckets(
        db, LearningSession.created_at, LearningSession.id.is_not(None), now
    )

    # ── 3. Capstones submitted (window) ──
    capstones_wk = (
        await db.execute(
            select(func.count(ExerciseSubmission.id))
            .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
            .where(
                Exercise.is_capstone.is_(True),
                ExerciseSubmission.created_at >= cutoff,
            )
        )
    ).scalar() or 0
    capstones_prior = (
        await db.execute(
            select(func.count(ExerciseSubmission.id))
            .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
            .where(
                Exercise.is_capstone.is_(True),
                ExerciseSubmission.created_at >= prior_cutoff,
                ExerciseSubmission.created_at < cutoff,
            )
        )
    ).scalar() or 0
    # Spark: capstone submissions per day (joined query — simpler to fetch ids).
    cap_rows = (
        await db.execute(
            select(ExerciseSubmission.created_at)
            .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
            .where(
                Exercise.is_capstone.is_(True),
                ExerciseSubmission.created_at >= now - timedelta(days=14),
            )
        )
    ).all()
    capstones_spark = [0.0] * 14
    spark_start = (now - timedelta(days=13)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    for (ts,) in cap_rows:
        idx = (ts.date() - spark_start.date()).days
        if 0 <= idx < 14:
            capstones_spark[idx] += 1

    # ── 4. Promotions earned (window) ──
    promotions_wk = (
        await db.execute(
            select(func.count(User.id)).where(
                User.promoted_at >= cutoff,  # type: ignore[arg-type]
            )
        )
    ).scalar() or 0
    promotions_prior = (
        await db.execute(
            select(func.count(User.id)).where(
                User.promoted_at >= prior_cutoff,  # type: ignore[arg-type]
                User.promoted_at < cutoff,  # type: ignore[arg-type]
            )
        )
    ).scalar() or 0
    promotions_spark = await _daily_buckets(
        db, User.promoted_at, User.promoted_at.is_not(None), now
    )

    # ── 5. MRR (last 30 days, in dollars) ──
    mrr_cents = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
                Payment.created_at >= month_ago,
                Payment.status == "succeeded",
            )
        )
    ).scalar() or 0
    mrr_prior_cents = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
                Payment.created_at >= two_months_ago,
                Payment.created_at < month_ago,
                Payment.status == "succeeded",
            )
        )
    ).scalar() or 0
    mrr_dollars = float(mrr_cents) / 100.0
    mrr_prior_dollars = float(mrr_prior_cents) / 100.0
    # Spark: daily revenue for last 14 days.
    pay_rows = (
        await db.execute(
            select(Payment.created_at, Payment.amount_cents).where(
                Payment.created_at >= now - timedelta(days=14),
                Payment.status == "succeeded",
            )
        )
    ).all()
    mrr_spark = [0.0] * 14
    for ts, cents in pay_rows:
        idx = (ts.date() - spark_start.date()).days
        if 0 <= idx < 14:
            mrr_spark[idx] += float(cents) / 100.0

    # ── 6. At-risk learners (right now) ──
    # Counts every student that F1 has flagged with a slip pattern
    # (slip_type != 'none'). Conservative: any flagged student is
    # worth the operator's attention.
    at_risk_now = (
        await db.execute(
            select(func.count(StudentRiskSignals.id)).where(
                StudentRiskSignals.slip_type != "none",
                StudentRiskSignals.risk_score > 0,
            )
        )
    ).scalar() or 0
    # Prior week: we don't keep historical risk snapshots, so use "at-risk
    # last week" as a proxy via student_risk_signals.computed_at if available.
    # For now, just no-delta when there's no prior signal.
    at_risk_prior = at_risk_now  # no historical baseline yet → delta = 0
    at_risk_spark = [float(at_risk_now)] * 14  # flat line until we snapshot daily

    # Pretty value formatting matching the existing UI's ConsoleStudent shape.
    def mrr_display(d: float) -> tuple[str, str]:
        if d >= 1000:
            return f"${d / 1000:.1f}", "k"
        return f"${int(d)}", ""

    mrr_val, mrr_unit = mrr_display(mrr_dollars)

    label_suffix = spec["label_suffix"]
    delta_text_default = spec["delta_text"]
    session_label = spec["session_label"]
    session_delta_text = spec["session_delta_text"]
    # Capstones / promotions use a "wk"-style unit; on 24h we want
    # "today" instead of "wk", on 30d we want "mo".
    unit_suffix = {"24h": " today", "7d": " wk", "30d": " mo"}.get(window, " wk")

    return [
        AdminConsolePulseCard(
            metric_key="active_24h",
            label=f"Active learners {label_suffix}",
            value=_fmt_int(active_24h),
            unit="",
            delta=_delta_pct(active_24h, active_prior),
            delta_text=delta_text_default,
            color="#5fa37f",
            invert_delta=False,
            spark=active_spark,
        ),
        AdminConsolePulseCard(
            metric_key="sessions_today",
            label=session_label,
            value=_fmt_int(sessions_today),
            unit="",
            delta=_delta_pct(sessions_today, sessions_yday),
            delta_text=session_delta_text,
            color="#5fa37f",
            invert_delta=False,
            spark=sessions_spark,
        ),
        AdminConsolePulseCard(
            metric_key="capstones_wk",
            label="Capstones submitted",
            value=_fmt_int(capstones_wk),
            unit=unit_suffix,
            delta=_delta_pct(capstones_wk, capstones_prior),
            delta_text=delta_text_default,
            color="#5fa37f",
            invert_delta=False,
            spark=capstones_spark,
        ),
        AdminConsolePulseCard(
            metric_key="promotions_wk",
            label="Promotions earned",
            value=_fmt_int(promotions_wk),
            unit=unit_suffix,
            delta=_delta_pct(promotions_wk, promotions_prior),
            delta_text=delta_text_default,
            color="#d6a54d",
            invert_delta=False,
            spark=promotions_spark,
        ),
        AdminConsolePulseCard(
            metric_key="mrr",
            label="MRR",
            value=mrr_val,
            unit=mrr_unit,
            delta=_delta_pct(mrr_dollars, mrr_prior_dollars),
            delta_text="this month",
            color="#5fa37f",
            invert_delta=False,
            spark=mrr_spark,
        ),
        AdminConsolePulseCard(
            metric_key="at_risk",
            label="At-risk learners",
            value=_fmt_int(at_risk_now),
            unit="",
            delta=_delta_pct(at_risk_now, at_risk_prior),
            delta_text="right now",
            color="#b8443a",
            invert_delta=True,
            spark=at_risk_spark,
        ),
    ]


@router.get("/console/v1", response_model=AdminConsoleResponse)
async def get_admin_console(
    window: str = Query(
        "24h",
        pattern="^(24h|7d|30d)$",
        description=(
            "Pulse-strip window: 24h (default), 7d, or 30d. Controls "
            "the lookback for the activity-style cards (active learners, "
            "sessions, capstones, promotions). MRR and at-risk count "
            "are unaffected — they're a 30-day window and a snapshot, "
            "respectively."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> AdminConsoleResponse:
    """All data the v1 Admin Console needs in one round-trip.

    LD-1..LD-5 (live data migration) and LD-7 (cleanup) — every block
    on /admin now reads from live tables instead of the seeded
    admin_console_* demo:

      LD-1  students roster + action band → users + student_risk_signals
      LD-2  pulse strip                   → agent_actions + learning_sessions
                                            + exercise_submissions + users
                                            + payments + student_risk_signals
      LD-3  learner funnel                → users + goal_contracts +
                                            student_progress + course_entitlements
                                            + exercise_submissions
      LD-4  feature pulse tiles           → srs_cards + agent_actions +
                                            ai_reviews + notebook_entries +
                                            exercise_submissions + jd_match_scores
                                            + interview_sessions
      LD-5  right rail (calls + events    → outreach_log + cohort_events +
            + revenue)                      payments + refunds

    The 8 admin_console_* tables and their seed script remain in the
    schema for one more deploy as a safety net; they are dropped by
    a follow-up alembic migration once this code soaks in production.

    One bulk endpoint keeps the page fast and avoids 8 separate
    auth round-trips.
    """
    from app.models.student_risk_signals import StudentRiskSignals

    # Students — LIVE: users LEFT JOIN student_risk_signals.
    # Includes ALL students (paid or not, at-risk or not). The risk
    # score is 0 for students with no signal row (treated as healthy
    # until F1 nightly task scores them). Sorted by risk DESC so the
    # action band's "top 3" picks the most urgent.
    user_rows = (
        await db.execute(
            select(User)
            .where(User.role == "student", User.is_deleted.is_(False))
            .order_by(User.created_at.desc())
        )
    ).scalars().all()
    risk_rows = (
        await db.execute(select(StudentRiskSignals))
    ).scalars().all()
    risk_by_uid = {r.user_id: r for r in risk_rows}

    now = datetime.now(UTC)

    def _last_seen_days(u: User) -> int:
        if u.last_login_at is None:
            # Never logged in — show as "days since signup" for the UI to
            # render "Stale 71d" rather than "Today".
            return max(0, (now - u.created_at).days)
        return max(0, (now - u.last_login_at).days)

    def _joined_label(u: User) -> str:
        return u.created_at.strftime("%b %d")

    students: list[AdminConsoleStudent] = []
    for u in user_rows:
        risk = risk_by_uid.get(u.id)
        students.append(
            AdminConsoleStudent(
                id=str(u.id),
                name=u.full_name or u.email,
                email=u.email,
                # Track / stage / progress aren't on the User row yet —
                # placeholder until per-student rollups land in LD-4.
                track="—",
                stage="—",
                progress=0,
                streak=risk.max_streak_ever if risk else 0,
                last_seen=risk.days_since_last_session
                if (risk and risk.days_since_last_session is not None)
                else _last_seen_days(u),
                risk=risk.risk_score if risk else 0,
                paid=risk.paid if risk else False,
                joined=_joined_label(u),
                city=None,
                sessions14=0,
                flashcards=0,
                agent_q=0,
                reviews=0,
                notes=0,
                labs=0,
                capstones=0,
                purchases=0,
                risk_reason=risk.risk_reason if risk else None,
                whatsapp_number=u.whatsapp_number,
            )
        )
    students.sort(key=lambda s: s.risk, reverse=True)

    # Pulse — LD-2: 6 cards computed from LIVE data with 14-day sparks.
    pulse = await _compute_live_pulse(db, now, window)

    # Funnel — LD-3: live counts over the entire student population
    # (not a 30-day cohort — the marketing-funnel narrative the CEO
    # cares about is "where are all my students right now along the
    # journey"). Stages mirror the existing 7-stage demo so the chart
    # renders identically.
    funnel = await _compute_live_funnel(db)

    # Features — LD-4: 8 tiles computed from live tables.
    features = await _compute_live_features(db, now)

    # Calls (today) — LD-5: from outreach_log where kind='admin_manual'
    # and the outreach was logged today UTC. The richer
    # "scheduled_call" concept (with explicit scheduled_at column)
    # is a future migration; for now we reuse today's manual sends
    # as a proxy for "calls the operator has on their plate today".
    calls = await _compute_live_calls(db, now)

    # Events — LD-5: from cohort_events (real, masked-handle stream
    # populated by various agents on lifecycle moments).
    events = await _compute_live_events(db, now)

    # Revenue — LD-5: from payments + refunds tables.
    revenue = await _compute_live_revenue(db, now, pulse)

    return AdminConsoleResponse(
        students=students,
        pulse=pulse,
        funnel=funnel,
        features=features,
        calls=calls,
        events=events,
        revenue=revenue,
        synced_at=datetime.now(UTC),
    )


# ── F8 — In-app messaging (admin side) ──────────────────────────────


class _AdminSendMessage(PydanticModel):
    thread_id: str | None = None  # missing → start a new thread
    body: str


class _AdminMessageRead(PydanticModel):
    id: str
    thread_id: str
    student_id: str
    sender_role: str
    sender_id: str | None
    body: str
    read_at: str | None
    created_at: str


def _admin_msg_to_read(m: Any) -> _AdminMessageRead:
    return _AdminMessageRead(
        id=str(m.id),
        thread_id=str(m.thread_id),
        student_id=str(m.student_id),
        sender_role=m.sender_role,
        sender_id=str(m.sender_id) if m.sender_id else None,
        body=m.body,
        read_at=m.read_at.isoformat() if m.read_at else None,
        created_at=m.created_at.isoformat(),
    )


@router.post(
    "/students/{student_id}/messages",
    response_model=_AdminMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def admin_send_message(
    student_id: uuid.UUID,
    payload: _AdminSendMessage,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> _AdminMessageRead:
    """Admin sends an in-app DM. If thread_id is omitted, mints a new
    thread; otherwise appends to the existing one. Mirrors to
    outreach_log via F3 for the audit trail."""
    from app.services import student_message_service

    await _require_student(db, student_id)
    thread_uuid: uuid.UUID | None = None
    if payload.thread_id:
        thread_uuid = uuid.UUID(payload.thread_id)
    msg = await student_message_service.create_message(
        db,
        thread_id=thread_uuid,
        student_id=student_id,
        sender_role="admin",
        sender_id=admin.id,
        body=payload.body,
    )
    return _admin_msg_to_read(msg)


@router.get(
    "/students/{student_id}/messages",
    response_model=list[_AdminMessageRead],
)
async def admin_list_messages(
    student_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[_AdminMessageRead]:
    """All messages for one student (across threads), newest first.
    Powers the per-student admin DM view."""
    from app.services import student_message_service

    await _require_student(db, student_id)
    msgs = await student_message_service.list_for_student(
        db, student_id=student_id
    )
    return [_admin_msg_to_read(m) for m in msgs]


# ── D16/CP3.2 — Manual outreach logging (WhatsApp / phone) ───────────


_ALLOWED_MANUAL_OUTREACH_CHANNELS = {"whatsapp", "phone"}


class _AdminLogOutreach(PydanticModel):
    # whatsapp | phone — defaults to whatsapp because that's the primary
    # use case from the founder reframe; phone is the secondary value
    # for voice-call outreach the admin wants to record after the fact.
    channel: str = "whatsapp"
    # Free-form note about what was discussed. Stored as body_preview
    # on outreach_log (truncated to 200 chars in the service layer).
    body_preview: str = ""


class _AdminOutreachLogRead(PydanticModel):
    id: str
    user_id: str
    channel: str
    triggered_by: str
    triggered_by_user_id: str | None
    body_preview: str | None
    sent_at: str
    status: str


@router.post(
    "/students/{student_id}/outreach",
    response_model=_AdminOutreachLogRead,
    status_code=status.HTTP_201_CREATED,
)
async def admin_log_manual_outreach(
    student_id: uuid.UUID,
    payload: _AdminLogOutreach,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> _AdminOutreachLogRead:
    """D16/CP3.2 — record a manual admin outreach (WhatsApp or phone).

    Per locked decision D-B: outreach_log is canonical for admin
    contact records. The admin clicks the wa.me/{number} deep link
    (their own WhatsApp opens) or makes a phone call, then taps "Log
    this contact" to capture what happened. We write a single
    outreach_log row with channel='whatsapp' (or 'phone'),
    triggered_by='admin_manual', triggered_by_user_id=<admin>, and
    status='sent' — the network step happened outside the platform,
    so we go straight to 'sent' (no 'pending' → 'sent' flip).
    """
    from app.services import outreach_service

    channel = payload.channel.lower().strip()
    if channel not in _ALLOWED_MANUAL_OUTREACH_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"channel must be one of {sorted(_ALLOWED_MANUAL_OUTREACH_CHANNELS)} "
                f"(got '{payload.channel}')"
            ),
        )

    student = await _require_student(db, student_id)

    entry = await outreach_service.record(
        db,
        user_id=student.id,
        channel=channel,
        template_key=None,
        slip_type=None,
        triggered_by="admin_manual",
        triggered_by_user_id=admin.id,
        body_preview=payload.body_preview or None,
        status="sent",
    )
    # outreach_service.record() already commits + refreshes.
    await AdminAuditService.log(
        db=db,
        admin=admin,
        action_type="outreach.send",
        resource_type="user",
        resource_id=str(student.id),
        metadata={
            "channel": channel,
            "student_id": str(student.id),
            "text_preview": (payload.body_preview or "")[:200],
        },
        request=request,
    )
    await db.commit()
    return _AdminOutreachLogRead(
        id=str(entry.id),
        user_id=str(entry.user_id),
        channel=entry.channel,
        triggered_by=entry.triggered_by,
        triggered_by_user_id=str(entry.triggered_by_user_id)
        if entry.triggered_by_user_id
        else None,
        body_preview=entry.body_preview,
        sent_at=entry.sent_at.isoformat(),
        status=entry.status,
    )


# ── Admin health strip (6 aggregate metrics) ─────────────────────────────────


@router.get("/health-strip", response_model=HealthStripResponse)
async def get_health_strip(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> HealthStripResponse:
    """7 aggregated platform-health metrics for the admin dashboard strip."""
    from app.models.exercise_submission import ExerciseSubmission
    from app.models.feedback import Feedback
    from app.models.lesson import Lesson
    from app.models.payment import Payment

    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)
    thirty_days_ago = now - timedelta(days=30)

    # Assumption: User has no `last_active_at`; using `last_login_at` as the
    # most recent activity proxy. Null last_login_at counts as inactive.
    inactive_user_q = select(User.id).where(
        User.role == "student",
        User.is_deleted.is_(False),
        (User.last_login_at.is_(None)) | (User.last_login_at < seven_days_ago),
    )

    # 1. revenue_at_risk — paid users (have a succeeded payment) inactive 7d+.
    paid_inactive_rows = (
        await db.execute(
            select(Payment.user_id, func.sum(Payment.amount_cents))
            .where(Payment.status == "succeeded", Payment.user_id.in_(inactive_user_q))
            .group_by(Payment.user_id)
        )
    ).all()
    revenue_cents = sum(int(r[1] or 0) for r in paid_inactive_rows)
    paid_silent_count = len(paid_inactive_rows)
    revenue_dollars = revenue_cents // 100
    revenue_metric = HealthMetric(
        key="revenue_at_risk",
        label="Revenue at risk",
        value=f"${revenue_dollars:,}",
        sub=f"{paid_silent_count} paid students silent 7d+",
        tone="danger" if revenue_cents > 0 else "ok",
        delta=None,
        delta_text=None,
    )

    # 2. review_queue — submissions awaiting review.
    # Assumption: ExerciseSubmission has `status` and `score`. Pending =
    # status in ('pending','submitted') AND score IS NULL, last 14d.
    pending_rows = (
        await db.execute(
            select(ExerciseSubmission.created_at)
            .where(
                ExerciseSubmission.score.is_(None),
                ExerciseSubmission.status.in_(("pending", "submitted")),
                ExerciseSubmission.created_at >= fourteen_days_ago,
            )
            .order_by(ExerciseSubmission.created_at.asc())
        )
    ).all()
    pending_count = len(pending_rows)
    oldest_hours = 0
    if pending_rows:
        oldest = pending_rows[0][0]
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        oldest_hours = int((now - oldest).total_seconds() // 3600)
    if oldest_hours > 96:
        review_tone = "danger"
    elif oldest_hours > 48:
        review_tone = "warn"
    else:
        review_tone = "ok" if pending_count == 0 else "neutral"
    review_metric = HealthMetric(
        key="review_queue",
        label="Review queue",
        value=str(pending_count),
        sub=f"Oldest {oldest_hours}h waiting",
        tone=review_tone,
        delta=None,
        delta_text=None,
    )

    # 3. top_confusion — distinct topics from socratic_tutor actions last 7d.
    confusion_actions = (
        await db.execute(
            select(AgentAction.input_data).where(
                AgentAction.agent_name == "socratic_tutor",
                AgentAction.created_at >= seven_days_ago,
            )
        )
    ).all()
    topic_counts: dict[str, int] = {}
    for (inp,) in confusion_actions:
        if not isinstance(inp, dict):
            continue
        topic = inp.get("topic") or inp.get("concept") or inp.get("lesson_id")
        if topic:
            topic_counts[str(topic)] = topic_counts.get(str(topic), 0) + 1
    distinct_topics = len(topic_counts)
    top_topic = max(topic_counts.items(), key=lambda kv: kv[1])[0] if topic_counts else "—"
    if distinct_topics > 10:
        conf_tone = "danger"
    elif distinct_topics > 5:
        conf_tone = "warn"
    else:
        conf_tone = "ok" if distinct_topics == 0 else "neutral"
    confusion_metric = HealthMetric(
        key="top_confusion",
        label="Confusion topics",
        value=str(distinct_topics),
        sub=f"Top: {top_topic}",
        tone=conf_tone,
        delta=None,
        delta_text=None,
    )

    # 4. worst_lessons — lessons whose confusion_rate (>30%) over last 30d.
    actions_30d = (
        await db.execute(
            select(AgentAction.agent_name, AgentAction.input_data).where(
                AgentAction.created_at >= thirty_days_ago
            )
        )
    ).all()
    per_lesson: dict[str, dict[str, int]] = {}
    for agent_name, inp in actions_30d:
        if not isinstance(inp, dict):
            continue
        lid = inp.get("lesson_id")
        if not lid:
            continue
        bucket = per_lesson.setdefault(str(lid), {"total": 0, "confusion": 0})
        bucket["total"] += 1
        if agent_name == "socratic_tutor":
            bucket["confusion"] += 1
    worst_lessons: list[tuple[str, float]] = []
    for lid, vals in per_lesson.items():
        if vals["total"] >= 5 and (vals["confusion"] / vals["total"]) > 0.30:
            worst_lessons.append((lid, vals["confusion"] / vals["total"]))
    worst_lessons.sort(key=lambda kv: kv[1], reverse=True)
    worst_title = "—"
    if worst_lessons:
        try:
            worst_uuid = uuid.UUID(worst_lessons[0][0])
            title_row = (
                await db.execute(select(Lesson.title).where(Lesson.id == worst_uuid))
            ).first()
            if title_row:
                worst_title = title_row[0]
        except (ValueError, TypeError):
            pass
    worst_metric = HealthMetric(
        key="worst_lessons",
        label="Worst lessons",
        value=str(len(worst_lessons)),
        sub=f"Worst: {worst_title}",
        tone="warn" if worst_lessons else "ok",
        delta=None,
        delta_text=None,
    )

    # 5. stale_students — students inactive 7d+.
    stale_count = (
        await db.execute(select(func.count()).select_from(inactive_user_q.subquery()))
    ).scalar_one()
    stale_metric = HealthMetric(
        key="stale_students",
        label="Stale students",
        value=str(stale_count),
        sub=f"{stale_count} no activity 7d+",
        tone="warn" if (stale_count or 0) > 5 else "ok",
        delta=None,
        delta_text=None,
    )

    # 6. cohort_delta — signups this week vs last week.
    this_week = (
        await db.execute(
            select(func.count(User.id)).where(
                User.role == "student",
                User.is_deleted.is_(False),
                User.created_at >= seven_days_ago,
            )
        )
    ).scalar_one() or 0
    last_week = (
        await db.execute(
            select(func.count(User.id)).where(
                User.role == "student",
                User.is_deleted.is_(False),
                User.created_at >= fourteen_days_ago,
                User.created_at < seven_days_ago,
            )
        )
    ).scalar_one() or 0
    if last_week > 0:
        pct = ((this_week - last_week) / last_week) * 100.0
    else:
        pct = 100.0 if this_week > 0 else 0.0
    if pct < -10:
        cohort_tone = "danger"
    elif pct < 0:
        cohort_tone = "warn"
    else:
        cohort_tone = "ok"
    sign = "+" if pct >= 0 else ""

    open_feedback_total: int = (
        await db.execute(
            select(func.count(Feedback.id)).where(Feedback.resolved.is_(False))
        )
    ).scalar() or 0
    sentiment_rows = (
        await db.execute(
            select(Feedback.sentiment, func.count(Feedback.id))
            .where(Feedback.resolved.is_(False))
            .group_by(Feedback.sentiment)
        )
    ).all()
    sentiment_counts = {(s or "neutral"): c for s, c in sentiment_rows}
    neg_count = sentiment_counts.get("negative", 0)
    if neg_count >= 5:
        feedback_tone = "danger"
    elif neg_count >= 1 or open_feedback_total >= 10:
        feedback_tone = "warn"
    elif open_feedback_total == 0:
        feedback_tone = "ok"
    else:
        feedback_tone = "neutral"
    feedback_sub_parts = []
    if neg_count:
        feedback_sub_parts.append(f"{neg_count} negative")
    if sentiment_counts.get("neutral", 0):
        feedback_sub_parts.append(f"{sentiment_counts['neutral']} neutral")
    if sentiment_counts.get("positive", 0):
        feedback_sub_parts.append(f"{sentiment_counts['positive']} positive")
    feedback_sub = " · ".join(feedback_sub_parts) if feedback_sub_parts else "No open feedback"
    feedback_metric = HealthMetric(
        key="open_feedback",
        label="Open feedback",
        value=str(open_feedback_total),
        sub=feedback_sub,
        tone=feedback_tone,
        delta=None,
        delta_text=None,
    )

    cohort_metric = HealthMetric(
        key="cohort_delta",
        label="Cohort delta",
        value=f"{sign}{pct:.0f}%",
        sub=f"{this_week} new vs {last_week}",
        tone=cohort_tone,
        delta=round(pct, 2),
        delta_text=f"{sign}{pct:.0f}% WoW",
    )

    log.info(
        "admin.health_strip_viewed",
        revenue_at_risk_cents=revenue_cents,
        review_pending=pending_count,
        stale_students=stale_count,
        cohort_delta_pct=pct,
    )

    return HealthStripResponse(
        metrics=[
            revenue_metric,
            review_metric,
            confusion_metric,
            worst_metric,
            stale_metric,
            feedback_metric,
            cohort_metric,
        ],
        generated_at=now,
    )


# ── Health-strip drill-down schemas ──────────────────────────────────────────


class RevenueAtRiskItem(PydanticModel):
    user_id: str
    name: str
    email: str | None
    amount_cents: int
    amount_display: str
    last_active_days: int | None
    last_active_text: str


class RevenueAtRiskResponse(PydanticModel):
    items: list[RevenueAtRiskItem]
    total_cents: int
    total_display: str


class ReviewQueueItem(PydanticModel):
    submission_id: str
    user_id: str
    user_name: str
    exercise_id: str
    exercise_title: str | None
    created_at: datetime
    age_hours: int
    age_text: str


class ReviewQueueResponse(PydanticModel):
    items: list[ReviewQueueItem]
    total: int


class StaleStudentItem(PydanticModel):
    user_id: str
    name: str
    email: str | None
    last_active_days: int | None
    last_active_text: str
    is_paid: bool


class StaleStudentsResponse(PydanticModel):
    items: list[StaleStudentItem]
    total: int


class CohortDeltaResponse(PydanticModel):
    this_week_signups: int
    last_week_signups: int
    delta_pct: float
    delta_text: str
    this_week_paid: int
    last_week_paid: int
    this_week_completions: int
    last_week_completions: int
    daily: list[dict]


def _days_since(ts: datetime | None, now: datetime) -> int | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return int((now - ts).total_seconds() // 86400)


def _last_active_text(days: int | None) -> str:
    if days is None:
        return "never"
    return f"{days}d ago"


def _format_dollars(cents: int) -> str:
    return f"${cents / 100:.2f}"


@router.get("/health-strip/revenue-at-risk", response_model=RevenueAtRiskResponse)
async def get_health_strip_revenue_at_risk(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> RevenueAtRiskResponse:
    """Paid students inactive 7d+ with their total spend, sorted by amount desc."""
    from app.models.payment import Payment

    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)

    rows = (
        await db.execute(
            select(
                User.id,
                User.full_name,
                User.email,
                User.last_login_at,
                func.sum(Payment.amount_cents).label("amount"),
            )
            .join(Payment, Payment.user_id == User.id)
            .where(
                Payment.status == "succeeded",
                User.role == "student",
                User.is_deleted.is_(False),
                (User.last_login_at.is_(None)) | (User.last_login_at < seven_days_ago),
            )
            .group_by(User.id, User.full_name, User.email, User.last_login_at)
            .order_by(func.sum(Payment.amount_cents).desc())
        )
    ).all()

    items: list[RevenueAtRiskItem] = []
    total_cents = 0
    for uid, name, email, last_login, amount in rows:
        amt = int(amount or 0)
        total_cents += amt
        days = _days_since(last_login, now)
        items.append(
            RevenueAtRiskItem(
                user_id=str(uid),
                name=name,
                email=email,
                amount_cents=amt,
                amount_display=_format_dollars(amt),
                last_active_days=days,
                last_active_text=_last_active_text(days),
            )
        )

    log.info("admin.health_strip_revenue_at_risk_viewed", count=len(items), total_cents=total_cents)
    return RevenueAtRiskResponse(
        items=items,
        total_cents=total_cents,
        total_display=_format_dollars(total_cents),
    )


@router.get("/health-strip/review-queue", response_model=ReviewQueueResponse)
async def get_health_strip_review_queue(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> ReviewQueueResponse:
    """Pending exercise submissions awaiting review, oldest first."""
    from app.models.exercise import Exercise
    from app.models.exercise_submission import ExerciseSubmission

    now = datetime.now(UTC)

    rows = (
        await db.execute(
            select(
                ExerciseSubmission.id,
                ExerciseSubmission.student_id,
                User.full_name,
                ExerciseSubmission.exercise_id,
                Exercise.title,
                ExerciseSubmission.created_at,
            )
            .join(User, User.id == ExerciseSubmission.student_id)
            .outerjoin(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
            .where(
                ExerciseSubmission.score.is_(None),
                ExerciseSubmission.status.in_(("pending", "submitted")),
            )
            .order_by(ExerciseSubmission.created_at.asc())
            .limit(50)
        )
    ).all()

    items: list[ReviewQueueItem] = []
    for sub_id, uid, uname, ex_id, ex_title, created_at in rows:
        ts = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
        age_hours = int((now - ts).total_seconds() // 3600)
        items.append(
            ReviewQueueItem(
                submission_id=str(sub_id),
                user_id=str(uid),
                user_name=uname,
                exercise_id=str(ex_id),
                exercise_title=ex_title,
                created_at=ts,
                age_hours=age_hours,
                age_text=f"{age_hours}h ago",
            )
        )

    log.info("admin.health_strip_review_queue_viewed", count=len(items))
    return ReviewQueueResponse(items=items, total=len(items))


@router.get("/health-strip/stale-students", response_model=StaleStudentsResponse)
async def get_health_strip_stale_students(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> StaleStudentsResponse:
    """Students inactive 7d+ (or never logged in), oldest activity first."""
    from app.models.payment import Payment

    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)

    paid_user_ids = {
        r[0]
        for r in (
            await db.execute(
                select(Payment.user_id).where(Payment.status == "succeeded").distinct()
            )
        ).all()
    }

    rows = (
        await db.execute(
            select(User.id, User.full_name, User.email, User.last_login_at)
            .where(
                User.role == "student",
                User.is_deleted.is_(False),
                (User.last_login_at.is_(None)) | (User.last_login_at < seven_days_ago),
            )
            .order_by(User.last_login_at.asc().nulls_last())
            .limit(100)
        )
    ).all()

    items: list[StaleStudentItem] = []
    for uid, name, email, last_login in rows:
        days = _days_since(last_login, now)
        items.append(
            StaleStudentItem(
                user_id=str(uid),
                name=name,
                email=email,
                last_active_days=days,
                last_active_text=_last_active_text(days),
                is_paid=uid in paid_user_ids,
            )
        )

    log.info("admin.health_strip_stale_students_viewed", count=len(items))
    return StaleStudentsResponse(items=items, total=len(items))


@router.get("/health-strip/cohort-delta", response_model=CohortDeltaResponse)
async def get_health_strip_cohort_delta(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> CohortDeltaResponse:
    """Week-over-week cohort breakdown with 14-day sparkline data."""
    from app.models.exercise_submission import ExerciseSubmission
    from app.models.payment import Payment

    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)

    this_week_signups = (
        await db.execute(
            select(func.count(User.id)).where(
                User.role == "student",
                User.is_deleted.is_(False),
                User.created_at >= seven_days_ago,
            )
        )
    ).scalar_one() or 0

    last_week_signups = (
        await db.execute(
            select(func.count(User.id)).where(
                User.role == "student",
                User.is_deleted.is_(False),
                User.created_at >= fourteen_days_ago,
                User.created_at < seven_days_ago,
            )
        )
    ).scalar_one() or 0

    this_week_paid = (
        await db.execute(
            select(func.count(func.distinct(Payment.user_id))).where(
                Payment.status == "succeeded",
                Payment.created_at >= seven_days_ago,
            )
        )
    ).scalar_one() or 0

    last_week_paid = (
        await db.execute(
            select(func.count(func.distinct(Payment.user_id))).where(
                Payment.status == "succeeded",
                Payment.created_at >= fourteen_days_ago,
                Payment.created_at < seven_days_ago,
            )
        )
    ).scalar_one() or 0

    this_week_completions = (
        await db.execute(
            select(func.count(ExerciseSubmission.id)).where(
                ExerciseSubmission.status == "completed",
                ExerciseSubmission.created_at >= seven_days_ago,
            )
        )
    ).scalar_one() or 0

    last_week_completions = (
        await db.execute(
            select(func.count(ExerciseSubmission.id)).where(
                ExerciseSubmission.status == "completed",
                ExerciseSubmission.created_at >= fourteen_days_ago,
                ExerciseSubmission.created_at < seven_days_ago,
            )
        )
    ).scalar_one() or 0

    if last_week_signups > 0:
        pct = ((this_week_signups - last_week_signups) / last_week_signups) * 100.0
    else:
        pct = 100.0 if this_week_signups > 0 else 0.0
    sign = "+" if pct >= 0 else ""
    delta_text = f"{sign}{pct:.0f}%"

    # Daily breakdown — last 14 days.
    signup_rows = (
        await db.execute(
            select(func.date(User.created_at), func.count(User.id))
            .where(
                User.role == "student",
                User.is_deleted.is_(False),
                User.created_at >= fourteen_days_ago,
            )
            .group_by(func.date(User.created_at))
        )
    ).all()
    signups_by_day = {str(d): int(c or 0) for d, c in signup_rows}

    paid_rows = (
        await db.execute(
            select(func.date(Payment.created_at), func.count(func.distinct(Payment.user_id)))
            .where(
                Payment.status == "succeeded",
                Payment.created_at >= fourteen_days_ago,
            )
            .group_by(func.date(Payment.created_at))
        )
    ).all()
    paid_by_day = {str(d): int(c or 0) for d, c in paid_rows}

    daily: list[dict] = []
    today = now.date()
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        daily.append(
            {
                "date": ds,
                "signups": signups_by_day.get(ds, 0),
                "paid": paid_by_day.get(ds, 0),
            }
        )

    log.info(
        "admin.health_strip_cohort_delta_viewed",
        this_week_signups=this_week_signups,
        last_week_signups=last_week_signups,
        delta_pct=pct,
    )

    return CohortDeltaResponse(
        this_week_signups=this_week_signups,
        last_week_signups=last_week_signups,
        delta_pct=round(pct, 2),
        delta_text=delta_text,
        this_week_paid=this_week_paid,
        last_week_paid=last_week_paid,
        this_week_completions=this_week_completions,
        last_week_completions=last_week_completions,
        daily=daily,
    )


class CourseHealth(PydanticModel):
    course_id: str
    title: str
    slug: str
    difficulty: str
    price_cents: int
    is_published: bool
    lessons_count: int
    enrollments: int
    completion_rate: float
    avg_confusion_rate: float
    open_feedback_count: int
    negative_feedback_count: int
    needs_attention: bool
    updated_at: datetime


class CoursesHealthResponse(PydanticModel):
    items: list[CourseHealth]
    generated_at: datetime


@router.get("/courses-health", response_model=CoursesHealthResponse)
async def get_courses_health(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> CoursesHealthResponse:
    """Per-course health metrics for the admin Courses page."""
    from app.models.course import Course
    from app.models.enrollment import Enrollment
    from app.models.feedback import Feedback
    from app.models.lesson import Lesson

    now = datetime.now(UTC)

    course_rows = (
        await db.execute(
            select(Course).where(Course.is_deleted.is_(False)).order_by(Course.created_at.desc())
        )
    ).scalars().all()

    lesson_rows = (
        await db.execute(
            select(Lesson.id, Lesson.course_id).where(Lesson.is_deleted.is_(False))
        )
    ).all()
    lessons_by_course: dict[str, list[str]] = {}
    lesson_to_course: dict[str, str] = {}
    for lid, cid in lesson_rows:
        c_key = str(cid)
        lessons_by_course.setdefault(c_key, []).append(str(lid))
        lesson_to_course[str(lid)] = c_key

    enrollment_rows = (
        await db.execute(
            select(Enrollment.course_id, Enrollment.progress_pct, Enrollment.completed_at)
        )
    ).all()
    enroll_by_course: dict[str, list[tuple[float, datetime | None]]] = {}
    for cid, pct, completed in enrollment_rows:
        enroll_by_course.setdefault(str(cid), []).append((float(pct or 0.0), completed))

    action_rows = (
        await db.execute(
            select(AgentAction.agent_name, AgentAction.input_data)
        )
    ).all()
    per_lesson_counts: dict[str, dict[str, int]] = {}
    for agent_name, inp in action_rows:
        if not isinstance(inp, dict):
            continue
        lid = inp.get("lesson_id")
        if not lid:
            continue
        bucket = per_lesson_counts.setdefault(str(lid), {"total": 0, "confusion": 0})
        bucket["total"] += 1
        if agent_name == "socratic_tutor":
            bucket["confusion"] += 1

    feedback_rows = (
        await db.execute(
            select(Feedback.route, Feedback.sentiment, Feedback.category).where(
                Feedback.resolved.is_(False)
            )
        )
    ).all()

    items: list[CourseHealth] = []
    for course in course_rows:
        cid_str = str(course.id)
        lesson_ids = lessons_by_course.get(cid_str, [])
        lessons_count = len(lesson_ids)

        enrolls = enroll_by_course.get(cid_str, [])
        enrollments = len(enrolls)
        if enrollments > 0:
            completed_n = sum(
                1 for pct, completed in enrolls if completed is not None or pct >= 100
            )
            completion_rate = completed_n / enrollments
        else:
            completion_rate = 0.0

        rates: list[float] = []
        for lid in lesson_ids:
            counts = per_lesson_counts.get(lid)
            if not counts or counts["total"] == 0:
                continue
            rates.append(counts["confusion"] / counts["total"])
        avg_confusion_rate = (sum(rates) / len(rates)) if rates else 0.0

        slug_needle = course.slug.lower()
        id_needle = cid_str.lower()
        open_feedback_count = 0
        negative_feedback_count = 0
        for route, sentiment, category in feedback_rows:
            r = (route or "").lower()
            if slug_needle in r or id_needle in r:
                open_feedback_count += 1
                if sentiment == "negative" or category == "bug":
                    negative_feedback_count += 1

        needs_attention = (
            (avg_confusion_rate > 0.3 and enrollments >= 5)
            or (completion_rate < 0.2 and enrollments >= 5)
            or negative_feedback_count > 0
        )

        updated_at = course.updated_at
        if updated_at is not None and updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)

        items.append(
            CourseHealth(
                course_id=cid_str,
                title=course.title,
                slug=course.slug,
                difficulty=course.difficulty,
                price_cents=course.price_cents,
                is_published=course.is_published,
                lessons_count=lessons_count,
                enrollments=enrollments,
                completion_rate=round(completion_rate, 4),
                avg_confusion_rate=round(avg_confusion_rate, 4),
                open_feedback_count=open_feedback_count,
                negative_feedback_count=negative_feedback_count,
                needs_attention=needs_attention,
                updated_at=updated_at or now,
            )
        )

    log.info(
        "admin.courses_health_viewed",
        course_count=len(items),
        needs_attention_count=sum(1 for i in items if i.needs_attention),
    )

    return CoursesHealthResponse(items=items, generated_at=now)


# ── Course Bundle CRUD ───────────────────────────────────────────────────────


class BundleSummary(PydanticModel):
    id: str
    slug: str
    title: str
    description: str | None
    price_cents: int
    currency: str
    course_ids: list[str]
    course_count: int
    is_published: bool
    sort_order: int
    updated_at: datetime
    expanded_courses: list[dict[str, Any]] | None = None


class BundlesListResponse(PydanticModel):
    items: list[BundleSummary]


class BundleCreate(PydanticModel):
    slug: str
    title: str
    description: str | None = None
    price_cents: int = 0
    currency: str = "INR"
    course_ids: list[str] = []
    is_published: bool = False
    sort_order: int = 0


class BundleUpdate(PydanticModel):
    slug: str | None = None
    title: str | None = None
    description: str | None = None
    price_cents: int | None = None
    currency: str | None = None
    course_ids: list[str] | None = None
    is_published: bool | None = None
    sort_order: int | None = None


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _bundle_to_summary(
    bundle: Any, expanded_courses: list[dict[str, Any]] | None = None
) -> BundleSummary:
    return BundleSummary(
        id=str(bundle.id),
        slug=bundle.slug,
        title=bundle.title,
        description=bundle.description,
        price_cents=bundle.price_cents,
        currency=bundle.currency,
        course_ids=list(bundle.course_ids or []),
        course_count=len(bundle.course_ids or []),
        is_published=bundle.is_published,
        sort_order=bundle.sort_order,
        updated_at=bundle.updated_at,
        expanded_courses=expanded_courses,
    )


async def _audit_log(
    db: AsyncSession,
    admin: User,
    action_type: str,
    target_id: str,
    metadata: dict[str, Any] | None = None,
    resource_type: str = "bundle",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Best-effort audit log. AdminAuditService may not be built yet."""
    try:
        from app.services.admin_audit_service import AdminAuditService

        await AdminAuditService.log(
            db=db,
            admin=admin,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=target_id,
            before=before,
            after=after,
            metadata=metadata or {},
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.debug(
            "admin.audit_log_skipped",
            action_type=action_type,
            target_id=target_id,
            error=str(exc),
        )


async def _expand_courses(
    db: AsyncSession, course_ids: list[str]
) -> list[dict[str, Any]]:
    """Resolve course_ids → [{id, slug, title, price_cents}, ...] preserving order."""
    if not course_ids:
        return []
    from app.models.course import Course

    try:
        uuid_ids = [uuid.UUID(cid) for cid in course_ids]
    except (ValueError, TypeError):
        return []
    result = await db.execute(select(Course).where(Course.id.in_(uuid_ids)))
    by_id = {str(c.id): c for c in result.scalars().all()}
    out: list[dict[str, Any]] = []
    for cid in course_ids:
        course = by_id.get(cid)
        if course is not None:
            out.append(
                {
                    "id": str(course.id),
                    "slug": course.slug,
                    "title": course.title,
                    "price_cents": course.price_cents,
                }
            )
    return out


@router.get("/bundles", response_model=BundlesListResponse)
async def list_bundles(
    include_courses: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> BundlesListResponse:
    """List all bundles (draft + published)."""
    from app.models.course_bundle import CourseBundle

    result = await db.execute(
        select(CourseBundle).order_by(CourseBundle.sort_order, CourseBundle.created_at)
    )
    bundles = result.scalars().all()
    items: list[BundleSummary] = []
    for b in bundles:
        expanded = (
            await _expand_courses(db, list(b.course_ids or []))
            if include_courses
            else None
        )
        items.append(_bundle_to_summary(b, expanded))
    log.info("admin.bundles_listed", count=len(items), include_courses=include_courses)
    return BundlesListResponse(items=items)


@router.post(
    "/bundles", response_model=BundleSummary, status_code=status.HTTP_201_CREATED
)
async def create_bundle(
    body: BundleCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> BundleSummary:
    """Create a new course bundle."""
    from sqlalchemy.exc import IntegrityError

    from app.models.course_bundle import CourseBundle

    bundle = CourseBundle(
        slug=body.slug,
        title=body.title,
        description=body.description,
        price_cents=body.price_cents,
        currency=body.currency,
        course_ids=_dedupe_preserve_order(body.course_ids),
        is_published=body.is_published,
        sort_order=body.sort_order,
    )
    db.add(bundle)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Bundle with slug '{body.slug}' already exists",
        ) from None
    await db.refresh(bundle)
    await _audit_log(
        db,
        admin,
        action_type="bundle.create",
        target_id=str(bundle.id),
        metadata={"slug": bundle.slug, "title": bundle.title},
    )
    log.info("admin.bundle_created", bundle_id=str(bundle.id), slug=bundle.slug)
    return _bundle_to_summary(bundle)


@router.patch("/bundles/{bundle_id}", response_model=BundleSummary)
async def update_bundle(
    bundle_id: uuid.UUID,
    body: BundleUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> BundleSummary:
    """Partial update — only non-None fields applied."""
    from sqlalchemy.exc import IntegrityError

    from app.models.course_bundle import CourseBundle

    result = await db.execute(select(CourseBundle).where(CourseBundle.id == bundle_id))
    bundle = result.scalar_one_or_none()
    if not bundle:
        raise HTTPException(status_code=404, detail="Bundle not found")

    updates = body.model_dump(exclude_unset=True)
    if "course_ids" in updates and updates["course_ids"] is not None:
        updates["course_ids"] = _dedupe_preserve_order(updates["course_ids"])

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, new_val in updates.items():
        if new_val is None:
            continue
        old_val = getattr(bundle, field)
        if old_val != new_val:
            before[field] = list(old_val) if isinstance(old_val, list) else old_val
            after[field] = list(new_val) if isinstance(new_val, list) else new_val
            setattr(bundle, field, new_val)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bundle slug conflict",
        ) from None
    await db.refresh(bundle)
    await _audit_log(
        db,
        admin,
        action_type="bundle.update",
        target_id=str(bundle.id),
        metadata={"before": before, "after": after},
    )
    log.info(
        "admin.bundle_updated",
        bundle_id=str(bundle.id),
        changed_fields=list(after.keys()),
    )
    return _bundle_to_summary(bundle)


@router.delete("/bundles/{bundle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bundle(
    bundle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> None:
    """Hard delete a bundle."""
    from app.models.course_bundle import CourseBundle

    result = await db.execute(select(CourseBundle).where(CourseBundle.id == bundle_id))
    bundle = result.scalar_one_or_none()
    if not bundle:
        raise HTTPException(status_code=404, detail="Bundle not found")
    slug = bundle.slug
    await db.delete(bundle)
    await db.commit()
    await _audit_log(
        db,
        admin,
        action_type="bundle.delete",
        target_id=str(bundle_id),
        metadata={"slug": slug},
    )
    log.info("admin.bundle_deleted", bundle_id=str(bundle_id), slug=slug)


@router.post("/bundles/{bundle_id}/courses/{course_id}", response_model=BundleSummary)
async def add_course_to_bundle(
    bundle_id: uuid.UUID,
    course_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> BundleSummary:
    """Append course_id to bundle.course_ids (idempotent)."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.models.course_bundle import CourseBundle

    result = await db.execute(select(CourseBundle).where(CourseBundle.id == bundle_id))
    bundle = result.scalar_one_or_none()
    if not bundle:
        raise HTTPException(status_code=404, detail="Bundle not found")

    current = list(bundle.course_ids or [])
    if course_id not in current:
        current.append(course_id)
        bundle.course_ids = current
        flag_modified(bundle, "course_ids")
        await db.commit()
        await db.refresh(bundle)
        await _audit_log(
            db,
            admin,
            action_type="bundle.add_course",
            target_id=str(bundle.id),
            metadata={"course_id": course_id},
        )
        log.info(
            "admin.bundle_course_added",
            bundle_id=str(bundle.id),
            course_id=course_id,
        )
    return _bundle_to_summary(bundle)


@router.delete(
    "/bundles/{bundle_id}/courses/{course_id}", response_model=BundleSummary
)
async def remove_course_from_bundle(
    bundle_id: uuid.UUID,
    course_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> BundleSummary:
    """Remove course_id from bundle.course_ids."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.models.course_bundle import CourseBundle

    result = await db.execute(select(CourseBundle).where(CourseBundle.id == bundle_id))
    bundle = result.scalar_one_or_none()
    if not bundle:
        raise HTTPException(status_code=404, detail="Bundle not found")

    current = list(bundle.course_ids or [])
    if course_id in current:
        current = [c for c in current if c != course_id]
        bundle.course_ids = current
        flag_modified(bundle, "course_ids")
        await db.commit()
        await db.refresh(bundle)
        await _audit_log(
            db,
            admin,
            action_type="bundle.remove_course",
            target_id=str(bundle.id),
            metadata={"course_id": course_id},
        )
        log.info(
            "admin.bundle_course_removed",
            bundle_id=str(bundle.id),
            course_id=course_id,
        )
    return _bundle_to_summary(bundle)


# ── Coupons ──────────────────────────────────────────────────────────────────


def _coupon_to_read(c: Any) -> CouponRead:
    return CouponRead(
        id=str(c.id),
        code=c.code,
        course_id=str(c.course_id) if c.course_id else None,
        bundle_id=str(c.bundle_id) if c.bundle_id else None,
        percent_off=c.percent_off,
        max_redemptions=c.max_redemptions,
        redemption_count=c.redemption_count,
        expires_at=c.expires_at,
        is_active=c.is_active,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


async def _audit(
    db: AsyncSession,
    admin_user: User,
    action_type: str,
    target_type: str,
    target_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    try:
        from app.services.admin_audit_service import AdminAuditService

        await AdminAuditService.log(
            db=db,
            admin=admin_user,
            action_type=action_type,
            resource_type=target_type,
            resource_id=target_id,
            before=before,
            after=after,
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.debug("admin_audit_service.unavailable", action_type=action_type, error=str(exc))


@router.get("/coupons")
async def list_coupons(
    course_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[CouponRead]:
    from app.models.coupon import Coupon

    stmt = select(Coupon)
    if course_id is not None:
        stmt = stmt.where(Coupon.course_id == course_id)
    stmt = stmt.order_by(Coupon.created_at.desc())
    result = await db.execute(stmt)
    coupons = result.scalars().all()
    return [_coupon_to_read(c) for c in coupons]


@router.post("/coupons", status_code=201)
async def create_coupon(
    body: CouponCreate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> CouponRead:
    from sqlalchemy.exc import IntegrityError

    from app.models.coupon import Coupon

    payload = body
    if payload.course_id and payload.bundle_id:
        raise HTTPException(
            status_code=400,
            detail="coupon may target a course OR a bundle, not both",
        )

    coupon = Coupon(
        code=payload.code,
        course_id=uuid.UUID(payload.course_id) if payload.course_id else None,
        bundle_id=uuid.UUID(payload.bundle_id) if payload.bundle_id else None,
        percent_off=payload.percent_off,
        max_redemptions=payload.max_redemptions,
        expires_at=payload.expires_at,
    )
    db.add(coupon)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="coupon code already exists") from None
    await db.refresh(coupon)

    log.info("admin.coupon_created", coupon_id=str(coupon.id), code=coupon.code)
    await _audit(
        db,
        admin_user=admin_user,
        action_type="coupon.create",
        target_type="coupon",
        target_id=str(coupon.id),
        after={
            "code": coupon.code,
            "course_id": str(coupon.course_id) if coupon.course_id else None,
            "bundle_id": str(coupon.bundle_id) if coupon.bundle_id else None,
            "percent_off": coupon.percent_off,
            "max_redemptions": coupon.max_redemptions,
            "expires_at": coupon.expires_at.isoformat() if coupon.expires_at else None,
        },
    )
    return _coupon_to_read(coupon)


@router.patch("/coupons/{coupon_id}")
async def update_coupon(
    coupon_id: uuid.UUID,
    body: CouponUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> CouponRead:
    from app.models.coupon import Coupon

    payload = body
    result = await db.execute(select(Coupon).where(Coupon.id == coupon_id))
    coupon = result.scalar_one_or_none()
    if not coupon:
        raise HTTPException(status_code=404, detail="coupon not found")

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}

    def _track(field: str, new_val: Any) -> None:
        cur = getattr(coupon, field)
        if cur != new_val:
            before[field] = cur.isoformat() if isinstance(cur, datetime) else cur
            after[field] = (
                new_val.isoformat() if isinstance(new_val, datetime) else new_val
            )

    if payload.percent_off is not None:
        _track("percent_off", payload.percent_off)
        coupon.percent_off = payload.percent_off
    if payload.max_redemptions is not None:
        _track("max_redemptions", payload.max_redemptions)
        coupon.max_redemptions = payload.max_redemptions
    if payload.expires_at is not None:
        _track("expires_at", payload.expires_at)
        coupon.expires_at = payload.expires_at
    if payload.is_active is not None:
        _track("is_active", payload.is_active)
        coupon.is_active = payload.is_active

    await db.commit()
    await db.refresh(coupon)

    log.info("admin.coupon_updated", coupon_id=str(coupon_id))
    if after:
        await _audit(
            db,
            admin_user=admin_user,
            action_type="coupon.update",
            target_type="coupon",
            target_id=str(coupon_id),
            before=before,
            after=after,
        )
    return _coupon_to_read(coupon)


@router.delete("/coupons/{coupon_id}", status_code=204)
async def delete_coupon(
    coupon_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> None:
    from app.models.coupon import Coupon

    result = await db.execute(select(Coupon).where(Coupon.id == coupon_id))
    coupon = result.scalar_one_or_none()
    if not coupon:
        raise HTTPException(status_code=404, detail="coupon not found")

    snapshot = {
        "code": coupon.code,
        "course_id": str(coupon.course_id) if coupon.course_id else None,
        "bundle_id": str(coupon.bundle_id) if coupon.bundle_id else None,
        "percent_off": coupon.percent_off,
    }
    await db.delete(coupon)
    await db.commit()

    log.info("admin.coupon_deleted", coupon_id=str(coupon_id))
    await _audit(
        db,
        admin_user=admin_user,
        action_type="coupon.delete",
        target_type="coupon",
        target_id=str(coupon_id),
        before=snapshot,
    )


@router.get("/courses/{course_id}/coupons")
async def list_course_coupons(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[CouponRead]:
    from sqlalchemy import or_

    from app.models.coupon import Coupon

    stmt = (
        select(Coupon)
        .where(
            or_(
                Coupon.course_id == course_id,
                (Coupon.course_id.is_(None)) & (Coupon.bundle_id.is_(None)),
            )
        )
        .order_by(Coupon.created_at.desc())
    )
    result = await db.execute(stmt)
    coupons = result.scalars().all()
    return [_coupon_to_read(c) for c in coupons]


# ── Agent runtime configuration (kill switch / rate limit / prompt version) ──


class AgentRuntimeConfigRead(PydanticModel):
    name: str
    is_enabled: bool
    rate_limit_per_minute: int | None
    prompt_version: str | None
    notes: str | None
    updated_at: datetime
    updated_by: str | None


class RuntimeConfigListResponse(PydanticModel):
    items: list[AgentRuntimeConfigRead]


class AgentConfigUpdate(PydanticModel):
    is_enabled: bool | None = None
    rate_limit_per_minute: int | None = None
    prompt_version: str | None = None
    notes: str | None = None


class AgentTriggerRequest(PydanticModel):
    student_id: str
    task: str | None = None
    # Optional one-shot trigger-and-send. If set, after the agent run
    # succeeds the admin output is dispatched to the student via the
    # same internal helper used by /agents/actions/{action_id}/send.
    auto_send_channel: str | None = None
    auto_send_body_override: str | None = None


class AgentTriggerResponse(PydanticModel):
    agent_name: str
    status: str
    duration_ms: int
    response_preview: str
    evaluation_score: float | None
    action_id: str | None
    # Populated when auto_send_channel was set on the request and the
    # follow-up outreach send succeeded; None otherwise (failed send is
    # logged but does NOT fail the trigger response).
    auto_send_outreach_id: str | None = None


def _runtime_cfg_to_read(row: Any) -> AgentRuntimeConfigRead:
    return AgentRuntimeConfigRead(
        name=row.name,
        is_enabled=bool(row.is_enabled),
        rate_limit_per_minute=row.rate_limit_per_minute,
        prompt_version=row.prompt_version,
        notes=row.notes,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


@router.get("/agents/runtime-config", response_model=RuntimeConfigListResponse)
async def list_agent_runtime_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> RuntimeConfigListResponse:
    """List runtime config rows for every registered agent.

    Agents that have no row yet are returned as synthetic enabled defaults so
    the admin UI sees all entries from AGENT_REGISTRY.
    """
    from app.agents.registry import AGENT_REGISTRY, _ensure_registered
    from app.models.agent_runtime_config import AgentRuntimeConfig

    _ensure_registered()

    result = await db.execute(select(AgentRuntimeConfig))
    rows = {row.name: row for row in result.scalars().all()}

    items: list[AgentRuntimeConfigRead] = []
    seen: set[str] = set()
    for agent_name in AGENT_REGISTRY:
        seen.add(agent_name)
        row = rows.get(agent_name)
        if row is not None:
            items.append(_runtime_cfg_to_read(row))
        else:
            items.append(
                AgentRuntimeConfigRead(
                    name=agent_name,
                    is_enabled=True,
                    rate_limit_per_minute=None,
                    prompt_version=None,
                    notes=None,
                    updated_at=datetime.now(UTC),
                    updated_by=None,
                )
            )
    # Include any DB rows for agents no longer in the registry so admins
    # can still see / clean them up.
    for name, row in rows.items():
        if name not in seen:
            items.append(_runtime_cfg_to_read(row))

    items.sort(key=lambda i: i.name)
    return RuntimeConfigListResponse(items=items)


@router.patch("/agents/{name}/config", response_model=AgentRuntimeConfigRead)
async def upsert_agent_runtime_config(
    name: str,
    payload: AgentConfigUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> AgentRuntimeConfigRead:
    """Upsert runtime config for an agent. Creates the row on first call."""
    from app.models.agent_runtime_config import AgentRuntimeConfig

    result = await db.execute(
        select(AgentRuntimeConfig).where(AgentRuntimeConfig.name == name)
    )
    row = result.scalar_one_or_none()

    before: dict[str, Any] | None = None
    fields_set = payload.model_fields_set
    if row is None:
        row = AgentRuntimeConfig(
            name=name,
            is_enabled=payload.is_enabled if payload.is_enabled is not None else True,
            rate_limit_per_minute=payload.rate_limit_per_minute,
            prompt_version=payload.prompt_version,
            notes=payload.notes,
            updated_by=admin.email,
        )
        db.add(row)
    else:
        before = {
            "is_enabled": row.is_enabled,
            "rate_limit_per_minute": row.rate_limit_per_minute,
            "prompt_version": row.prompt_version,
            "notes": row.notes,
        }
        if "is_enabled" in fields_set and payload.is_enabled is not None:
            row.is_enabled = payload.is_enabled
        if "rate_limit_per_minute" in fields_set:
            row.rate_limit_per_minute = payload.rate_limit_per_minute
        if "prompt_version" in fields_set:
            row.prompt_version = payload.prompt_version
        if "notes" in fields_set:
            row.notes = payload.notes
        row.updated_by = admin.email

    await db.flush()

    after = {
        "is_enabled": row.is_enabled,
        "rate_limit_per_minute": row.rate_limit_per_minute,
        "prompt_version": row.prompt_version,
        "notes": row.notes,
    }

    try:
        await AdminAuditService.log(
            db=db,
            admin=admin,
            action_type="agent.config_update",
            resource_type="agent",
            resource_id=name,
            before=before,
            after=after,
            request=request,
        )
    except Exception:
        log.exception("admin.agent_config_update.audit_failed", agent=name)
    await db.commit()

    log.info(
        "admin.agent_runtime_config.updated",
        agent=name,
        admin_email=admin.email,
        before=before,
        after=after,
    )
    await db.refresh(row)
    return _runtime_cfg_to_read(row)


@router.post("/agents/{name}/trigger/v2", response_model=AgentTriggerResponse)
async def trigger_agent_v2(
    name: str,
    payload: AgentTriggerRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> AgentTriggerResponse:
    """Admin manual trigger with audit logging.

    A sibling endpoint POST /agents/{agent_name}/trigger already exists
    higher in this file (DISC-57). This v2 endpoint preserves that contract
    for the existing useTriggerAgent hook and adds the audit-logged variant
    expected by the runtime-config admin panel. Both share the underlying
    `agent.run(state)` pattern; agent_actions logging is performed by
    BaseAgent.log_action, while the AdminAuditLog row below records the
    admin attribution.
    """
    import time as _time

    from app.agents.base_agent import AgentState
    from app.agents.registry import _ensure_registered, get_agent
    from app.models.agent_action import AgentAction

    try:
        student_uuid = uuid.UUID(payload.student_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid student_id") from exc

    student = await _require_student(db, student_uuid)

    _ensure_registered()
    try:
        agent = get_agent(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent not found.") from exc

    task = payload.task or f"Admin-triggered run of {name} for {student.email}."
    state = AgentState(
        student_id=str(student.id),
        task=task,
        context={
            "actor_id": str(admin.id),
            "actor_role": "admin",
            "on_behalf_of": str(student.id),
            "trigger": "admin_manual",
        },
    )

    start = _time.monotonic()
    status_out = "success"
    result = None
    try:
        result = await agent.run(state)
        if result.error:
            status_out = "error"
    except Exception as exc:
        log.exception("admin.agent_trigger_v2.failed", agent=name, error=str(exc))
        status_out = "error"
    duration_ms = int((_time.monotonic() - start) * 1000)

    preview = ""
    eval_score: float | None = None
    if result is not None:
        preview = (result.response or result.error or "").strip()
        if len(preview) > 280:
            preview = preview[:277] + "..."
        eval_score = result.evaluation_score

    action_id: str | None = None
    try:
        action_row = await db.execute(
            select(AgentAction.id)
            .where(
                AgentAction.agent_name == name,
                AgentAction.student_id == student.id,
            )
            .order_by(AgentAction.created_at.desc())
            .limit(1)
        )
        latest = action_row.scalar_one_or_none()
        if latest is not None:
            action_id = str(latest)
    except Exception:
        log.exception("admin.agent_trigger_v2.action_lookup_failed", agent=name)

    try:
        await AdminAuditService.log(
            db=db,
            admin=admin,
            action_type="agent.manual_trigger",
            resource_type="agent",
            resource_id=name,
            metadata={
                "student_id": str(student.id),
                "agent_name": name,
                "task_preview": (task or "")[:200],
                "status": status_out,
                "duration_ms": duration_ms,
            },
            request=request,
        )
    except Exception:
        log.exception("admin.agent_trigger_v2.audit_failed", agent=name)
    await db.commit()

    log.info(
        "admin.agent_triggered_v2",
        agent=name,
        admin_id=str(admin.id),
        student_id=str(student.id),
        duration_ms=duration_ms,
        status=status_out,
    )

    auto_send_outreach_id: str | None = None
    if (
        payload.auto_send_channel
        and status_out == "success"
        and action_id is not None
    ):
        try:
            send_result = await _send_agent_output_internal(
                db=db,
                request=request,
                admin=admin,
                action_id=uuid.UUID(action_id),
                channel=payload.auto_send_channel,
                body_override=payload.auto_send_body_override,
                student_id_check=None,
            )
            auto_send_outreach_id = send_result.outreach_id
        except HTTPException as exc:
            log.warning(
                "admin.agent_trigger_v2.auto_send_failed",
                agent=name,
                action_id=action_id,
                detail=str(exc.detail),
            )
        except Exception:
            log.exception(
                "admin.agent_trigger_v2.auto_send_error",
                agent=name,
                action_id=action_id,
            )

    return AgentTriggerResponse(
        agent_name=name,
        status=status_out,
        duration_ms=duration_ms,
        response_preview=preview,
        evaluation_score=eval_score,
        action_id=action_id,
        auto_send_outreach_id=auto_send_outreach_id,
    )


# ── Agent observability endpoints ────────────────────────────────────────────


_STUB_AGENTS: frozenset[str] = frozenset(
    {
        "content_ingestion",
        "deep_capturer",
        "knowledge_graph",
        "job_match",
        "peer_matching",
        "spaced_repetition",
    }
)


def _cost_per_call(agent_name: str) -> float:
    if agent_name == "moa":
        return 0.001
    if agent_name in {"student_buddy", "socratic_tutor"}:
        return 0.005
    if agent_name in {"mock_interview", "project_evaluator", "progress_report"}:
        return 0.015
    return 0.008


def _eval_score_from_output(output_data: Any) -> float | None:
    if not isinstance(output_data, dict):
        return None
    raw = output_data.get("evaluation_score")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _stringify_preview(data: Any, limit: int) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        text = data
    else:
        import json as _json

        try:
            text = _json.dumps(data, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(data)
    return text[:limit]


class AgentHealthExtended(PydanticModel):
    name: str
    description: str
    total_actions: int
    actions_24h: int
    error_count: int
    errors_24h: int
    avg_duration_ms: int
    avg_duration_24h_ms: int
    last_called_at: datetime | None
    success_rate: float | None
    avg_eval_score_24h: float | None
    status: str
    is_stub: bool
    calls_sparkline: list[int]
    eval_sparkline: list[float | None]
    est_cost_24h_usd: float
    model: str | None
    actions_24h_by_role: dict[str, int]
    total_actions_by_role: dict[str, int]


class AgentsHealthExtendedResponse(PydanticModel):
    agents: list[AgentHealthExtended]
    total_actions_24h: int
    total_errors_24h: int
    total_cost_24h_usd: float
    healthy_count: int
    degraded_count: int
    generated_at: datetime
    total_actions_24h_by_role: dict[str, int]


@router.get("/agents/health-extended", response_model=AgentsHealthExtendedResponse)
async def get_agents_health_extended(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> AgentsHealthExtendedResponse:
    from app.agents.registry import AGENT_REGISTRY, _ensure_registered, list_agents

    _ensure_registered()
    all_agents = list_agents()

    now = datetime.now(UTC)
    window_start = now - timedelta(hours=24)
    bucket_starts: list[datetime] = [
        (now - timedelta(hours=23 - i)).replace(minute=0, second=0, microsecond=0)
        for i in range(24)
    ]

    agents_out: list[AgentHealthExtended] = []
    total_actions_24h = 0
    total_errors_24h = 0
    total_cost_24h = 0.0
    healthy = 0
    degraded = 0
    platform_actions_24h_by_role: dict[str, int] = {}

    # Single-pass per-role aggregations (one query each, grouped in SQL).
    role_24h_rows = (
        await db.execute(
            select(
                AgentAction.agent_name,
                AgentAction.actor_role,
                func.count(AgentAction.id),
            )
            .where(AgentAction.created_at >= window_start)
            .group_by(AgentAction.agent_name, AgentAction.actor_role)
        )
    ).all()
    actions_24h_by_role_map: dict[str, dict[str, int]] = {}
    for a_name, role, cnt in role_24h_rows:
        bucket = actions_24h_by_role_map.setdefault(a_name, {})
        role_key = role if role else "unknown"
        bucket[role_key] = bucket.get(role_key, 0) + int(cnt)
        platform_actions_24h_by_role[role_key] = (
            platform_actions_24h_by_role.get(role_key, 0) + int(cnt)
        )

    role_total_rows = (
        await db.execute(
            select(
                AgentAction.agent_name,
                AgentAction.actor_role,
                func.count(AgentAction.id),
            ).group_by(AgentAction.agent_name, AgentAction.actor_role)
        )
    ).all()
    total_actions_by_role_map: dict[str, dict[str, int]] = {}
    for a_name, role, cnt in role_total_rows:
        bucket = total_actions_by_role_map.setdefault(a_name, {})
        role_key = role if role else "unknown"
        bucket[role_key] = bucket.get(role_key, 0) + int(cnt)

    for agent_info in all_agents:
        name = agent_info["name"]

        total_actions = (
            await db.execute(
                select(func.count(AgentAction.id)).where(AgentAction.agent_name == name)
            )
        ).scalar_one()

        avg_duration_all = (
            await db.execute(
                select(func.avg(AgentAction.duration_ms)).where(
                    AgentAction.agent_name == name
                )
            )
        ).scalar()

        errors_all = (
            await db.execute(
                select(func.count(AgentAction.id)).where(
                    AgentAction.agent_name == name,
                    AgentAction.status == "error",
                )
            )
        ).scalar_one()

        last_called_at = (
            await db.execute(
                select(func.max(AgentAction.created_at)).where(
                    AgentAction.agent_name == name
                )
            )
        ).scalar()

        actions_24h = (
            await db.execute(
                select(func.count(AgentAction.id)).where(
                    AgentAction.agent_name == name,
                    AgentAction.created_at >= window_start,
                )
            )
        ).scalar_one()

        errors_24h = (
            await db.execute(
                select(func.count(AgentAction.id)).where(
                    AgentAction.agent_name == name,
                    AgentAction.status == "error",
                    AgentAction.created_at >= window_start,
                )
            )
        ).scalar_one()

        avg_duration_24h = (
            await db.execute(
                select(func.avg(AgentAction.duration_ms)).where(
                    AgentAction.agent_name == name,
                    AgentAction.created_at >= window_start,
                )
            )
        ).scalar()

        rows_24h = (
            await db.execute(
                select(AgentAction.created_at, AgentAction.output_data).where(
                    AgentAction.agent_name == name,
                    AgentAction.created_at >= window_start,
                )
            )
        ).all()

        calls_sparkline = [0] * 24
        eval_buckets: list[list[float]] = [[] for _ in range(24)]
        eval_all_24h: list[float] = []
        for created_at, output_data in rows_24h:
            ts = created_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            for idx in range(23, -1, -1):
                if ts >= bucket_starts[idx]:
                    calls_sparkline[idx] += 1
                    score = _eval_score_from_output(output_data)
                    if score is not None:
                        eval_buckets[idx].append(score)
                        eval_all_24h.append(score)
                    break

        eval_sparkline: list[float | None] = [
            round(sum(b) / len(b), 4) if b else None for b in eval_buckets
        ]
        avg_eval_score_24h = (
            round(sum(eval_all_24h) / len(eval_all_24h), 4)
            if eval_all_24h
            else None
        )

        if total_actions > 0:
            success_rate: float | None = round(1.0 - (errors_all / total_actions), 3)
        else:
            success_rate = None

        agent_status = "healthy" if errors_24h == 0 else "degraded"
        if agent_status == "healthy":
            healthy += 1
        else:
            degraded += 1

        agent_cls = AGENT_REGISTRY.get(name)
        model_name: str | None = None
        if agent_cls is not None:
            raw_model = getattr(agent_cls, "model", None)
            model_name = str(raw_model) if isinstance(raw_model, str) else None

        cost_24h = round(actions_24h * _cost_per_call(name), 6)
        total_actions_24h += actions_24h
        total_errors_24h += errors_24h
        total_cost_24h += cost_24h

        agents_out.append(
            AgentHealthExtended(
                name=name,
                description=agent_info["description"],
                total_actions=total_actions,
                actions_24h=actions_24h,
                error_count=errors_all,
                errors_24h=errors_24h,
                avg_duration_ms=int(round(float(avg_duration_all or 0))),
                avg_duration_24h_ms=int(round(float(avg_duration_24h or 0))),
                last_called_at=last_called_at,
                success_rate=success_rate,
                avg_eval_score_24h=avg_eval_score_24h,
                status=agent_status,
                is_stub=name in _STUB_AGENTS,
                calls_sparkline=calls_sparkline,
                eval_sparkline=eval_sparkline,
                est_cost_24h_usd=cost_24h,
                model=model_name,
                actions_24h_by_role=actions_24h_by_role_map.get(name, {}),
                total_actions_by_role=total_actions_by_role_map.get(name, {}),
            )
        )

    log.info(
        "admin.agents.health_extended",
        total_actions_24h=total_actions_24h,
        total_errors_24h=total_errors_24h,
    )
    return AgentsHealthExtendedResponse(
        agents=agents_out,
        total_actions_24h=total_actions_24h,
        total_errors_24h=total_errors_24h,
        total_cost_24h_usd=round(total_cost_24h, 6),
        healthy_count=healthy,
        degraded_count=degraded,
        generated_at=now,
        total_actions_24h_by_role=platform_actions_24h_by_role,
    )


class AgentRecentError(PydanticModel):
    action_id: str
    student_id: str | None
    student_name: str | None
    error: str
    input_preview: str
    created_at: datetime


class AgentSampleAction(PydanticModel):
    action_id: str
    student_id: str | None
    student_name: str | None
    input_preview: str
    output_preview: str
    evaluation_score: float | None
    duration_ms: int
    created_at: datetime


class AgentDetailResponse(PydanticModel):
    name: str
    description: str
    model: str | None
    is_stub: bool
    prompt_content: str | None
    prompt_path: str | None
    actions_24h: int
    actions_7d: int
    actions_all_time: int
    avg_eval_score_24h: float | None
    avg_eval_score_7d: float | None
    avg_duration_24h_ms: int
    recent_errors: list[AgentRecentError]
    recent_samples: list[AgentSampleAction]
    est_cost_7d_usd: float
    est_cost_total_usd: float
    actions_24h_by_role: dict[str, int]
    actions_7d_by_role: dict[str, int]
    actions_all_time_by_role: dict[str, int]


@router.get("/agents/{agent_name}/detail", response_model=AgentDetailResponse)
async def get_agent_detail(
    agent_name: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> AgentDetailResponse:
    from pathlib import Path

    from app.agents.registry import AGENT_REGISTRY, _ensure_registered

    _ensure_registered()
    agent_cls = AGENT_REGISTRY.get(agent_name)
    if agent_cls is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    description = str(getattr(agent_cls, "description", "") or "")
    raw_model = getattr(agent_cls, "model", None)
    model_name = str(raw_model) if isinstance(raw_model, str) else None

    # Assumption: prompts live at backend/app/agents/prompts/{name}.md.
    # __file__ = backend/app/api/v1/routes/admin.py → parents[4] = backend/app.
    prompt_path = (
        Path(__file__).resolve().parents[3] / "agents" / "prompts" / f"{agent_name}.md"
    )
    prompt_content: str | None = None
    prompt_path_str: str | None = None
    if prompt_path.exists():
        try:
            prompt_content = prompt_path.read_text(encoding="utf-8")
            prompt_path_str = str(prompt_path)
        except OSError:
            prompt_content = None

    now = datetime.now(UTC)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    actions_all = (
        await db.execute(
            select(func.count(AgentAction.id)).where(AgentAction.agent_name == agent_name)
        )
    ).scalar_one()

    actions_24h = (
        await db.execute(
            select(func.count(AgentAction.id)).where(
                AgentAction.agent_name == agent_name,
                AgentAction.created_at >= cutoff_24h,
            )
        )
    ).scalar_one()

    actions_7d = (
        await db.execute(
            select(func.count(AgentAction.id)).where(
                AgentAction.agent_name == agent_name,
                AgentAction.created_at >= cutoff_7d,
            )
        )
    ).scalar_one()

    avg_duration_24h = (
        await db.execute(
            select(func.avg(AgentAction.duration_ms)).where(
                AgentAction.agent_name == agent_name,
                AgentAction.created_at >= cutoff_24h,
            )
        )
    ).scalar()

    rows_24h = (
        await db.execute(
            select(AgentAction.output_data).where(
                AgentAction.agent_name == agent_name,
                AgentAction.created_at >= cutoff_24h,
            )
        )
    ).all()
    rows_7d = (
        await db.execute(
            select(AgentAction.output_data).where(
                AgentAction.agent_name == agent_name,
                AgentAction.created_at >= cutoff_7d,
            )
        )
    ).all()

    def _avg_eval(rows: list[Any]) -> float | None:
        scores: list[float] = []
        for (output_data,) in rows:
            s = _eval_score_from_output(output_data)
            if s is not None:
                scores.append(s)
        return round(sum(scores) / len(scores), 4) if scores else None

    avg_eval_24h = _avg_eval(rows_24h)
    avg_eval_7d = _avg_eval(rows_7d)

    errors_stmt = (
        select(AgentAction, User.full_name)
        .outerjoin(User, AgentAction.student_id == User.id)
        .where(
            AgentAction.agent_name == agent_name,
            AgentAction.error_message.isnot(None),
        )
        .order_by(AgentAction.created_at.desc())
        .limit(5)
    )
    errors_result = (await db.execute(errors_stmt)).all()
    recent_errors: list[AgentRecentError] = []
    for action, full_name in errors_result:
        recent_errors.append(
            AgentRecentError(
                action_id=str(action.id),
                student_id=str(action.student_id) if action.student_id else None,
                student_name=full_name,
                error=action.error_message or "",
                input_preview=_stringify_preview(action.input_data, 200),
                created_at=action.created_at,
            )
        )

    samples_stmt = (
        select(AgentAction, User.full_name)
        .outerjoin(User, AgentAction.student_id == User.id)
        .where(
            AgentAction.agent_name == agent_name,
            AgentAction.error_message.is_(None),
        )
        .order_by(AgentAction.created_at.desc())
        .limit(10)
    )
    samples_result = (await db.execute(samples_stmt)).all()
    recent_samples: list[AgentSampleAction] = []
    for action, full_name in samples_result:
        recent_samples.append(
            AgentSampleAction(
                action_id=str(action.id),
                student_id=str(action.student_id) if action.student_id else None,
                student_name=full_name,
                input_preview=_stringify_preview(action.input_data, 200),
                output_preview=_stringify_preview(action.output_data, 300),
                evaluation_score=_eval_score_from_output(action.output_data),
                duration_ms=int(action.duration_ms or 0),
                created_at=action.created_at,
            )
        )

    cost_per = _cost_per_call(agent_name)

    # Role breakdown: one SQL GROUP BY, partition windows in Python.
    role_rows = (
        await db.execute(
            select(
                AgentAction.actor_role,
                AgentAction.created_at,
            ).where(AgentAction.agent_name == agent_name)
        )
    ).all()
    by_role_24h: dict[str, int] = {}
    by_role_7d: dict[str, int] = {}
    by_role_all: dict[str, int] = {}
    for role, created_at in role_rows:
        role_key = role if role else "unknown"
        by_role_all[role_key] = by_role_all.get(role_key, 0) + 1
        ts = created_at
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts is not None and ts >= cutoff_7d:
            by_role_7d[role_key] = by_role_7d.get(role_key, 0) + 1
        if ts is not None and ts >= cutoff_24h:
            by_role_24h[role_key] = by_role_24h.get(role_key, 0) + 1

    return AgentDetailResponse(
        name=agent_name,
        description=description,
        model=model_name,
        is_stub=agent_name in _STUB_AGENTS,
        prompt_content=prompt_content,
        prompt_path=prompt_path_str,
        actions_24h=actions_24h,
        actions_7d=actions_7d,
        actions_all_time=actions_all,
        avg_eval_score_24h=avg_eval_24h,
        avg_eval_score_7d=avg_eval_7d,
        avg_duration_24h_ms=int(round(float(avg_duration_24h or 0))),
        recent_errors=recent_errors,
        recent_samples=recent_samples,
        est_cost_7d_usd=round(actions_7d * cost_per, 6),
        est_cost_total_usd=round(actions_all * cost_per, 6),
        actions_24h_by_role=by_role_24h,
        actions_7d_by_role=by_role_7d,
        actions_all_time_by_role=by_role_all,
    )


class RecentActivityRow(PydanticModel):
    action_id: str
    agent_name: str
    student_id: str | None
    student_name: str | None
    duration_ms: int
    evaluation_score: float | None
    has_error: bool
    error_preview: str | None
    input_preview: str
    output_preview: str
    created_at: datetime
    actor_role: str | None
    actor_id: str | None
    on_behalf_of: str | None


class RecentActivityResponse(PydanticModel):
    items: list[RecentActivityRow]
    total_returned: int


@router.get("/agents/recent-activity", response_model=RecentActivityResponse)
async def get_agents_recent_activity(
    agent_name: str | None = Query(default=None, max_length=100),
    student_id: uuid.UUID | None = Query(default=None),
    min_eval_score: float | None = Query(default=None, ge=0.0, le=1.0),
    actor_role: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> RecentActivityResponse:
    stmt = (
        select(AgentAction, User.full_name)
        .outerjoin(User, AgentAction.student_id == User.id)
        .order_by(AgentAction.created_at.desc())
    )
    if agent_name is not None:
        stmt = stmt.where(AgentAction.agent_name == agent_name)
    if student_id is not None:
        stmt = stmt.where(AgentAction.student_id == student_id)
    if actor_role is not None:
        if actor_role == "unknown":
            stmt = stmt.where(AgentAction.actor_role.is_(None))
        else:
            stmt = stmt.where(AgentAction.actor_role == actor_role)

    # eval_score lives in output_data JSON; filter in Python and over-fetch.
    fetch_limit = limit * 4 if min_eval_score is not None else limit
    stmt = stmt.limit(fetch_limit)
    rows = (await db.execute(stmt)).all()

    items: list[RecentActivityRow] = []
    for action, full_name in rows:
        score = _eval_score_from_output(action.output_data)
        if min_eval_score is not None and (score is None or score < min_eval_score):
            continue
        items.append(
            RecentActivityRow(
                action_id=str(action.id),
                agent_name=action.agent_name,
                student_id=str(action.student_id) if action.student_id else None,
                student_name=full_name,
                duration_ms=int(action.duration_ms or 0),
                evaluation_score=score,
                has_error=action.error_message is not None,
                error_preview=(action.error_message or "")[:100]
                if action.error_message
                else None,
                input_preview=_stringify_preview(action.input_data, 150),
                output_preview=_stringify_preview(action.output_data, 300),
                created_at=action.created_at,
                actor_role=action.actor_role,
                actor_id=str(action.actor_id) if action.actor_id else None,
                on_behalf_of=str(action.on_behalf_of) if action.on_behalf_of else None,
            )
        )
        if len(items) >= limit:
            break

    return RecentActivityResponse(items=items, total_returned=len(items))


class RoutingHealthResponse(PydanticModel):
    total_routes_24h: int
    keyword_hits_24h: int
    llm_fallback_24h: int
    keyword_hit_rate: float
    agent_distribution_24h: dict[str, int]
    suspected_misroutes_24h: int
    misroutes_by_agent: dict[str, int]
    generated_at: datetime
    # Assumption: MOA does NOT currently persist routed_via/routing_method to
    # agent_actions.input_data — it only structlogs the routing reason in
    # moa.classify_intent. Until MOA is updated to write this field, all
    # rows default to the llm_fallback bucket and this flag stays False.
    routing_metadata_available: bool


@router.get("/agents/routing-health", response_model=RoutingHealthResponse)
async def get_agents_routing_health(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> RoutingHealthResponse:
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=24)

    rows = (
        await db.execute(
            select(
                AgentAction.agent_name,
                AgentAction.input_data,
                AgentAction.output_data,
            ).where(AgentAction.created_at >= cutoff)
        )
    ).all()

    total = 0
    keyword_hits = 0
    llm_fallback = 0
    routing_metadata_seen = False
    agent_distribution: dict[str, int] = {}
    misroutes_by_agent: dict[str, int] = {}
    suspected_misroutes = 0

    for name, input_data, output_data in rows:
        total += 1
        agent_distribution[name] = agent_distribution.get(name, 0) + 1

        routed_via: str | None = None
        if isinstance(input_data, dict):
            raw = input_data.get("routed_via") or input_data.get("routing_method")
            if isinstance(raw, str):
                routed_via = raw.lower()
                routing_metadata_seen = True
        if routed_via == "keyword":
            keyword_hits += 1
        else:
            llm_fallback += 1

        score = _eval_score_from_output(output_data)
        if score is not None and score < 0.4:
            suspected_misroutes += 1
            misroutes_by_agent[name] = misroutes_by_agent.get(name, 0) + 1

    keyword_hit_rate = round(keyword_hits / total, 4) if total > 0 else 0.0

    return RoutingHealthResponse(
        total_routes_24h=total,
        keyword_hits_24h=keyword_hits,
        llm_fallback_24h=llm_fallback,
        keyword_hit_rate=keyword_hit_rate,
        agent_distribution_24h=agent_distribution,
        suspected_misroutes_24h=suspected_misroutes,
        misroutes_by_agent=misroutes_by_agent,
        generated_at=now,
        routing_metadata_available=routing_metadata_seen,
    )


# ── Agent context preview (admin pre-trigger readiness check) ────────────────


class ContextFactor(PydanticModel):
    label: str
    present: bool


class ContextPreviewResponse(PydanticModel):
    agent_name: str
    student_id: str
    readiness_score: float
    tone: str
    summary: str
    factors: list[ContextFactor]
    student_name: str | None
    student_email: str | None
    generated_at: datetime


def _last_active_phrase(last_login_at: datetime | None, now: datetime) -> str:
    """Return a short 'X ago' phrase for a last-active timestamp."""
    if last_login_at is None:
        return "never active"
    ts = last_login_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    seconds = max(0, int((now - ts).total_seconds()))
    if seconds < 60:
        return "active just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"active {minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"active {hours}h ago"
    days = hours // 24
    return f"active {days}d ago"


async def _count_completed_lessons(db: AsyncSession, student_id: uuid.UUID) -> int:
    from app.models.student_progress import StudentProgress

    result = await db.execute(
        select(func.count())
        .select_from(StudentProgress)
        .where(
            StudentProgress.student_id == student_id,
            StudentProgress.status == "completed",
        )
    )
    return int(result.scalar() or 0)


async def _count_completions_since(
    db: AsyncSession, student_id: uuid.UUID, since: datetime
) -> int:
    from app.models.student_progress import StudentProgress

    result = await db.execute(
        select(func.count())
        .select_from(StudentProgress)
        .where(
            StudentProgress.student_id == student_id,
            StudentProgress.status == "completed",
            StudentProgress.completed_at.is_not(None),
            StudentProgress.completed_at >= since,
        )
    )
    return int(result.scalar() or 0)


async def _count_agent_actions(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    agent_name: str | None = None,
    since: datetime | None = None,
) -> int:
    stmt = (
        select(func.count())
        .select_from(AgentAction)
        .where(AgentAction.student_id == student_id)
    )
    if agent_name is not None:
        stmt = stmt.where(AgentAction.agent_name == agent_name)
    if since is not None:
        stmt = stmt.where(AgentAction.created_at >= since)
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def _count_exercise_submissions(
    db: AsyncSession, student_id: uuid.UUID, *, status_filter: str | None = None
) -> int:
    from app.models.exercise_submission import ExerciseSubmission

    stmt = (
        select(func.count())
        .select_from(ExerciseSubmission)
        .where(ExerciseSubmission.student_id == student_id)
    )
    if status_filter is not None:
        stmt = stmt.where(ExerciseSubmission.status == status_filter)
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def _has_resume(db: AsyncSession, student_id: uuid.UUID) -> bool:
    """Check the dedicated `resumes` table (no resume_url column on User)."""
    from app.models.resume import Resume

    result = await db.execute(
        select(func.count()).select_from(Resume).where(Resume.user_id == student_id)
    )
    return int(result.scalar() or 0) > 0


async def _count_quiz_results(db: AsyncSession, student_id: uuid.UUID) -> int:
    from app.models.quiz_result import QuizResult

    result = await db.execute(
        select(func.count())
        .select_from(QuizResult)
        .where(QuizResult.student_id == student_id)
    )
    return int(result.scalar() or 0)


def _days_inactive(student: User, now: datetime) -> int | None:
    if student.last_login_at is None:
        return None
    ts = student.last_login_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return int((now - ts).total_seconds() // 86400)


# Readiness check signature:
#   async def check(student: User, db: AsyncSession) -> tuple[float, list[ContextFactor]]


async def _check_cover_letter(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    has_resume = await _has_resume(db, student.id)
    capstone_subs = await _count_exercise_submissions(db, student.id)
    factors = [
        ContextFactor(label="Resume on file" if has_resume else "No resume on file", present=has_resume),
        ContextFactor(
            label=f"{capstone_subs} project submission(s)" if capstone_subs >= 1 else "No project submissions",
            present=capstone_subs >= 1,
        ),
    ]
    score = (0.5 if has_resume else 0.0) + (0.5 if capstone_subs >= 1 else 0.0)
    return score, factors


async def _check_mock_interview(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    completed = await _count_completed_lessons(db, student.id)
    prior_mocks = await _count_agent_actions(db, student.id, agent_name="mock_interview")
    factors = [
        ContextFactor(
            label=f"{completed} lessons completed" if completed >= 5 else f"Only {completed} lessons completed (need 5)",
            present=completed >= 5,
        ),
        ContextFactor(
            label=f"{prior_mocks} prior mock interview(s)" if prior_mocks >= 1 else "No prior mock interviews",
            present=prior_mocks >= 1,
        ),
    ]
    score = (0.6 if completed >= 5 else 0.0) + (0.4 if prior_mocks >= 1 else 0.0)
    return score, factors


async def _check_progress_report(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=14)
    recent_completions = await _count_completions_since(db, student.id, cutoff)
    recent_actions = await _count_agent_actions(db, student.id, since=cutoff)
    factors = [
        ContextFactor(
            label=f"{recent_completions} lessons completed in last 14d"
            if recent_completions >= 1
            else "No lesson completions in last 14d",
            present=recent_completions >= 1,
        ),
        ContextFactor(
            label=f"{recent_actions} agent action(s) in last 14d"
            if recent_actions >= 1
            else "No agent activity in last 14d",
            present=recent_actions >= 1,
        ),
    ]
    score = (0.5 if recent_completions >= 1 else 0.0) + (0.5 if recent_actions >= 1 else 0.0)
    return score, factors


async def _check_disrupt_prevention(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    now = datetime.now(UTC)
    days = _days_inactive(student, now)
    needs_reengagement = days is not None and days >= 3
    if days is None:
        label = "Never logged in (re-engagement candidate)"
        needs_reengagement = True
    elif needs_reengagement:
        label = f"Inactive {days}d (re-engagement warranted)"
    else:
        label = f"Active {days}d ago (no re-engagement needed)"
    factors = [ContextFactor(label=label, present=needs_reengagement)]
    score = 1.0 if needs_reengagement else 0.3
    return score, factors


async def _check_socratic_tutor(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    factors = [ContextFactor(label="Always ready — needs only a question", present=True)]
    return 1.0, factors


async def _check_adaptive_quiz(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    completed = await _count_completed_lessons(db, student.id)
    prior_quizzes = await _count_quiz_results(db, student.id)
    factors = [
        ContextFactor(
            label=f"{completed} lessons completed" if completed >= 3 else f"Only {completed} lessons completed (need 3)",
            present=completed >= 3,
        ),
        ContextFactor(
            label=f"{prior_quizzes} prior quiz result(s)" if prior_quizzes >= 1 else "No prior quiz results",
            present=prior_quizzes >= 1,
        ),
    ]
    score = (0.5 if completed >= 3 else 0.0) + (0.5 if prior_quizzes >= 1 else 0.0)
    return score, factors


async def _check_code_review(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    subs = await _count_exercise_submissions(db, student.id)
    factors = [
        ContextFactor(
            label=f"{subs} exercise submission(s)" if subs >= 1 else "No exercise submissions",
            present=subs >= 1,
        )
    ]
    score = 1.0 if subs >= 1 else 0.2
    return score, factors


async def _check_portfolio_builder(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    capstone_subs = await _count_exercise_submissions(db, student.id)
    has_resume = await _has_resume(db, student.id)
    factors = [
        ContextFactor(
            label=f"{capstone_subs} capstone/exercise submission(s)" if capstone_subs >= 1 else "No capstone submissions",
            present=capstone_subs >= 1,
        ),
        ContextFactor(label="Resume on file" if has_resume else "No resume on file", present=has_resume),
    ]
    score = (0.7 if capstone_subs >= 1 else 0.0) + (0.3 if has_resume else 0.0)
    return score, factors


async def _check_community_celebrator(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=7)
    recent = await _count_completions_since(db, student.id, cutoff)
    factors = [
        ContextFactor(
            label=f"{recent} lessons completed in last 7d"
            if recent >= 1
            else "No completions in last 7d",
            present=recent >= 1,
        )
    ]
    score = 1.0 if recent >= 1 else 0.4
    return score, factors


async def _check_project_evaluator(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    submitted = await _count_exercise_submissions(db, student.id, status_filter="submitted")
    factors = [
        ContextFactor(
            label=f"{submitted} submitted exercise(s)" if submitted >= 1 else "No submitted exercises",
            present=submitted >= 1,
        )
    ]
    score = 1.0 if submitted >= 1 else 0.0
    return score, factors


async def _check_job_match(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    has_resume = await _has_resume(db, student.id)
    completed = await _count_completed_lessons(db, student.id)
    factors = [
        ContextFactor(label="Resume on file" if has_resume else "No resume on file", present=has_resume),
        ContextFactor(
            label=f"{completed} lessons completed" if completed >= 3 else f"Only {completed} lessons completed (need 3)",
            present=completed >= 3,
        ),
    ]
    score = (0.5 if has_resume else 0.0) + (0.5 if completed >= 3 else 0.0)
    return score, factors


async def _check_peer_matching(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=14)
    completed = await _count_completed_lessons(db, student.id)
    days = _days_inactive(student, now)
    active_recent = days is not None and days <= 14
    factors = [
        ContextFactor(
            label=f"{completed} lessons completed" if completed >= 3 else f"Only {completed} lessons completed (need 3)",
            present=completed >= 3,
        ),
        ContextFactor(
            label="Active in last 14d" if active_recent else "Inactive >14d (or never)",
            present=active_recent,
        ),
    ]
    _ = cutoff  # cutoff retained for parity with progress_report style
    score = (0.5 if completed >= 3 else 0.0) + (0.5 if active_recent else 0.0)
    return score, factors


async def _check_default(
    student: User, db: AsyncSession
) -> tuple[float, list[ContextFactor]]:
    has_logged_in = student.last_login_at is not None
    factors = [
        ContextFactor(
            label="No specific context check defined for this agent",
            present=False,
        ),
        ContextFactor(
            label="Student has logged in at least once"
            if has_logged_in
            else "Student has never logged in",
            present=has_logged_in,
        ),
    ]
    score = 0.5 if has_logged_in else 0.2
    return score, factors


# Dispatch dict: agent_name -> async check fn.
# Lookup with .get(name, _check_default) so unknown agents fall back gracefully.
_AGENT_READINESS_CHECKS: dict[str, Any] = {
    "cover_letter": _check_cover_letter,
    "mock_interview": _check_mock_interview,
    "progress_report": _check_progress_report,
    "disrupt_prevention": _check_disrupt_prevention,
    "socratic_tutor": _check_socratic_tutor,
    "adaptive_quiz": _check_adaptive_quiz,
    "code_review": _check_code_review,
    "coding_assistant": _check_code_review,
    "portfolio_builder": _check_portfolio_builder,
    "community_celebrator": _check_community_celebrator,
    "project_evaluator": _check_project_evaluator,
    "job_match": _check_job_match,
    "peer_matching": _check_peer_matching,
}


def _tone_for_score(score: float) -> str:
    if score >= 0.7:
        return "ready"
    if score >= 0.3:
        return "limited"
    return "not_ready"


def _build_summary(
    tone: str, factors: list[ContextFactor], last_active_text: str
) -> str:
    present_labels = [f.label for f in factors if f.present]
    missing_labels = [f.label for f in factors if not f.present]
    if tone == "ready":
        head = "Ready"
        body = ", ".join(present_labels) if present_labels else "all checks pass"
        summary = f"{head} - {body}, {last_active_text}"
    elif tone == "limited":
        head = "Limited"
        parts = []
        if present_labels:
            parts.append("has " + ", ".join(present_labels))
        if missing_labels:
            parts.append("missing " + ", ".join(missing_labels))
        body = "; ".join(parts) if parts else "partial context"
        summary = f"{head} - {body}, {last_active_text}"
    else:
        body = ", ".join(missing_labels) if missing_labels else "insufficient context"
        summary = f"Not ready - Missing: {body}"
    if len(summary) > 120:
        summary = summary[:117] + "..."
    return summary


@router.get(
    "/agents/{agent_name}/context-preview",
    response_model=ContextPreviewResponse,
)
async def get_agent_context_preview(
    agent_name: str,
    student_id: uuid.UUID = Query(..., description="Target student UUID"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> ContextPreviewResponse:
    """Preview a student's readiness for an agent before admin triggers it.

    Returns a 0-1 readiness score, traffic-light tone (ready / limited /
    not_ready), a one-line summary, and the list of factors checked.
    Each agent has a domain-specific factor set; unknown agents fall back
    to a generic "has the student ever logged in?" check.
    """
    student = (
        await db.execute(select(User).where(User.id == student_id))
    ).scalar_one_or_none()
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    check = _AGENT_READINESS_CHECKS.get(agent_name, _check_default)
    score, factors = await check(student, db)
    # Clamp to [0, 1] for safety.
    score = max(0.0, min(1.0, float(score)))
    tone = _tone_for_score(score)
    now = datetime.now(UTC)
    last_active_text = _last_active_phrase(student.last_login_at, now)
    summary = _build_summary(tone, factors, last_active_text)

    log.info(
        "admin.agent_context_preview_viewed",
        agent_name=agent_name,
        student_id=str(student_id),
        score=score,
        tone=tone,
    )

    return ContextPreviewResponse(
        agent_name=agent_name,
        student_id=str(student_id),
        readiness_score=round(score, 3),
        tone=tone,
        summary=summary,
        factors=factors,
        student_name=student.full_name,
        student_email=student.email,
        generated_at=now,
    )


# ── Agent task templates ─────────────────────────────────────────────────────


class TaskTemplateRead(PydanticModel):
    id: str
    agent_name: str
    label: str
    body: str
    is_built_in: bool
    sort_order: int
    created_by_admin_id: str | None
    created_at: datetime
    updated_at: datetime


class TaskTemplateCreate(PydanticModel):
    agent_name: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1)
    sort_order: int = 100  # admin-created defaults after seeds


class TaskTemplateUpdate(PydanticModel):
    label: str | None = None
    body: str | None = None
    sort_order: int | None = None


def _template_to_read(t: Any) -> TaskTemplateRead:
    return TaskTemplateRead(
        id=str(t.id),
        agent_name=t.agent_name,
        label=t.label,
        body=t.body,
        is_built_in=t.is_built_in,
        sort_order=t.sort_order,
        created_by_admin_id=str(t.created_by_admin_id) if t.created_by_admin_id else None,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get("/agents/{agent_name}/templates", response_model=list[TaskTemplateRead])
async def list_agent_templates(
    agent_name: str,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> list[TaskTemplateRead]:
    """List task templates for a given agent, sorted by (sort_order asc, label asc)."""
    from app.models.agent_task_template import AgentTaskTemplate

    result = await db.execute(
        select(AgentTaskTemplate)
        .where(AgentTaskTemplate.agent_name == agent_name)
        .order_by(AgentTaskTemplate.sort_order.asc(), AgentTaskTemplate.label.asc())
    )
    rows = result.scalars().all()
    return [_template_to_read(t) for t in rows]


@router.post(
    "/agents/templates",
    response_model=TaskTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_template(
    payload: TaskTemplateCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> TaskTemplateRead:
    """Admin creates a new (non-built-in) task template."""
    from app.models.agent_task_template import AgentTaskTemplate

    template = AgentTaskTemplate(
        agent_name=payload.agent_name,
        label=payload.label,
        body=payload.body,
        sort_order=payload.sort_order,
        is_built_in=False,
        created_by_admin_id=admin_user.id,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)

    try:
        from app.services.admin_audit_service import AdminAuditService

        await AdminAuditService.log(
            db=db,
            admin=admin_user,
            action_type="agent.template_create",
            resource_type="agent_template",
            resource_id=str(template.id),
            before=None,
            after={
                "agent_name": template.agent_name,
                "label": template.label,
                "sort_order": template.sort_order,
            },
            metadata={"agent_name": template.agent_name},
            request=request,
        )
        await db.commit()
    except Exception:
        pass

    await db.refresh(template)
    log.info(
        "admin.agent_template.created",
        template_id=str(template.id),
        agent_name=template.agent_name,
        admin_email=admin_user.email,
    )
    return _template_to_read(template)


@router.patch("/agents/templates/{template_id}", response_model=TaskTemplateRead)
async def update_agent_template(
    template_id: uuid.UUID,
    payload: TaskTemplateUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> TaskTemplateRead:
    """Partial update of a (non-built-in) task template."""
    from app.models.agent_task_template import AgentTaskTemplate

    result = await db.execute(
        select(AgentTaskTemplate).where(AgentTaskTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if template.is_built_in:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Built-in templates are read-only",
        )

    before = {
        "label": template.label,
        "body": template.body,
        "sort_order": template.sort_order,
    }
    if payload.label is not None:
        template.label = payload.label
    if payload.body is not None:
        template.body = payload.body
    if payload.sort_order is not None:
        template.sort_order = payload.sort_order
    await db.flush()
    await db.refresh(template)

    try:
        from app.services.admin_audit_service import AdminAuditService

        await AdminAuditService.log(
            db=db,
            admin=admin_user,
            action_type="agent.template_update",
            resource_type="agent_template",
            resource_id=str(template.id),
            before=before,
            after={
                "label": template.label,
                "body": template.body,
                "sort_order": template.sort_order,
            },
            metadata={"agent_name": template.agent_name},
            request=request,
        )
        await db.commit()
    except Exception:
        pass

    await db.refresh(template)
    log.info(
        "admin.agent_template.updated",
        template_id=str(template.id),
        admin_email=admin_user.email,
    )
    return _template_to_read(template)


@router.delete(
    "/agents/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_agent_template(
    template_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> None:
    """Delete a (non-built-in) task template."""
    from app.models.agent_task_template import AgentTaskTemplate

    result = await db.execute(
        select(AgentTaskTemplate).where(AgentTaskTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if template.is_built_in:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Built-in templates are read-only",
        )

    before = {
        "agent_name": template.agent_name,
        "label": template.label,
        "body": template.body,
        "sort_order": template.sort_order,
    }
    agent_name = template.agent_name
    await db.delete(template)
    await db.flush()

    try:
        from app.services.admin_audit_service import AdminAuditService

        await AdminAuditService.log(
            db=db,
            admin=admin_user,
            action_type="agent.template_delete",
            resource_type="agent_template",
            resource_id=str(template_id),
            before=before,
            after=None,
            metadata={"agent_name": agent_name},
            request=request,
        )
        await db.commit()
    except Exception:
        pass

    log.info(
        "admin.agent_template.deleted",
        template_id=str(template_id),
        admin_email=admin_user.email,
    )


# ── Send agent output to student via outreach ────────────────────────────────
#
# Wraps the existing outreach_service.record() pipeline so an admin can,
# from the agents page, dispatch an agent's response to the target student
# over WhatsApp / Email / In-app. Two entry points:
#
#   • POST /admin/agents/actions/{action_id}/send   — explicit, after-review
#   • The auto_send_channel field on /agents/{name}/trigger/v2 — one-shot
#
# Both paths funnel through `_send_agent_output_internal` so the audit
# trail and outreach_log shape are identical regardless of caller.


# Channels we accept on the agent-send wrapper. Superset of the manual
# outreach endpoint's whitelist (which is whatsapp/phone only) because
# admins triggering agents want to also reach students via email and the
# in-app message stream. We deliberately do NOT include "phone" here —
# that channel is for after-the-fact call logging, not agent dispatch.
_ALLOWED_AGENT_SEND_CHANNELS = {"whatsapp", "email", "in_app"}


class SendAgentOutputRequest(PydanticModel):
    channel: str = Field(min_length=1, max_length=32)
    body_override: str | None = None
    # Optional safety check: caller can pin the expected target student.
    # If it doesn't match the agent_action's on_behalf_of we reject 400.
    student_id: str | None = None


class SendAgentOutputResponse(PydanticModel):
    outreach_id: str
    action_id: str
    channel: str
    student_id: str
    sent_at: datetime
    body_preview: str  # first 200 chars of what was sent


def _extract_agent_output_body(action: AgentAction) -> str:
    """Pull the best-available admin-facing text from an agent_action row.

    Preference order matches what agents put on AgentState.response /
    output_data — most agents serialize the final reply under "output",
    some legacy paths use "response" / "answer" / "text". We fall back to
    a stringified dump so the send still goes through even if the agent
    produced an unusual shape; the audit log captures the preview for
    forensic review.
    """
    data = action.output_data or {}
    if isinstance(data, dict):
        for key in ("output", "response", "answer", "text"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val
    if data:
        return str(data)[:4000]
    return ""


async def _send_agent_output_internal(
    *,
    db: AsyncSession,
    request: Request,
    admin: User,
    action_id: uuid.UUID,
    channel: str,
    body_override: str | None,
    student_id_check: uuid.UUID | None,
) -> SendAgentOutputResponse:
    """Core send logic shared by the explicit endpoint and trigger/v2
    auto-send. Raises HTTPException on validation errors; never swallows
    them so the v2 caller can decide whether a failed send should null
    out auto_send_outreach_id (it does) or surface the error (it logs).
    """
    from app.services import outreach_service

    channel_norm = channel.lower().strip()
    if channel_norm not in _ALLOWED_AGENT_SEND_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"channel must be one of {sorted(_ALLOWED_AGENT_SEND_CHANNELS)} "
                f"(got '{channel}')"
            ),
        )

    action = await db.get(AgentAction, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="agent_action not found")

    # Admin-triggered runs put the target student on on_behalf_of; legacy
    # student-self runs put it on student_id. Try on_behalf_of first so
    # admin-triggered flows resolve cleanly.
    target_uuid: uuid.UUID | None = action.on_behalf_of or action.student_id
    if target_uuid is None:
        raise HTTPException(
            status_code=400,
            detail="agent_action has no associated student (on_behalf_of/student_id both null)",
        )

    if student_id_check is not None and student_id_check != target_uuid:
        raise HTTPException(
            status_code=400,
            detail="student_id mismatch with agent action",
        )

    student = await _require_student(db, target_uuid)

    body = body_override if (body_override and body_override.strip()) else _extract_agent_output_body(action)
    if not body:
        raise HTTPException(
            status_code=400,
            detail="agent_action has no output to send and no body_override provided",
        )

    entry = await outreach_service.record(
        db,
        user_id=student.id,
        channel=channel_norm,
        template_key=None,
        slip_type=None,
        # triggered_by tags the outreach_log row as originating from an
        # admin-driven agent trigger. The outreach_log model has no JSON
        # metadata column, so the agent_action_id link lives in the
        # AdminAuditLog row below — that's the join path for tracing.
        triggered_by="agent_trigger",
        triggered_by_user_id=admin.id,
        body_preview=body,
        status="sent",
    )

    body_preview = (body or "")[:200]

    try:
        await AdminAuditService.log(
            db=db,
            admin=admin,
            action_type="outreach.send_from_agent",
            resource_type="outreach",
            resource_id=str(entry.id),
            metadata={
                "channel": channel_norm,
                "agent_name": action.agent_name,
                "agent_action_id": str(action.id),
                "student_id": str(student.id),
                "body_preview": body_preview,
            },
            request=request,
        )
        await db.commit()
    except Exception:
        log.exception(
            "admin.outreach.send_from_agent.audit_failed",
            action_id=str(action.id),
            outreach_id=str(entry.id),
        )

    log.info(
        "admin.outreach.send_from_agent",
        admin_id=str(admin.id),
        student_id=str(student.id),
        channel=channel_norm,
        agent_name=action.agent_name,
        agent_action_id=str(action.id),
        outreach_id=str(entry.id),
    )

    return SendAgentOutputResponse(
        outreach_id=str(entry.id),
        action_id=str(action.id),
        channel=channel_norm,
        student_id=str(student.id),
        sent_at=entry.sent_at,
        body_preview=body_preview,
    )


@router.post(
    "/agents/actions/{action_id}/send",
    response_model=SendAgentOutputResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_agent_output_to_student(
    action_id: uuid.UUID,
    payload: SendAgentOutputRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> SendAgentOutputResponse:
    """Dispatch an agent's output to the student it was run for.

    Looks up agent_actions by action_id, resolves the target student
    (on_behalf_of, falling back to student_id), optionally honours a
    body_override so the admin can tweak the agent's wording before
    sending, and routes through outreach_service.record() so the
    outreach_log audit trail matches every other admin-driven send.
    """
    student_id_check: uuid.UUID | None = None
    if payload.student_id:
        try:
            student_id_check = uuid.UUID(payload.student_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Invalid student_id"
            ) from exc

    return await _send_agent_output_internal(
        db=db,
        request=request,
        admin=admin,
        action_id=action_id,
        channel=payload.channel,
        body_override=payload.body_override,
        student_id_check=student_id_check,
    )


# =============================================================================
# ── B3-C: MCQ bank CRUD (deep course edit) ───────────────────────────────────
# =============================================================================


class AdminMCQRead(PydanticModel):
    id: str
    lesson_id: str | None
    question: str
    options: dict
    correct_answer: str
    explanation: str | None
    difficulty: str
    tags: list[str] | None
    source: str
    created_at: datetime
    updated_at: datetime


class AdminMCQsListResponse(PydanticModel):
    items: list[AdminMCQRead]
    total: int


class AdminMCQCreate(PydanticModel):
    question: str = Field(min_length=1)
    options: dict[str, str]
    correct_answer: str = Field(min_length=1, max_length=10)
    explanation: str | None = None
    difficulty: str = "medium"
    tags: list[str] | None = None
    source: str = "admin_authored"


class AdminMCQUpdate(PydanticModel):
    question: str | None = None
    options: dict[str, str] | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    difficulty: str | None = None
    tags: list[str] | None = None
    source: str | None = None
    lesson_id: str | None = None


class CourseMCQSummaryResponse(PydanticModel):
    counts: dict[str, int]
    total: int


def _normalize_mcq_options(raw: Any) -> dict[str, str]:
    """Defensive read for legacy MCQ option shapes.

    Legacy rows may store options as a list like ``["A) foo", "B) bar"]``
    instead of a ``{"A": "foo", ...}`` dict. Normalize on the way out so the
    admin UI sees a consistent shape. ``None`` becomes ``{}``.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        normalized: dict[str, str] = {}
        for idx, item in enumerate(raw):
            text = str(item)
            # try to parse "A) foo" / "A. foo" / "A: foo" leading-letter form
            key: str | None = None
            body = text
            if len(text) >= 2 and text[0].isalpha() and text[1] in (")", ".", ":"):
                key = text[0].upper()
                body = text[2:].lstrip()
            if key is None:
                key = chr(ord("A") + idx) if idx < 26 else str(idx)
            normalized[key] = body
        return normalized
    return {}


def _mcq_to_read(mcq: Any) -> AdminMCQRead:
    return AdminMCQRead(
        id=str(mcq.id),
        lesson_id=str(mcq.lesson_id) if mcq.lesson_id else None,
        question=mcq.question,
        options=_normalize_mcq_options(mcq.options),
        correct_answer=mcq.correct_answer,
        explanation=mcq.explanation,
        difficulty=mcq.difficulty,
        tags=list(mcq.tags) if mcq.tags else [],
        source=mcq.source,
        created_at=mcq.created_at,
        updated_at=mcq.updated_at,
    )


@router.get("/lessons/{lesson_id}/mcqs", response_model=AdminMCQsListResponse)
async def list_lesson_mcqs(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> AdminMCQsListResponse:
    """List all non-deleted MCQs for a lesson, oldest first."""
    from app.models.mcq_bank import MCQBank

    stmt = (
        select(MCQBank)
        .where(MCQBank.lesson_id == lesson_id)
        .where(MCQBank.is_deleted.is_(False))
        .order_by(MCQBank.created_at.asc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    items = [_mcq_to_read(r) for r in rows]
    log.info("admin.mcqs_listed", lesson_id=str(lesson_id), count=len(items))
    return AdminMCQsListResponse(items=items, total=len(items))


@router.post("/lessons/{lesson_id}/mcqs", response_model=AdminMCQRead, status_code=201)
async def create_lesson_mcq(
    lesson_id: uuid.UUID,
    body: AdminMCQCreate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> AdminMCQRead:
    """Create a new MCQ attached to a lesson."""
    from app.models.lesson import Lesson
    from app.models.mcq_bank import MCQBank

    lesson_res = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    if not lesson_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="lesson not found")

    if len(body.options) < 2:
        raise HTTPException(
            status_code=400, detail="MCQ requires at least 2 options"
        )
    if body.correct_answer not in body.options:
        raise HTTPException(
            status_code=400,
            detail="correct_answer must be a key in options",
        )

    mcq = MCQBank(
        lesson_id=lesson_id,
        question=body.question,
        options=body.options,
        correct_answer=body.correct_answer,
        explanation=body.explanation,
        difficulty=body.difficulty,
        tags=body.tags,
        source=body.source,
    )
    db.add(mcq)
    await db.commit()
    await db.refresh(mcq)

    log.info("admin.mcq_created", mcq_id=str(mcq.id), lesson_id=str(lesson_id))
    await _audit(
        db,
        admin_user=admin_user,
        action_type="mcq.create",
        target_type="mcq",
        target_id=str(mcq.id),
        after={
            "lesson_id": str(lesson_id),
            "question": mcq.question,
            "options": mcq.options,
            "correct_answer": mcq.correct_answer,
            "difficulty": mcq.difficulty,
            "source": mcq.source,
        },
    )
    return _mcq_to_read(mcq)


@router.patch("/mcqs/{mcq_id}", response_model=AdminMCQRead)
async def update_mcq(
    mcq_id: uuid.UUID,
    body: AdminMCQUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> AdminMCQRead:
    """Partial update — only fields present in the request body are touched."""
    from app.models.mcq_bank import MCQBank

    result = await db.execute(
        select(MCQBank)
        .where(MCQBank.id == mcq_id)
        .where(MCQBank.is_deleted.is_(False))
    )
    mcq = result.scalar_one_or_none()
    if not mcq:
        raise HTTPException(status_code=404, detail="mcq not found")

    fields_set = body.model_fields_set

    # Resolve effective options + correct_answer for cross-field validation.
    new_options = body.options if "options" in fields_set else mcq.options
    new_correct = (
        body.correct_answer if "correct_answer" in fields_set else mcq.correct_answer
    )
    if "options" in fields_set or "correct_answer" in fields_set:
        if not isinstance(new_options, dict) or len(new_options) < 2:
            raise HTTPException(
                status_code=400, detail="MCQ requires at least 2 options"
            )
        if new_correct not in new_options:
            raise HTTPException(
                status_code=400,
                detail="correct_answer must be a key in options",
            )

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}

    def _track(field: str, new_val: Any) -> None:
        cur = getattr(mcq, field)
        if cur != new_val:
            before[field] = str(cur) if isinstance(cur, uuid.UUID) else cur
            after[field] = str(new_val) if isinstance(new_val, uuid.UUID) else new_val

    if "question" in fields_set:
        _track("question", body.question)
        mcq.question = body.question  # type: ignore[assignment]
    if "options" in fields_set:
        _track("options", body.options)
        mcq.options = body.options  # type: ignore[assignment]
    if "correct_answer" in fields_set:
        _track("correct_answer", body.correct_answer)
        mcq.correct_answer = body.correct_answer  # type: ignore[assignment]
    if "explanation" in fields_set:
        _track("explanation", body.explanation)
        mcq.explanation = body.explanation
    if "difficulty" in fields_set:
        _track("difficulty", body.difficulty)
        mcq.difficulty = body.difficulty  # type: ignore[assignment]
    if "tags" in fields_set:
        _track("tags", body.tags)
        mcq.tags = body.tags
    if "source" in fields_set:
        _track("source", body.source)
        mcq.source = body.source  # type: ignore[assignment]
    if "lesson_id" in fields_set:
        new_lesson_id = uuid.UUID(body.lesson_id) if body.lesson_id else None
        _track("lesson_id", new_lesson_id)
        mcq.lesson_id = new_lesson_id

    await db.commit()
    await db.refresh(mcq)

    log.info("admin.mcq_updated", mcq_id=str(mcq_id), fields=list(after.keys()))
    if after:
        await _audit(
            db,
            admin_user=admin_user,
            action_type="mcq.update",
            target_type="mcq",
            target_id=str(mcq_id),
            before=before,
            after=after,
        )
    return _mcq_to_read(mcq)


@router.delete("/mcqs/{mcq_id}", status_code=204)
async def delete_mcq(
    mcq_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> None:
    """Soft delete — sets is_deleted=True; row is preserved for audit."""
    from app.models.mcq_bank import MCQBank

    result = await db.execute(
        select(MCQBank)
        .where(MCQBank.id == mcq_id)
        .where(MCQBank.is_deleted.is_(False))
    )
    mcq = result.scalar_one_or_none()
    if not mcq:
        raise HTTPException(status_code=404, detail="mcq not found")

    snapshot = {
        "lesson_id": str(mcq.lesson_id) if mcq.lesson_id else None,
        "question": mcq.question,
        "correct_answer": mcq.correct_answer,
        "difficulty": mcq.difficulty,
    }
    mcq.is_deleted = True
    await db.commit()

    log.info("admin.mcq_deleted", mcq_id=str(mcq_id))
    await _audit(
        db,
        admin_user=admin_user,
        action_type="mcq.delete",
        target_type="mcq",
        target_id=str(mcq_id),
        before=snapshot,
    )


@router.get("/courses/{course_id}/mcq-summary", response_model=CourseMCQSummaryResponse)
async def get_course_mcq_summary(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> CourseMCQSummaryResponse:
    """Per-lesson MCQ counts for a course — powers "N MCQs" badges in the UI."""
    from app.models.lesson import Lesson
    from app.models.mcq_bank import MCQBank

    stmt = (
        select(MCQBank.lesson_id, func.count(MCQBank.id))
        .join(Lesson, Lesson.id == MCQBank.lesson_id)
        .where(Lesson.course_id == course_id)
        .where(MCQBank.is_deleted.is_(False))
        .group_by(MCQBank.lesson_id)
    )
    result = await db.execute(stmt)
    counts: dict[str, int] = {}
    total = 0
    for lesson_id, count in result.all():
        if lesson_id is None:
            continue
        counts[str(lesson_id)] = int(count)
        total += int(count)
    log.info(
        "admin.course_mcq_summary",
        course_id=str(course_id),
        lessons_with_mcqs=len(counts),
        total=total,
    )
    return CourseMCQSummaryResponse(counts=counts, total=total)


# =============================================================================
# ── B3-A: Lessons CRUD + reorder (deep course edit) ────────────────────────────
# =============================================================================


class AdminLessonRead(PydanticModel):
    id: str
    course_id: str
    title: str
    slug: str
    description: str | None
    content: str | None
    video_url: str | None
    youtube_video_id: str | None
    duration_seconds: int
    order: int
    is_published: bool
    is_free_preview: bool
    github_branch: str | None
    exercise_count: int
    mcq_count: int
    created_at: datetime
    updated_at: datetime


class AdminLessonsListResponse(PydanticModel):
    items: list[AdminLessonRead]


class AdminLessonCreate(PydanticModel):
    title: str = Field(min_length=1, max_length=500)
    slug: str | None = Field(default=None, max_length=500)
    description: str | None = None
    content: str | None = None
    video_url: str | None = Field(default=None, max_length=500)
    youtube_video_id: str | None = Field(default=None, max_length=100)
    duration_seconds: int = 0
    is_published: bool = False
    is_free_preview: bool = False
    github_branch: str | None = None


class AdminLessonUpdate(PydanticModel):
    title: str | None = None
    slug: str | None = None
    description: str | None = None
    content: str | None = None
    video_url: str | None = None
    youtube_video_id: str | None = None
    duration_seconds: int | None = None
    is_published: bool | None = None
    is_free_preview: bool | None = None
    github_branch: str | None = None


class LessonReorderRequest(PydanticModel):
    lesson_ids: list[str]


def _serialize_admin_lesson(
    lesson: Any, exercise_count: int, mcq_count: int
) -> AdminLessonRead:
    return AdminLessonRead(
        id=str(lesson.id),
        course_id=str(lesson.course_id),
        title=lesson.title,
        slug=lesson.slug,
        description=lesson.description,
        content=lesson.content,
        video_url=lesson.video_url,
        youtube_video_id=lesson.youtube_video_id,
        duration_seconds=lesson.duration_seconds or 0,
        order=lesson.order or 0,
        is_published=bool(lesson.is_published),
        is_free_preview=bool(lesson.is_free_preview),
        github_branch=lesson.github_branch,
        exercise_count=exercise_count,
        mcq_count=mcq_count,
        created_at=lesson.created_at,
        updated_at=lesson.updated_at,
    )


async def _load_lessons_with_counts(
    db: AsyncSession, course_id: uuid.UUID
) -> list[AdminLessonRead]:
    from app.models.course import Course  # noqa: F401
    from app.models.exercise import Exercise
    from app.models.lesson import Lesson
    from app.models.mcq_bank import MCQBank

    lessons_result = await db.execute(
        select(Lesson)
        .where(Lesson.course_id == course_id, Lesson.is_deleted.is_(False))
        .order_by(Lesson.order.asc())
    )
    lessons = lessons_result.scalars().all()
    if not lessons:
        return []

    lesson_ids = [lesson.id for lesson in lessons]

    ex_rows = (
        await db.execute(
            select(Exercise.lesson_id, func.count(Exercise.id))
            .where(
                Exercise.lesson_id.in_(lesson_ids),
                Exercise.is_deleted.is_(False),
            )
            .group_by(Exercise.lesson_id)
        )
    ).all()
    ex_map = {row[0]: row[1] for row in ex_rows}

    mcq_rows = (
        await db.execute(
            select(MCQBank.lesson_id, func.count(MCQBank.id))
            .where(
                MCQBank.lesson_id.in_(lesson_ids),
                MCQBank.is_deleted.is_(False),
            )
            .group_by(MCQBank.lesson_id)
        )
    ).all()
    mcq_map = {row[0]: row[1] for row in mcq_rows}

    return [
        _serialize_admin_lesson(
            lesson,
            exercise_count=int(ex_map.get(lesson.id, 0)),
            mcq_count=int(mcq_map.get(lesson.id, 0)),
        )
        for lesson in lessons
    ]


async def _get_lesson_counts(db: AsyncSession, lesson_id: uuid.UUID) -> tuple[int, int]:
    from app.models.exercise import Exercise
    from app.models.mcq_bank import MCQBank

    ex_count = (
        await db.execute(
            select(func.count(Exercise.id)).where(
                Exercise.lesson_id == lesson_id,
                Exercise.is_deleted.is_(False),
            )
        )
    ).scalar_one()
    mcq_count = (
        await db.execute(
            select(func.count(MCQBank.id)).where(
                MCQBank.lesson_id == lesson_id,
                MCQBank.is_deleted.is_(False),
            )
        )
    ).scalar_one()
    return int(ex_count or 0), int(mcq_count or 0)


@router.get("/courses/{course_id}/lessons", response_model=AdminLessonsListResponse)
async def admin_list_course_lessons(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> AdminLessonsListResponse:
    from app.models.course import Course

    try:
        course_uuid = uuid.UUID(course_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid course_id") from exc

    course = (
        await db.execute(
            select(Course).where(Course.id == course_uuid, Course.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    items = await _load_lessons_with_counts(db, course_uuid)
    return AdminLessonsListResponse(items=items)


@router.post(
    "/courses/{course_id}/lessons",
    response_model=AdminLessonRead,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_lesson(
    course_id: str,
    payload: AdminLessonCreate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> AdminLessonRead:
    from app.models.course import Course
    from app.models.lesson import Lesson

    try:
        course_uuid = uuid.UUID(course_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid course_id") from exc

    course = (
        await db.execute(
            select(Course).where(Course.id == course_uuid, Course.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    max_order = (
        await db.execute(
            select(func.max(Lesson.order)).where(
                Lesson.course_id == course_uuid, Lesson.is_deleted.is_(False)
            )
        )
    ).scalar()
    next_order = (int(max_order) + 1) if max_order is not None else 0

    slug = (payload.slug or "").strip()
    if not slug:
        import re

        slug = re.sub(r"[^a-z0-9]+", "-", payload.title.lower()).strip("-")[:120] or "lesson"

    lesson = Lesson(
        course_id=course_uuid,
        title=payload.title,
        slug=slug,
        description=payload.description,
        content=payload.content,
        video_url=payload.video_url,
        youtube_video_id=payload.youtube_video_id,
        duration_seconds=payload.duration_seconds,
        order=next_order,
        is_published=payload.is_published,
        is_free_preview=payload.is_free_preview,
        github_branch=payload.github_branch,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)

    log.info(
        "admin.lesson.create",
        admin_id=str(admin_user.id),
        course_id=str(course_uuid),
        lesson_id=str(lesson.id),
    )

    try:
        await AdminAuditService.log(
            db=db,
            admin=admin_user,
            action_type="lesson.create",
            resource_type="lesson",
            resource_id=str(lesson.id),
            before=None,
            after={
                "title": lesson.title,
                "slug": lesson.slug,
                "order": lesson.order,
                "is_published": lesson.is_published,
            },
            metadata={"course_id": str(course_uuid)},
        )
        await db.commit()
    except Exception:
        pass

    return _serialize_admin_lesson(lesson, exercise_count=0, mcq_count=0)


@router.patch("/lessons/{lesson_id}", response_model=AdminLessonRead)
async def admin_update_lesson(
    lesson_id: str,
    payload: AdminLessonUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> AdminLessonRead:
    from app.models.lesson import Lesson

    try:
        lesson_uuid = uuid.UUID(lesson_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid lesson_id") from exc

    lesson = (
        await db.execute(
            select(Lesson).where(Lesson.id == lesson_uuid, Lesson.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    update_fields = payload.model_dump(exclude_unset=True)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for key, new_value in update_fields.items():
        old_value = getattr(lesson, key)
        if old_value != new_value:
            before[key] = old_value
            after[key] = new_value
            setattr(lesson, key, new_value)

    await db.commit()
    await db.refresh(lesson)

    log.info(
        "admin.lesson.update",
        admin_id=str(admin_user.id),
        lesson_id=str(lesson.id),
        changed=list(after.keys()),
    )

    try:
        await AdminAuditService.log(
            db=db,
            admin=admin_user,
            action_type="lesson.update",
            resource_type="lesson",
            resource_id=str(lesson.id),
            before=before,
            after=after,
            metadata={"course_id": str(lesson.course_id)},
        )
        await db.commit()
    except Exception:
        pass

    ex_count, mcq_count = await _get_lesson_counts(db, lesson.id)
    return _serialize_admin_lesson(lesson, exercise_count=ex_count, mcq_count=mcq_count)


@router.delete("/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_lesson(
    lesson_id: str,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> None:
    from app.models.lesson import Lesson

    try:
        lesson_uuid = uuid.UUID(lesson_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid lesson_id") from exc

    lesson = (
        await db.execute(
            select(Lesson).where(Lesson.id == lesson_uuid, Lesson.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    lesson.is_deleted = True
    await db.commit()

    log.info(
        "admin.lesson.delete",
        admin_id=str(admin_user.id),
        lesson_id=str(lesson_uuid),
    )

    try:
        await AdminAuditService.log(
            db=db,
            admin=admin_user,
            action_type="lesson.delete",
            resource_type="lesson",
            resource_id=str(lesson_uuid),
            before={"title": lesson.title, "slug": lesson.slug},
            after=None,
            metadata={"course_id": str(lesson.course_id)},
        )
        await db.commit()
    except Exception:
        pass

    return None


@router.post(
    "/courses/{course_id}/lessons/reorder",
    response_model=AdminLessonsListResponse,
)
async def admin_reorder_lessons(
    course_id: str,
    payload: LessonReorderRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> AdminLessonsListResponse:
    from app.models.course import Course
    from app.models.lesson import Lesson

    try:
        course_uuid = uuid.UUID(course_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid course_id") from exc

    course = (
        await db.execute(
            select(Course).where(Course.id == course_uuid, Course.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        lesson_uuids = [uuid.UUID(lid) for lid in payload.lesson_ids]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid lesson_id in list") from exc

    if not lesson_uuids:
        raise HTTPException(status_code=400, detail="lesson_ids must not be empty")

    lessons = (
        (
            await db.execute(
                select(Lesson).where(
                    Lesson.id.in_(lesson_uuids), Lesson.is_deleted.is_(False)
                )
            )
        )
        .scalars()
        .all()
    )

    if len(lessons) != len(lesson_uuids):
        raise HTTPException(
            status_code=400, detail="One or more lessons not found"
        )
    for lesson in lessons:
        if lesson.course_id != course_uuid:
            raise HTTPException(
                status_code=400,
                detail="All lessons must belong to the specified course",
            )

    lesson_by_id = {lesson.id: lesson for lesson in lessons}
    for index, lid in enumerate(lesson_uuids):
        lesson_by_id[lid].order = index

    await db.commit()

    log.info(
        "admin.lesson.reorder",
        admin_id=str(admin_user.id),
        course_id=str(course_uuid),
        count=len(lesson_uuids),
    )

    try:
        await AdminAuditService.log(
            db=db,
            admin=admin_user,
            action_type="lesson.reorder",
            resource_type="course",
            resource_id=str(course_uuid),
            before=None,
            after=None,
            metadata={
                "course_id": str(course_uuid),
                "lesson_ids": [str(lid) for lid in lesson_uuids],
            },
        )
        await db.commit()
    except Exception:
        pass

    items = await _load_lessons_with_counts(db, course_uuid)
    return AdminLessonsListResponse(items=items)


# =============================================================================
# ── B3-B: Exercises CRUD + structured rubric (deep course edit) ──────────────
# =============================================================================


class _B3BRubricCriterion(PydanticModel):
    name: str
    weight: int = 1
    description: str | None = None


class _B3BTestCase(PydanticModel):
    name: str
    input: str
    expected_output: str
    hidden: bool = False


class AdminExerciseRead(PydanticModel):
    id: str
    lesson_id: str
    title: str
    description: str | None
    exercise_type: str
    difficulty: str
    starter_code: str | None
    solution_code: str | None
    test_cases: list[dict] | None
    rubric: dict | None
    points: int
    order: int
    is_capstone: bool
    pass_score: int
    due_at: datetime | None
    github_template_url: str | None
    submission_count: int
    created_at: datetime
    updated_at: datetime


class AdminExercisesListResponse(PydanticModel):
    items: list[AdminExerciseRead]


class AdminExerciseCreate(PydanticModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    exercise_type: str = "coding"
    difficulty: str = "medium"
    starter_code: str | None = None
    solution_code: str | None = None
    test_cases: list[_B3BTestCase] | None = None
    rubric_criteria: list[_B3BRubricCriterion] | None = None
    points: int = 100
    is_capstone: bool = False
    pass_score: int = 70
    due_at: datetime | None = None
    github_template_url: str | None = None


class AdminExerciseUpdate(PydanticModel):
    title: str | None = None
    description: str | None = None
    exercise_type: str | None = None
    difficulty: str | None = None
    starter_code: str | None = None
    solution_code: str | None = None
    test_cases: list[_B3BTestCase] | None = None
    rubric_criteria: list[_B3BRubricCriterion] | None = None
    points: int | None = None
    is_capstone: bool | None = None
    pass_score: int | None = None
    due_at: datetime | None = None
    github_template_url: str | None = None


class ExerciseReorderRequest(PydanticModel):
    exercise_ids: list[str]


def _b3b_normalize_test_cases(raw: Any) -> list[dict] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return raw
    return None


def _b3b_normalize_rubric(raw: Any) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return {"criteria": raw}
    if isinstance(raw, dict):
        return raw
    return None


def _b3b_serialize_exercise(ex: Any, submission_count: int) -> AdminExerciseRead:
    return AdminExerciseRead(
        id=str(ex.id),
        lesson_id=str(ex.lesson_id),
        title=ex.title,
        description=ex.description,
        exercise_type=ex.exercise_type,
        difficulty=ex.difficulty,
        starter_code=ex.starter_code,
        solution_code=ex.solution_code,
        test_cases=_b3b_normalize_test_cases(ex.test_cases),
        rubric=_b3b_normalize_rubric(ex.rubric),
        points=ex.points,
        order=ex.order,
        is_capstone=bool(ex.is_capstone),
        pass_score=ex.pass_score,
        due_at=ex.due_at,
        github_template_url=ex.github_template_url,
        submission_count=submission_count,
        created_at=ex.created_at,
        updated_at=ex.updated_at,
    )


@router.get(
    "/lessons/{lesson_id}/exercises",
    response_model=AdminExercisesListResponse,
)
async def b3b_list_lesson_exercises(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> AdminExercisesListResponse:
    from app.models.exercise import Exercise
    from app.models.exercise_submission import ExerciseSubmission

    stmt = (
        select(Exercise, func.count(ExerciseSubmission.id))
        .outerjoin(ExerciseSubmission, ExerciseSubmission.exercise_id == Exercise.id)
        .where(Exercise.lesson_id == lesson_id)
        .where(Exercise.is_deleted.is_(False))
        .group_by(Exercise.id)
        .order_by(Exercise.order.asc())
    )
    rows = (await db.execute(stmt)).all()
    items = [_b3b_serialize_exercise(ex, int(count or 0)) for ex, count in rows]
    return AdminExercisesListResponse(items=items)


@router.post(
    "/lessons/{lesson_id}/exercises",
    response_model=AdminExerciseRead,
    status_code=status.HTTP_201_CREATED,
)
async def b3b_create_exercise(
    lesson_id: uuid.UUID,
    body: AdminExerciseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> AdminExerciseRead:
    from app.models.exercise import Exercise
    from app.models.lesson import Lesson

    lesson = (
        await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    ).scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    max_order = (
        await db.execute(
            select(func.max(Exercise.order)).where(Exercise.lesson_id == lesson_id)
        )
    ).scalar()
    next_order = (int(max_order) + 1) if max_order is not None else 0

    test_cases_payload: list[dict] | None = (
        [tc.model_dump() for tc in body.test_cases] if body.test_cases is not None else None
    )
    rubric_payload: dict | None = (
        {"criteria": [c.model_dump() for c in body.rubric_criteria]}
        if body.rubric_criteria is not None
        else None
    )

    exercise = Exercise(
        lesson_id=lesson_id,
        title=body.title,
        description=body.description,
        exercise_type=body.exercise_type,
        difficulty=body.difficulty,
        starter_code=body.starter_code,
        solution_code=body.solution_code,
        test_cases=test_cases_payload,
        rubric=rubric_payload,
        points=body.points,
        order=next_order,
        is_capstone=body.is_capstone,
        pass_score=body.pass_score,
        due_at=body.due_at,
        github_template_url=body.github_template_url,
    )
    db.add(exercise)
    await db.flush()

    try:
        await AdminAuditService.log(
            db=db,
            admin=admin_user,
            action_type="exercise.create",
            resource_type="exercise",
            resource_id=str(exercise.id),
            before=None,
            after={
                "lesson_id": str(lesson_id),
                "title": body.title,
                "order": next_order,
            },
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("admin.exercise_create.audit_failed", error=str(exc))

    await db.commit()
    await db.refresh(exercise)
    log.info(
        "admin.exercise_created",
        exercise_id=str(exercise.id),
        lesson_id=str(lesson_id),
    )
    return _b3b_serialize_exercise(exercise, 0)


@router.patch(
    "/exercises/{exercise_id}",
    response_model=AdminExerciseRead,
)
async def b3b_update_exercise(
    exercise_id: uuid.UUID,
    body: AdminExerciseUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> AdminExerciseRead:
    from app.models.exercise import Exercise
    from app.models.exercise_submission import ExerciseSubmission

    exercise = (
        await db.execute(
            select(Exercise)
            .where(Exercise.id == exercise_id)
            .where(Exercise.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if not exercise:
        raise HTTPException(status_code=404, detail="Exercise not found")

    fields_set = body.model_fields_set
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}

    simple_fields = (
        "title",
        "description",
        "exercise_type",
        "difficulty",
        "starter_code",
        "solution_code",
        "points",
        "is_capstone",
        "pass_score",
        "due_at",
        "github_template_url",
    )
    for fname in simple_fields:
        if fname in fields_set:
            new_val = getattr(body, fname)
            before[fname] = getattr(exercise, fname)
            after[fname] = new_val
            setattr(exercise, fname, new_val)

    if "test_cases" in fields_set:
        new_tcs: list[dict] | None = (
            [tc.model_dump() for tc in body.test_cases]
            if body.test_cases is not None
            else None
        )
        before["test_cases"] = exercise.test_cases
        after["test_cases"] = new_tcs
        exercise.test_cases = new_tcs  # type: ignore[assignment]

    if "rubric_criteria" in fields_set:
        new_rubric: dict | None = (
            {"criteria": [c.model_dump() for c in body.rubric_criteria]}
            if body.rubric_criteria is not None
            else None
        )
        before["rubric"] = exercise.rubric
        after["rubric"] = new_rubric
        exercise.rubric = new_rubric  # type: ignore[assignment]

    if after:
        try:
            await AdminAuditService.log(
                db=db,
                admin=admin_user,
                action_type="exercise.update",
                resource_type="exercise",
                resource_id=str(exercise_id),
                before=before,
                after=after,
                request=request,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("admin.exercise_update.audit_failed", error=str(exc))

    await db.commit()
    await db.refresh(exercise)

    submission_count = (
        await db.execute(
            select(func.count(ExerciseSubmission.id)).where(
                ExerciseSubmission.exercise_id == exercise_id
            )
        )
    ).scalar() or 0

    log.info("admin.exercise_updated", exercise_id=str(exercise_id))
    return _b3b_serialize_exercise(exercise, int(submission_count))


@router.delete(
    "/exercises/{exercise_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def b3b_delete_exercise(
    exercise_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> None:
    from app.models.exercise import Exercise

    exercise = (
        await db.execute(
            select(Exercise)
            .where(Exercise.id == exercise_id)
            .where(Exercise.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if not exercise:
        raise HTTPException(status_code=404, detail="Exercise not found")

    exercise.is_deleted = True

    try:
        await AdminAuditService.log(
            db=db,
            admin=admin_user,
            action_type="exercise.delete",
            resource_type="exercise",
            resource_id=str(exercise_id),
            before={"is_deleted": False},
            after={"is_deleted": True},
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("admin.exercise_delete.audit_failed", error=str(exc))

    await db.commit()
    log.info("admin.exercise_deleted", exercise_id=str(exercise_id))


@router.post(
    "/lessons/{lesson_id}/exercises/reorder",
    response_model=AdminExercisesListResponse,
)
async def b3b_reorder_exercises(
    lesson_id: uuid.UUID,
    body: ExerciseReorderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(_require_admin),
) -> AdminExercisesListResponse:
    from app.models.exercise import Exercise
    from app.models.exercise_submission import ExerciseSubmission

    try:
        target_ids = [uuid.UUID(eid) for eid in body.exercise_ids]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid exercise_id in list") from exc

    if not target_ids:
        raise HTTPException(status_code=400, detail="exercise_ids must not be empty")

    rows = (
        await db.execute(
            select(Exercise)
            .where(Exercise.id.in_(target_ids))
            .where(Exercise.is_deleted.is_(False))
        )
    ).scalars().all()

    by_id = {ex.id: ex for ex in rows}
    if len(by_id) != len(target_ids):
        raise HTTPException(status_code=404, detail="One or more exercises not found")

    for ex in rows:
        if ex.lesson_id != lesson_id:
            raise HTTPException(
                status_code=400,
                detail="All exercises must belong to the given lesson",
            )

    before_order = {str(ex.id): ex.order for ex in rows}
    for index, target_id in enumerate(target_ids):
        by_id[target_id].order = index

    try:
        await AdminAuditService.log(
            db=db,
            admin=admin_user,
            action_type="exercise.reorder",
            resource_type="exercise",
            resource_id=str(lesson_id),
            before=before_order,
            after={str(eid): idx for idx, eid in enumerate(body.exercise_ids)},
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("admin.exercise_reorder.audit_failed", error=str(exc))

    await db.commit()

    stmt = (
        select(Exercise, func.count(ExerciseSubmission.id))
        .outerjoin(ExerciseSubmission, ExerciseSubmission.exercise_id == Exercise.id)
        .where(Exercise.lesson_id == lesson_id)
        .where(Exercise.is_deleted.is_(False))
        .group_by(Exercise.id)
        .order_by(Exercise.order.asc())
    )
    result_rows = (await db.execute(stmt)).all()
    items = [_b3b_serialize_exercise(ex, int(count or 0)) for ex, count in result_rows]
    log.info("admin.exercises_reordered", lesson_id=str(lesson_id), count=len(items))
    return AdminExercisesListResponse(items=items)


# =============================================================================
# ── B3-D: Per-course analytics (deep course edit) ────────────────────────────
# =============================================================================


class CourseAnalyticsTopStudent(PydanticModel):
    student_id: str
    name: str
    email: str | None
    progress_pct: float
    completed_at: datetime | None
    last_active_at: datetime | None


class CourseAnalyticsFeedback(PydanticModel):
    id: str
    route: str
    body: str
    category: str | None
    sentiment: str | None
    severity: str | None
    resolved: bool
    created_at: datetime
    student_name: str | None


class CourseAnalyticsActivity(PydanticModel):
    action_id: str
    agent_name: str
    student_id: str | None
    student_name: str | None
    input_preview: str
    output_preview: str
    evaluation_score: float | None
    has_error: bool
    created_at: datetime


class CourseAnalyticsResponse(PydanticModel):
    course_id: str
    title: str
    slug: str
    enrolled_count: int
    completion_count: int
    completion_rate: float
    avg_progress_pct: float
    avg_confusion_rate: float
    lesson_count: int
    exercise_count: int
    mcq_count: int
    top_students: list[CourseAnalyticsTopStudent]
    recent_feedback: list[CourseAnalyticsFeedback]
    recent_agent_activity: list[CourseAnalyticsActivity]
    enrollments_last_30d: int
    enrollments_prior_30d: int
    enrollments_delta_pct: float
    generated_at: datetime


@router.get(
    "/courses/{course_id}/analytics",
    response_model=CourseAnalyticsResponse,
)
async def get_course_analytics(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> CourseAnalyticsResponse:
    """Per-course analytics for the admin deep course edit Analytics tab."""
    from app.models.course import Course
    from app.models.enrollment import Enrollment
    from app.models.exercise import Exercise
    from app.models.feedback import Feedback
    from app.models.lesson import Lesson
    from app.models.mcq_bank import MCQBank

    try:
        course_uuid = uuid.UUID(course_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    now = datetime.now(UTC)

    course = (
        await db.execute(
            select(Course).where(Course.id == course_uuid, Course.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    cid_str = str(course.id)
    slug_needle = (course.slug or "").lower()
    id_needle = cid_str.lower()

    lesson_rows = (
        await db.execute(
            select(Lesson.id).where(
                Lesson.course_id == course_uuid, Lesson.is_deleted.is_(False)
            )
        )
    ).all()
    lesson_ids = [lid for (lid,) in lesson_rows]
    lesson_count = len(lesson_ids)

    exercise_count = 0
    mcq_count = 0
    if lesson_ids:
        ex_count_row = (
            await db.execute(
                select(func.count(Exercise.id)).where(Exercise.lesson_id.in_(lesson_ids))
            )
        ).scalar_one()
        exercise_count = int(ex_count_row or 0)
        mcq_count_row = (
            await db.execute(
                select(func.count(MCQBank.id)).where(MCQBank.lesson_id.in_(lesson_ids))
            )
        ).scalar_one()
        mcq_count = int(mcq_count_row or 0)

    # last_active_at may not exist on User; fall back to updated_at
    last_active_col = getattr(User, "last_active_at", User.updated_at)

    enroll_user_rows = (
        await db.execute(
            select(
                Enrollment.student_id,
                Enrollment.progress_pct,
                Enrollment.completed_at,
                Enrollment.enrolled_at,
                User.full_name,
                User.email,
                last_active_col,
            )
            .join(User, User.id == Enrollment.student_id)
            .where(Enrollment.course_id == course_uuid)
        )
    ).all()

    enrolled_count = len(enroll_user_rows)
    completion_count = 0
    progress_sum = 0.0
    student_ids: list[uuid.UUID] = []
    top_candidates: list[CourseAnalyticsTopStudent] = []
    enrolled_last_30 = 0
    enrolled_prior_30 = 0
    cutoff_30 = now - timedelta(days=30)
    cutoff_60 = now - timedelta(days=60)

    for sid, pct, completed, enrolled_at, name, email, last_active in enroll_user_rows:
        pct_f = float(pct or 0.0)
        progress_sum += pct_f
        if completed is not None or pct_f >= 100:
            completion_count += 1
        student_ids.append(sid)

        ea = enrolled_at
        if ea is not None and ea.tzinfo is None:
            ea = ea.replace(tzinfo=UTC)
        if ea is not None:
            if ea >= cutoff_30:
                enrolled_last_30 += 1
            elif cutoff_60 <= ea < cutoff_30:
                enrolled_prior_30 += 1

        if pct_f > 0:
            la = last_active
            if la is not None and la.tzinfo is None:
                la = la.replace(tzinfo=UTC)
            ca = completed
            if ca is not None and ca.tzinfo is None:
                ca = ca.replace(tzinfo=UTC)
            top_candidates.append(
                CourseAnalyticsTopStudent(
                    student_id=str(sid),
                    name=name or "",
                    email=email,
                    progress_pct=round(pct_f / 100.0, 4),
                    completed_at=ca,
                    last_active_at=la,
                )
            )

    top_candidates.sort(key=lambda s: s.progress_pct, reverse=True)
    top_students = top_candidates[:10]

    completion_rate = (completion_count / enrolled_count) if enrolled_count > 0 else 0.0
    avg_progress_pct = (
        (progress_sum / enrolled_count / 100.0) if enrolled_count > 0 else 0.0
    )

    if enrolled_prior_30 > 0:
        enrollments_delta_pct = (enrolled_last_30 - enrolled_prior_30) / enrolled_prior_30
    elif enrolled_last_30 > 0:
        enrollments_delta_pct = 1.0
    else:
        enrollments_delta_pct = 0.0

    avg_confusion_rate = 0.0
    if lesson_ids:
        action_rows = (
            await db.execute(
                select(AgentAction.agent_name, AgentAction.input_data)
            )
        ).all()
        lesson_id_strs = {str(lid) for lid in lesson_ids}
        per_lesson_counts: dict[str, dict[str, int]] = {}
        for agent_name, inp in action_rows:
            if not isinstance(inp, dict):
                continue
            lid = inp.get("lesson_id")
            if not lid or str(lid) not in lesson_id_strs:
                continue
            bucket = per_lesson_counts.setdefault(str(lid), {"total": 0, "confusion": 0})
            bucket["total"] += 1
            if agent_name == "socratic_tutor":
                bucket["confusion"] += 1
        rates: list[float] = []
        for lid in lesson_ids:
            counts = per_lesson_counts.get(str(lid))
            if not counts or counts["total"] == 0:
                continue
            rates.append(counts["confusion"] / counts["total"])
        if rates:
            avg_confusion_rate = sum(rates) / len(rates)

    feedback_rows = (
        await db.execute(
            select(
                Feedback.id,
                Feedback.route,
                Feedback.body,
                Feedback.category,
                Feedback.sentiment,
                Feedback.severity,
                Feedback.resolved,
                Feedback.created_at,
                Feedback.user_id,
                User.full_name,
            )
            .outerjoin(User, User.id == Feedback.user_id)
            .where(Feedback.resolved.is_(False))
            .order_by(Feedback.created_at.desc())
        )
    ).all()

    recent_feedback: list[CourseAnalyticsFeedback] = []
    for fid, route, body, category, sentiment, severity, resolved, created_at, _uid, sname in feedback_rows:
        r = (route or "").lower()
        if slug_needle and slug_needle in r:
            matched = True
        elif id_needle in r:
            matched = True
        else:
            matched = False
        if not matched:
            continue
        ca = created_at
        if ca is not None and ca.tzinfo is None:
            ca = ca.replace(tzinfo=UTC)
        recent_feedback.append(
            CourseAnalyticsFeedback(
                id=str(fid),
                route=route or "",
                body=(body or "")[:280],
                category=category,
                sentiment=sentiment,
                severity=severity,
                resolved=bool(resolved),
                created_at=ca or now,
                student_name=sname,
            )
        )
        if len(recent_feedback) >= 10:
            break

    recent_agent_activity: list[CourseAnalyticsActivity] = []
    if student_ids:
        activity_rows = (
            await db.execute(
                select(
                    AgentAction.id,
                    AgentAction.agent_name,
                    AgentAction.student_id,
                    AgentAction.input_data,
                    AgentAction.output_data,
                    AgentAction.error_message,
                    AgentAction.created_at,
                    User.full_name,
                )
                .outerjoin(User, User.id == AgentAction.student_id)
                .where(AgentAction.student_id.in_(student_ids))
                .order_by(AgentAction.created_at.desc())
                .limit(20)
            )
        ).all()
        for aid, agent_name, sid, inp, outp, err, created_at, sname in activity_rows:
            if isinstance(inp, dict):
                input_text = str(inp.get("task") or inp.get("message") or inp.get("query") or inp)
            else:
                input_text = str(inp or "")
            if isinstance(outp, dict):
                output_text = str(outp.get("response") or outp.get("output") or outp)
            else:
                output_text = str(outp or "")
            ca = created_at
            if ca is not None and ca.tzinfo is None:
                ca = ca.replace(tzinfo=UTC)
            recent_agent_activity.append(
                CourseAnalyticsActivity(
                    action_id=str(aid),
                    agent_name=agent_name,
                    student_id=str(sid) if sid else None,
                    student_name=sname,
                    input_preview=input_text[:120],
                    output_preview=output_text[:200],
                    evaluation_score=_eval_score_from_output(outp),
                    has_error=bool(err),
                    created_at=ca or now,
                )
            )

    log.info(
        "admin.course_analytics_viewed",
        course_id=cid_str,
        enrolled_count=enrolled_count,
        completion_count=completion_count,
    )

    return CourseAnalyticsResponse(
        course_id=cid_str,
        title=course.title,
        slug=course.slug,
        enrolled_count=enrolled_count,
        completion_count=completion_count,
        completion_rate=round(completion_rate, 4),
        avg_progress_pct=round(avg_progress_pct, 4),
        avg_confusion_rate=round(avg_confusion_rate, 4),
        lesson_count=lesson_count,
        exercise_count=exercise_count,
        mcq_count=mcq_count,
        top_students=top_students,
        recent_feedback=recent_feedback,
        recent_agent_activity=recent_agent_activity,
        enrollments_last_30d=enrolled_last_30,
        enrollments_prior_30d=enrolled_prior_30,
        enrollments_delta_pct=round(enrollments_delta_pct, 4),
        generated_at=now,
    )


# =============================================================================
# ── AUDIT-OF-AUDIT: record who viewed sensitive audit data
# =============================================================================


class AuditViewRequest(PydanticModel):
    audit_row_id: str
    viewed_field: str  # "outreach_body" | "auth_ip" | "before_after_diff" | "row_expand" | other
    extra: dict[str, Any] | None = None


@router.post("/audit-log/view", status_code=status.HTTP_204_NO_CONTENT)
async def log_audit_view(
    payload: AuditViewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> None:
    """Record that an admin viewed a sensitive audit row. Best-effort — never fails."""
    try:
        metadata = {"viewed_field": payload.viewed_field, **(payload.extra or {})}
        await AdminAuditService.log(
            db=db,
            admin=admin,
            action_type="audit.view",
            resource_type="audit_row",
            resource_id=payload.audit_row_id,
            metadata=metadata,
            request=request,
        )
    except Exception as exc:
        log.warning("admin.audit_view_log_failed", error=str(exc))
    return None


# =============================================================================
# -- AUDIT-PULSE: metrics view of admin_audit_log + agent_actions (admin views)
# =============================================================================


class AuditPulseKpis(PydanticModel):
    actions_today: int
    actions_yesterday: int
    distinct_admins_today: int
    actions_per_hour_recent: float
    actions_per_hour_baseline: float
    anomaly_count_today: int


class AuditPulseHourBucket(PydanticModel):
    hour_iso: datetime
    count_total: int
    count_by_category: dict[str, int]


class AuditPulseCategoryBreakdown(PydanticModel):
    category: str
    count_today: int
    count_7d: int


class AuditPulseTopActor(PydanticModel):
    admin_id: str | None
    admin_email: str
    count_7d: int
    last_action_at: datetime


class AuditPulseTopResource(PydanticModel):
    resource_type: str
    resource_id: str
    resource_label: str | None
    count_7d: int


class AuditPulseHotAction(PydanticModel):
    id: str
    admin_email: str
    action_type: str
    resource_type: str | None
    resource_id: str | None
    summary: str
    severity: str
    created_at: datetime


class AuditPulseResponse(PydanticModel):
    kpis: AuditPulseKpis
    hourly_sparkline: list[AuditPulseHourBucket]
    categories: list[AuditPulseCategoryBreakdown]
    top_actors: list[AuditPulseTopActor]
    top_courses: list[AuditPulseTopResource]
    top_students: list[AuditPulseTopResource]
    top_agents: list[AuditPulseTopResource]
    hot_critical: list[AuditPulseHotAction]
    generated_at: datetime


def _audit_pulse_category(action_type: str) -> str:
    if not action_type or "." not in action_type:
        return "other"
    prefix = action_type.split(".", 1)[0]
    known = {
        "course", "coupon", "bundle", "feedback", "outreach",
        "auth", "agent", "exercise", "lesson", "mcq",
    }
    return prefix if prefix in known else "other"


def _audit_pulse_is_kill_switch(action_type: str, before: dict | None, after: dict | None) -> bool:
    if action_type != "agent.config_update":
        return False
    a = (after or {}).get("is_enabled")
    b = (before or {}).get("is_enabled")
    if a is False:
        return True
    if b is True and a is False:
        return True
    return False


def _audit_pulse_price_pct(before: dict | None, after: dict | None) -> float:
    try:
        b = (before or {}).get("price_cents")
        a = (after or {}).get("price_cents")
        if b is None or a is None or b == 0:
            return 0.0
        return abs(float(a) - float(b)) / float(b)
    except (TypeError, ValueError):
        return 0.0


def _audit_pulse_is_critical(action_type: str, before: dict | None, after: dict | None) -> bool:
    if not action_type:
        return False
    if action_type.endswith(".delete"):
        return True
    if _audit_pulse_is_kill_switch(action_type, before, after):
        return True
    if action_type == "auth.admin_login":
        return True
    if action_type == "outreach.send":
        return True
    if action_type.startswith("course.update") and _audit_pulse_price_pct(before, after) >= 0.20:
        return True
    return False


def _audit_pulse_severity(action_type: str, before: dict | None, after: dict | None) -> str:
    if action_type.endswith(".delete"):
        return "critical"
    if _audit_pulse_is_kill_switch(action_type, before, after):
        return "warn"
    if action_type.startswith("course.update") and _audit_pulse_price_pct(before, after) >= 0.20:
        return "warn"
    return "info"


def _audit_pulse_summary(action_type: str, resource_type: str | None, resource_id: str | None,
                         before: dict | None, after: dict | None) -> str:
    rt = resource_type or "resource"
    rid = resource_id or "?"
    if action_type.endswith(".delete"):
        return f"Deleted {rt} {rid}"
    if action_type == "auth.admin_login":
        return "Admin login"
    if action_type == "outreach.send":
        return f"Outreach sent to {rid}"
    if _audit_pulse_is_kill_switch(action_type, before, after):
        return f"Agent {rid} disabled"
    if action_type.startswith("course.update"):
        pct = _audit_pulse_price_pct(before, after)
        if pct >= 0.20:
            return f"Course {rid} price changed {pct*100:.0f}%"
    return f"{action_type} on {rt} {rid}"


@router.get("/audit-log/pulse", response_model=AuditPulseResponse)
async def audit_log_pulse(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> AuditPulseResponse:
    from app.models.admin_audit_log import AdminAuditLog
    from app.models.course import Course

    log = structlog.get_logger()
    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    yesterday_start = today_start - timedelta(days=1)
    week_start = now - timedelta(days=7)
    hour_ago = now - timedelta(hours=1)
    sparkline_start = (now.replace(minute=0, second=0, microsecond=0)
                       - timedelta(hours=23))

    kpi_stmt = select(
        func.count().filter(AdminAuditLog.created_at >= today_start).label("today"),
        func.count().filter(
            (AdminAuditLog.created_at >= yesterday_start)
            & (AdminAuditLog.created_at < today_start)
        ).label("yesterday"),
        func.count(func.distinct(AdminAuditLog.admin_id)).filter(
            AdminAuditLog.created_at >= today_start
        ).label("distinct_admins"),
        func.count().filter(AdminAuditLog.created_at >= hour_ago).label("last_hour"),
        func.count().filter(AdminAuditLog.created_at >= week_start).label("last_7d"),
    )
    kpi_row = (await db.execute(kpi_stmt)).one()

    spark_stmt = select(
        func.date_trunc("hour", AdminAuditLog.created_at).label("h"),
        AdminAuditLog.action_type,
        func.count().label("c"),
    ).where(
        AdminAuditLog.created_at >= sparkline_start
    ).group_by("h", AdminAuditLog.action_type)
    spark_rows = (await db.execute(spark_stmt)).all()

    buckets: dict[datetime, dict[str, int]] = {}
    for row in spark_rows:
        h = row.h
        if h.tzinfo is None:
            h = h.replace(tzinfo=UTC)
        cat = _audit_pulse_category(row.action_type)
        buckets.setdefault(h, {})
        buckets[h][cat] = buckets[h].get(cat, 0) + int(row.c)

    hourly: list[AuditPulseHourBucket] = []
    for i in range(24):
        h = sparkline_start + timedelta(hours=i)
        by_cat = buckets.get(h, {})
        hourly.append(AuditPulseHourBucket(
            hour_iso=h,
            count_total=sum(by_cat.values()),
            count_by_category=by_cat,
        ))

    cat_stmt = select(
        AdminAuditLog.action_type,
        func.count().filter(AdminAuditLog.created_at >= today_start).label("today"),
        func.count().filter(AdminAuditLog.created_at >= week_start).label("week"),
    ).where(
        AdminAuditLog.created_at >= week_start
    ).group_by(AdminAuditLog.action_type)
    cat_rows = (await db.execute(cat_stmt)).all()

    cat_agg: dict[str, dict[str, int]] = {}
    for row in cat_rows:
        cat = _audit_pulse_category(row.action_type)
        agg = cat_agg.setdefault(cat, {"today": 0, "week": 0})
        agg["today"] += int(row.today or 0)
        agg["week"] += int(row.week or 0)
    categories = [
        AuditPulseCategoryBreakdown(
            category=cat, count_today=v["today"], count_7d=v["week"]
        )
        for cat, v in sorted(cat_agg.items(), key=lambda kv: -kv[1]["week"])
    ]

    actor_stmt = select(
        AdminAuditLog.admin_id,
        AdminAuditLog.admin_email,
        func.count().label("c"),
        func.max(AdminAuditLog.created_at).label("last_at"),
    ).where(
        AdminAuditLog.created_at >= week_start
    ).group_by(
        AdminAuditLog.admin_id, AdminAuditLog.admin_email
    ).order_by(func.count().desc()).limit(10)
    actor_rows = (await db.execute(actor_stmt)).all()
    top_actors = [
        AuditPulseTopActor(
            admin_id=str(r.admin_id) if r.admin_id else None,
            admin_email=r.admin_email,
            count_7d=int(r.c),
            last_action_at=r.last_at,
        )
        for r in actor_rows
    ]

    resource_stmt = select(
        AdminAuditLog.resource_type,
        AdminAuditLog.resource_id,
        AdminAuditLog.extra,
    ).where(AdminAuditLog.created_at >= week_start)
    resource_rows = (await db.execute(resource_stmt)).all()

    course_counts: dict[str, int] = {}
    student_counts: dict[str, int] = {}
    agent_counts: dict[str, int] = {}
    for r in resource_rows:
        rt = r.resource_type
        rid = r.resource_id
        meta = r.extra or {}
        if rt == "course" and rid:
            course_counts[rid] = course_counts.get(rid, 0) + 1
        if rt == "user" and rid:
            student_counts[rid] = student_counts.get(rid, 0) + 1
        elif isinstance(meta, dict) and meta.get("student_id"):
            sid = str(meta["student_id"])
            student_counts[sid] = student_counts.get(sid, 0) + 1
        if rt == "agent" and rid:
            agent_counts[rid] = agent_counts.get(rid, 0) + 1
        elif isinstance(meta, dict) and meta.get("agent_name"):
            an = str(meta["agent_name"])
            agent_counts[an] = agent_counts.get(an, 0) + 1

    top_course_ids = sorted(course_counts.items(), key=lambda kv: -kv[1])[:5]
    top_student_ids = sorted(student_counts.items(), key=lambda kv: -kv[1])[:5]
    top_agent_ids = sorted(agent_counts.items(), key=lambda kv: -kv[1])[:5]

    course_label: dict[str, str] = {}
    if top_course_ids:
        cids: list[uuid.UUID] = []
        for cid, _c in top_course_ids:
            try:
                cids.append(uuid.UUID(cid))
            except (ValueError, AttributeError):
                continue
        if cids:
            crows = (await db.execute(
                select(Course.id, Course.title).where(Course.id.in_(cids))
            )).all()
            course_label = {str(cid): title for cid, title in crows}

    student_label: dict[str, str] = {}
    if top_student_ids:
        sids: list[uuid.UUID] = []
        for sid, _c in top_student_ids:
            try:
                sids.append(uuid.UUID(sid))
            except (ValueError, AttributeError):
                continue
        if sids:
            srows = (await db.execute(
                select(User.id, User.full_name, User.email).where(User.id.in_(sids))
            )).all()
            for uid, full_name, email in srows:
                student_label[str(uid)] = full_name or email

    top_courses = [
        AuditPulseTopResource(
            resource_type="course",
            resource_id=cid,
            resource_label=course_label.get(cid),
            count_7d=cnt,
        )
        for cid, cnt in top_course_ids
    ]
    top_students = [
        AuditPulseTopResource(
            resource_type="student",
            resource_id=sid,
            resource_label=student_label.get(sid),
            count_7d=cnt,
        )
        for sid, cnt in top_student_ids
    ]
    top_agents = [
        AuditPulseTopResource(
            resource_type="agent",
            resource_id=aid,
            resource_label=aid,
            count_7d=cnt,
        )
        for aid, cnt in top_agent_ids
    ]

    hot_stmt = select(AdminAuditLog).where(
        AdminAuditLog.created_at >= week_start
    ).order_by(AdminAuditLog.created_at.desc()).limit(200)
    hot_rows = (await db.execute(hot_stmt)).scalars().all()
    hot_critical: list[AuditPulseHotAction] = []
    for row in hot_rows:
        if not _audit_pulse_is_critical(row.action_type, row.before_value, row.after_value):
            continue
        hot_critical.append(AuditPulseHotAction(
            id=str(row.id),
            admin_email=row.admin_email,
            action_type=row.action_type,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            summary=_audit_pulse_summary(row.action_type, row.resource_type, row.resource_id,
                                         row.before_value, row.after_value),
            severity=_audit_pulse_severity(row.action_type, row.before_value, row.after_value),
            created_at=row.created_at,
        ))
        if len(hot_critical) >= 10:
            break

    baseline = float(int(kpi_row.last_7d or 0)) / (7.0 * 24.0)
    kpis = AuditPulseKpis(
        actions_today=int(kpi_row.today or 0),
        actions_yesterday=int(kpi_row.yesterday or 0),
        distinct_admins_today=int(kpi_row.distinct_admins or 0),
        actions_per_hour_recent=float(int(kpi_row.last_hour or 0)),
        actions_per_hour_baseline=round(baseline, 4),
        anomaly_count_today=0,
    )

    log.info("admin.audit_pulse.compute",
             today=kpis.actions_today, hot=len(hot_critical))

    return AuditPulseResponse(
        kpis=kpis,
        hourly_sparkline=hourly,
        categories=categories,
        top_actors=top_actors,
        top_courses=top_courses,
        top_students=top_students,
        top_agents=top_agents,
        hot_critical=hot_critical,
        generated_at=now,
    )


# =============================================================================
# ── AUDIT-ANOMALIES: heuristic detection over admin_audit_log
# =============================================================================
import hashlib as _anom_hashlib  # noqa: E402
from collections import defaultdict as _anom_defaultdict  # noqa: E402


class AnomalyDetection(PydanticModel):
    fingerprint: str
    rule_type: str
    severity: str
    admin_id: str | None
    admin_email: str
    description: str
    detected_at: datetime
    window_start: datetime
    window_end: datetime
    audit_row_ids: list[str]
    dismissed: bool


class AnomaliesResponse(PydanticModel):
    items: list[AnomalyDetection]
    generated_at: datetime


class AnomalyDismissRequest(PydanticModel):
    note: str | None = Field(default=None, max_length=500)


def _anom_bucket(dt: datetime, minutes: int) -> datetime:
    """Floor a datetime to the nearest N-minute bucket (UTC)."""
    dt_utc = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    total_minutes = dt_utc.hour * 60 + dt_utc.minute
    floored = (total_minutes // minutes) * minutes
    return dt_utc.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0)


def _anom_price_change_pct(before: dict | None, after: dict | None) -> float:
    """Return absolute % delta on price_cents, or 0.0 if not applicable."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return 0.0
    b = before.get("price_cents")
    a = after.get("price_cents")
    if not isinstance(b, (int, float)) or not isinstance(a, (int, float)) or b == 0:
        return 0.0
    return abs((a - b) / b) * 100.0


@router.get("/audit-log/anomalies", response_model=AnomaliesResponse)
async def get_audit_log_anomalies(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> AnomaliesResponse:
    """Heuristic anomaly detection over admin_audit_log (last 24h).

    Returns all detected anomalies (including dismissed ones — frontend filters).
    SQL queries per call: 4 (audit rows + dismissals + prior-30d IPs + historical action pairs).
    """
    from app.models.admin_audit_log import AdminAuditLog
    from app.models.anomaly_dismissal import AnomalyDismissal

    now = datetime.now(UTC)
    window_start = now - timedelta(hours=24)

    rows_result = await db.execute(
        select(AdminAuditLog)
        .where(AdminAuditLog.created_at >= window_start)
        .order_by(AdminAuditLog.created_at.asc())
    )
    rows = list(rows_result.scalars().all())

    dismissals_result = await db.execute(select(AnomalyDismissal.fingerprint))
    dismissed_set: set[str] = {fp for (fp,) in dismissals_result.all()}

    prior_window = now - timedelta(days=30)
    prior_ip_result = await db.execute(
        select(AdminAuditLog.admin_id, AdminAuditLog.ip_address)
        .where(
            AdminAuditLog.action_type == "auth.admin_login",
            AdminAuditLog.created_at >= prior_window,
            AdminAuditLog.created_at < window_start,
        )
        .distinct()
    )
    prior_ips: set[tuple[str, str]] = {
        (str(aid), ip) for (aid, ip) in prior_ip_result.all() if aid and ip
    }

    hist_result = await db.execute(
        select(AdminAuditLog.admin_id, AdminAuditLog.action_type)
        .where(AdminAuditLog.created_at < window_start)
        .distinct()
    )
    historical_actions: set[tuple[str, str]] = {
        (str(aid), at) for (aid, at) in hist_result.all() if aid
    }

    anomalies: list[AnomalyDetection] = []

    def _email_for(admin_id: str | None) -> str:
        for r in rows:
            if str(r.admin_id) == admin_id:
                return r.admin_email or "(unknown)"
        return "(unknown)"

    # ── Rule 1: burst_delete (5-min bucket, >=10 deletes) ─────────────────────
    delete_buckets: dict[tuple[str, datetime], list[Any]] = _anom_defaultdict(list)
    for r in rows:
        if r.action_type and r.action_type.endswith(".delete") and r.admin_id:
            bucket = _anom_bucket(r.created_at, 5)
            delete_buckets[(str(r.admin_id), bucket)].append(r)
    for (aid, bucket), grp in delete_buckets.items():
        if len(grp) >= 10:
            fp = f"burst_delete:{aid}:{bucket.isoformat()}"
            anomalies.append(AnomalyDetection(
                fingerprint=fp,
                rule_type="burst_delete",
                severity="critical",
                admin_id=aid,
                admin_email=grp[0].admin_email or _email_for(aid),
                description=f"{grp[0].admin_email or 'Admin'} performed {len(grp)} deletes in 5 minutes",
                detected_at=now,
                window_start=bucket,
                window_end=bucket + timedelta(minutes=5),
                audit_row_ids=[str(g.id) for g in grp],
                dismissed=fp in dismissed_set,
            ))

    # ── Rule 2: off_hours_login (22–06 UTC) ───────────────────────────────────
    off_hours_groups: dict[tuple[str, str], list[Any]] = _anom_defaultdict(list)
    for r in rows:
        if r.action_type == "auth.admin_login" and r.admin_id:
            ts = r.created_at.astimezone(UTC) if r.created_at.tzinfo else r.created_at.replace(tzinfo=UTC)
            if ts.hour in (22, 23, 0, 1, 2, 3, 4, 5, 6):
                off_hours_groups[(str(r.admin_id), ts.date().isoformat())].append(r)
    for (aid, day_iso), grp in off_hours_groups.items():
        fp = f"off_hours_login:{aid}:{day_iso}"
        anomalies.append(AnomalyDetection(
            fingerprint=fp,
            rule_type="off_hours_login",
            severity="warn",
            admin_id=aid,
            admin_email=grp[0].admin_email or _email_for(aid),
            description=f"{grp[0].admin_email or 'Admin'} logged in {len(grp)} time(s) during off-hours (22:00–06:59 UTC)",
            detected_at=now,
            window_start=min(g.created_at for g in grp),
            window_end=max(g.created_at for g in grp),
            audit_row_ids=[str(g.id) for g in grp],
            dismissed=fp in dismissed_set,
        ))

    # ── Rule 3: unusual_ip ────────────────────────────────────────────────────
    unusual_ip_groups: dict[tuple[str, str, str], list[Any]] = _anom_defaultdict(list)
    for r in rows:
        if r.action_type == "auth.admin_login" and r.admin_id and r.ip_address:
            key = (str(r.admin_id), r.ip_address)
            if key not in prior_ips:
                ts = r.created_at.astimezone(UTC) if r.created_at.tzinfo else r.created_at.replace(tzinfo=UTC)
                unusual_ip_groups[(str(r.admin_id), r.ip_address, ts.date().isoformat())].append(r)
    for (aid, ip, day_iso), grp in unusual_ip_groups.items():
        fp = f"unusual_ip:{aid}:{ip}:{day_iso}"
        anomalies.append(AnomalyDetection(
            fingerprint=fp,
            rule_type="unusual_ip",
            severity="warn",
            admin_id=aid,
            admin_email=grp[0].admin_email or _email_for(aid),
            description=f"{grp[0].admin_email or 'Admin'} logged in from new IP {ip} (not seen in prior 30 days)",
            detected_at=now,
            window_start=min(g.created_at for g in grp),
            window_end=max(g.created_at for g in grp),
            audit_row_ids=[str(g.id) for g in grp],
            dismissed=fp in dismissed_set,
        ))

    # ── Rule 4: first_time_action ─────────────────────────────────────────────
    _ft_skip = {"auth.admin_login", "audit.view"}
    seen_in_window: set[tuple[str, str]] = set()
    first_time_items: dict[tuple[str, str], Any] = {}
    for r in rows:
        if not r.admin_id or not r.action_type or r.action_type in _ft_skip:
            continue
        key = (str(r.admin_id), r.action_type)
        if key in historical_actions or key in seen_in_window:
            seen_in_window.add(key)
            continue
        seen_in_window.add(key)
        first_time_items[key] = r
    for (aid, action_type), r in first_time_items.items():
        fp = f"first_time_action:{aid}:{action_type}"
        anomalies.append(AnomalyDetection(
            fingerprint=fp,
            rule_type="first_time_action",
            severity="info",
            admin_id=aid,
            admin_email=r.admin_email or _email_for(aid),
            description=f"{r.admin_email or 'Admin'} performed '{action_type}' for the first time",
            detected_at=now,
            window_start=r.created_at,
            window_end=r.created_at,
            audit_row_ids=[str(r.id)],
            dismissed=fp in dismissed_set,
        ))

    # ── Rule 5: bulk_price_change (>=3 course.update with >=20% delta in 10m) ─
    price_buckets: dict[tuple[str, datetime], list[Any]] = _anom_defaultdict(list)
    for r in rows:
        if r.action_type == "course.update" and r.admin_id:
            if _anom_price_change_pct(r.before_value, r.after_value) >= 20.0:
                bucket = _anom_bucket(r.created_at, 10)
                price_buckets[(str(r.admin_id), bucket)].append(r)
    for (aid, bucket), grp in price_buckets.items():
        if len(grp) >= 3:
            fp = f"bulk_price_change:{aid}:{bucket.isoformat()}"
            anomalies.append(AnomalyDetection(
                fingerprint=fp,
                rule_type="bulk_price_change",
                severity="warn",
                admin_id=aid,
                admin_email=grp[0].admin_email or _email_for(aid),
                description=f"{grp[0].admin_email or 'Admin'} made {len(grp)} course price changes (>=20% delta) in 10 minutes",
                detected_at=now,
                window_start=bucket,
                window_end=bucket + timedelta(minutes=10),
                audit_row_ids=[str(g.id) for g in grp],
                dismissed=fp in dismissed_set,
            ))

    # ── Rule 6: outreach_too_short ────────────────────────────────────────────
    for r in rows:
        if r.action_type == "outreach.send" and r.admin_id:
            md = r.extra or {}
            preview = md.get("body_preview") if isinstance(md, dict) else None
            if isinstance(preview, str) and len(preview) < 10:
                fp = f"outreach_short:{r.admin_id}:{r.id}"
                anomalies.append(AnomalyDetection(
                    fingerprint=fp,
                    rule_type="outreach_too_short",
                    severity="info",
                    admin_id=str(r.admin_id),
                    admin_email=r.admin_email or _email_for(str(r.admin_id)),
                    description=f"{r.admin_email or 'Admin'} sent outreach with very short body ({len(preview)} chars)",
                    detected_at=now,
                    window_start=r.created_at,
                    window_end=r.created_at,
                    audit_row_ids=[str(r.id)],
                    dismissed=fp in dismissed_set,
                ))

    # ── Rule 7: outreach_reused (same body within 1h bucket) ──────────────────
    reuse_buckets: dict[tuple[str, str, datetime], list[Any]] = _anom_defaultdict(list)
    for r in rows:
        if r.action_type == "outreach.send" and r.admin_id:
            md = r.extra or {}
            preview = md.get("body_preview") if isinstance(md, dict) else None
            if isinstance(preview, str) and preview:
                body_hash = _anom_hashlib.sha1(preview.encode("utf-8")).hexdigest()[:16]
                bucket = _anom_bucket(r.created_at, 60)
                reuse_buckets[(str(r.admin_id), body_hash, bucket)].append(r)
    for (aid, body_hash, bucket), grp in reuse_buckets.items():
        if len(grp) >= 2:
            fp = f"outreach_reused:{aid}:{body_hash}:{bucket.isoformat()}"
            anomalies.append(AnomalyDetection(
                fingerprint=fp,
                rule_type="outreach_reused",
                severity="info",
                admin_id=aid,
                admin_email=grp[0].admin_email or _email_for(aid),
                description=f"{grp[0].admin_email or 'Admin'} reused identical outreach body {len(grp)} times within 1 hour",
                detected_at=now,
                window_start=bucket,
                window_end=bucket + timedelta(hours=1),
                audit_row_ids=[str(g.id) for g in grp],
                dismissed=fp in dismissed_set,
            ))

    # ── Rule 8: coupon_spam (>=5 coupon.create in 10m) ────────────────────────
    coupon_buckets: dict[tuple[str, datetime], list[Any]] = _anom_defaultdict(list)
    for r in rows:
        if r.action_type == "coupon.create" and r.admin_id:
            bucket = _anom_bucket(r.created_at, 10)
            coupon_buckets[(str(r.admin_id), bucket)].append(r)
    for (aid, bucket), grp in coupon_buckets.items():
        if len(grp) >= 5:
            fp = f"coupon_spam:{aid}:{bucket.isoformat()}"
            anomalies.append(AnomalyDetection(
                fingerprint=fp,
                rule_type="coupon_spam",
                severity="warn",
                admin_id=aid,
                admin_email=grp[0].admin_email or _email_for(aid),
                description=f"{grp[0].admin_email or 'Admin'} created {len(grp)} coupons in 10 minutes",
                detected_at=now,
                window_start=bucket,
                window_end=bucket + timedelta(minutes=10),
                audit_row_ids=[str(g.id) for g in grp],
                dismissed=fp in dismissed_set,
            ))

    # ── Rule 9: agent_kill_switch ─────────────────────────────────────────────
    for r in rows:
        if r.action_type == "agent.config_update" and r.admin_id:
            after = r.after_value if isinstance(r.after_value, dict) else None
            if after is not None and after.get("is_enabled") is False:
                fp = f"agent_kill:{r.admin_id}:{r.resource_id}:{r.id}"
                anomalies.append(AnomalyDetection(
                    fingerprint=fp,
                    rule_type="agent_kill_switch",
                    severity="warn",
                    admin_id=str(r.admin_id),
                    admin_email=r.admin_email or _email_for(str(r.admin_id)),
                    description=f"{r.admin_email or 'Admin'} disabled agent '{r.resource_id}' (kill-switch)",
                    detected_at=now,
                    window_start=r.created_at,
                    window_end=r.created_at,
                    audit_row_ids=[str(r.id)],
                    dismissed=fp in dismissed_set,
                ))

    return AnomaliesResponse(items=anomalies, generated_at=now)


@router.post(
    "/audit-log/anomalies/{fingerprint}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def dismiss_audit_anomaly(
    fingerprint: str,
    payload: AnomalyDismissRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> None:
    """Mark an anomaly as not-actionable. Itself audited."""
    from app.models.anomaly_dismissal import AnomalyDismissal

    rule_type = fingerprint.split(":", 1)[0] if ":" in fingerprint else "unknown"

    existing = (
        await db.execute(
            select(AnomalyDismissal).where(AnomalyDismissal.fingerprint == fingerprint)
        )
    ).scalar_one_or_none()
    if existing is None:
        entry = AnomalyDismissal(
            fingerprint=fingerprint,
            rule_type=rule_type,
            admin_id=admin.id,
            dismissed_by=admin.id,
            note=payload.note,
        )
        db.add(entry)
        await db.commit()

    try:
        await AdminAuditService.log(
            db=db,
            admin=admin,
            action_type="anomaly.dismiss",
            resource_type="anomaly",
            resource_id=fingerprint,
            metadata={"rule_type": rule_type, "note": payload.note},
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("admin.anomaly_dismiss_audit_failed", error=str(exc))
    return None


@router.delete(
    "/audit-log/anomalies/{fingerprint}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def undismiss_audit_anomaly(
    fingerprint: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> None:
    """Remove a prior dismissal. Itself audited."""
    from app.models.anomaly_dismissal import AnomalyDismissal

    rule_type = fingerprint.split(":", 1)[0] if ":" in fingerprint else "unknown"

    existing = (
        await db.execute(
            select(AnomalyDismissal).where(AnomalyDismissal.fingerprint == fingerprint)
        )
    ).scalar_one_or_none()
    if existing is not None:
        await db.delete(existing)
        await db.commit()

    try:
        await AdminAuditService.log(
            db=db,
            admin=admin,
            action_type="anomaly.undismiss",
            resource_type="anomaly",
            resource_id=fingerprint,
            metadata={"rule_type": rule_type},
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("admin.anomaly_undismiss_audit_failed", error=str(exc))
    return None
