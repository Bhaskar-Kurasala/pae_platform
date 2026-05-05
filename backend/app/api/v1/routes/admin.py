import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel as PydanticModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.agent_action import AgentAction
from app.models.user import User
from app.schemas.student_note import StudentNoteCreate, StudentNoteResponse
from app.services import refund_offer_service
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
    """DISC-55 — one event on a student's activity timeline."""

    kind: str  # "login" | "lesson_completed" | "agent_action" | "submission"
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


class ExerciseRubricUpdateRequest(PydanticModel):
    rubric: dict[str, Any]
    test_cases: list[dict[str, Any]] | None = None


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
        raise HTTPException(status_code=404, detail=str(exc)) from exc

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
        raise HTTPException(status_code=500, detail=f"Agent run failed: {exc}") from exc
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
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> None:
    """Update course title/description (#144)."""
    from app.models.course import Course

    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if body.title is not None:
        course.title = body.title
    if body.description is not None:
        course.description = body.description
    await db.commit()
    log.info("admin.course_updated", course_id=str(course_id))


@router.patch("/exercises/{exercise_id}/rubric", status_code=204)
async def update_exercise_rubric(
    exercise_id: uuid.UUID,
    body: ExerciseRubricUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> None:
    """Update exercise rubric and test cases (#145)."""
    from app.models.exercise import Exercise

    result = await db.execute(select(Exercise).where(Exercise.id == exercise_id))
    exercise = result.scalar_one_or_none()
    if not exercise:
        raise HTTPException(status_code=404, detail="Exercise not found")
    exercise.rubric = body.rubric
    if body.test_cases is not None:
        exercise.test_cases = body.test_cases  # type: ignore[assignment]
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

    # Onboarded — has a goal_contracts row.
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
