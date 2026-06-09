"""Seed the Today-screen demo dataset.

Idempotent. Run as:

    cd backend && uv run python -m app.scripts.seed_today_demo

After this runs, ``GET /api/v1/today/summary`` for ``demo@pae.dev`` returns a
fully populated payload — non-zero progress, due SRS cards, capstone, peers,
promotions, micro-wins, and a "Session 14"-style ordinal.

Each helper below is a find-or-create keyed on a stable column (email, slug,
course+order, user+concept) so reruns are no-ops on the data plane and only
bump ``updated_at``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.hashing import hash_password
from app.models.application_kit import ApplicationKit
from app.models.cohort_event import CohortEvent
from app.models.course import Course
from app.models.course_bundle import CourseBundle
from app.models.interview_session import InterviewSession
from app.models.notebook_entry import NotebookEntry
from app.models.portfolio_autopsy_result import PortfolioAutopsyResult
from app.models.readiness_workspace_event import ReadinessWorkspaceEvent
from app.models.enrollment import Enrollment
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.learning_session import LearningSession
from app.models.lesson import Lesson
from app.models.skill import Skill
from app.models.student_misconception import StudentMisconception
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.models.user_skill_state import UserSkillState
from app.schemas.goal_contract import GoalContractCreate
from app.services.cohort_event_service import record_event
from app.services.daily_intention_service import upsert_today
from app.services.goal_contract_service import GoalContractService
from app.services.notebook_service import concept_key_for
from app.services.srs_service import SRSService

log = structlog.get_logger()

# --------------------------------------------------------------------------- #
# Stable keys — every find-or-create leans on these.                          #
# --------------------------------------------------------------------------- #
DEMO_EMAIL = "demo@pae.dev"
DEMO_PASSWORD = "demo-password-123"
DEMO_NAME = "Demo Learner"
CAPSTONE_TITLE = "CLI AI tool"
HARD_EXERCISE_TITLE = "Build a retry decorator"

PEER_USERS: list[tuple[str, str]] = [
    ("priya.peer@pae.dev", "Priya Khanna"),
    ("marcus.peer@pae.dev", "Marcus Lee"),
    ("ana.peer@pae.dev", "Ana Ruiz"),
]

# (slug, title, lesson_count, completed_count) — yields ~12/38 ≈ 31.6% weighted.
COURSES: list[tuple[str, str, int, int]] = [
    ("python-foundations", "Python Foundations", 16, 8),
    ("data-analyst-path", "Data Analyst Path", 22, 4),
]

SKILLS: list[tuple[str, str, str]] = [
    ("apis", "APIs", "Designing and consuming HTTP APIs cleanly."),
    ("async_python", "Async Python", "Cooperative concurrency with asyncio."),
    ("error_handling", "Error Handling", "Failing loud, recovering smart."),
]

# (concept_key, prompt, answer, hint) — 7 cards, varied so the queue isn't filler.
SRS_CARDS: list[tuple[str, str, str, str]] = [
    ("apis:rest_basics", "What does REST mean in one sentence?",
     "REST is a stateless client–server style where resources are addressed by URL and manipulated via HTTP verbs.",
     "Think 'resources + verbs', not RPC."),
    ("apis:idempotency", "Which HTTP methods are idempotent and why does it matter?",
     "GET, PUT, DELETE, HEAD, OPTIONS — repeating the request yields the same server state, which is what makes safe retries possible.",
     "Idempotent = safe to retry."),
    ("async_python:event_loop", "What is the event loop responsible for?",
     "Scheduling and running coroutines: it picks the next ready task, runs it until it awaits, then moves on.",
     "One thread, many paused coroutines."),
    ("error_handling:bare_except", "Why is `except:` (no type) a smell?",
     "It swallows KeyboardInterrupt and SystemExit alongside real errors, hiding bugs and making Ctrl-C unreliable.",
     "Catch what you can handle — name the exception."),
    ("apis:status_codes", "When do you return 422 vs 400?",
     "400 means the request was malformed; 422 means it parsed fine but failed business validation.",
     "Syntax vs semantics."),
    ("async_python:gather", "What does asyncio.gather give you over a loop of awaits?",
     "Concurrent execution — all coroutines run interleaved on the loop instead of one-at-a-time.",
     "Fan out, then wait."),
    ("error_handling:retries", "What's the right retry pattern for a flaky third-party call?",
     "Exponential backoff with jitter, a max attempt cap, and a circuit-breaker so a dead dependency doesn't take you down.",
     "Backoff + cap + breaker."),
]


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Find-or-create helpers (one per row family)                                 #
# --------------------------------------------------------------------------- #
async def _ensure_user(
    db: AsyncSession, *, email: str, full_name: str
) -> User:
    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        existing.full_name = full_name
        existing.role = "student"
        existing.is_active = True
        existing.is_verified = True
        if not existing.hashed_password:
            existing.hashed_password = hash_password(DEMO_PASSWORD)
        await db.flush()
        log.info("seed.user.existing", email=email)
        return existing
    user = User(
        email=email,
        full_name=full_name,
        hashed_password=hash_password(DEMO_PASSWORD),
        role="student",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    log.info("seed.user.created", email=email, user_id=str(user.id))
    return user


async def _ensure_course(
    db: AsyncSession, *, slug: str, title: str, lesson_count: int
) -> Course:
    course = (
        await db.execute(select(Course).where(Course.slug == slug))
    ).scalar_one_or_none()
    if course is None:
        course = Course(
            slug=slug, title=title, description=f"Demo course: {title}.",
            is_published=True, difficulty="beginner",
            estimated_hours=lesson_count, price_cents=0,
        )
        db.add(course)
        await db.flush()
        log.info("seed.course.created", slug=slug)

    # Lessons keyed on (course_id, order). Backfill any missing ones.
    for order in range(1, lesson_count + 1):
        existing = (
            await db.execute(
                select(Lesson).where(
                    Lesson.course_id == course.id, Lesson.order == order
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(Lesson(
                course_id=course.id,
                slug=f"{slug}-lesson-{order:02d}",
                title=f"{title} — Lesson {order}",
                description=f"Lesson {order} of {title}.",
                order=order, duration_seconds=600, is_published=True,
            ))
    await db.flush()
    return course


async def _ensure_enrollment(
    db: AsyncSession, *, student: User, course: Course
) -> None:
    existing = (
        await db.execute(
            select(Enrollment).where(
                Enrollment.student_id == student.id,
                Enrollment.course_id == course.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(Enrollment(
            student_id=student.id, course_id=course.id, status="active",
            enrolled_at=_now() - timedelta(days=20),
        ))
        await db.flush()
        log.info("seed.enrollment.created",
                 student=student.email, course=course.slug)


async def _mark_lessons_completed(
    db: AsyncSession, *, student: User, course: Course, count: int
) -> None:
    """Mark first `count` lessons completed; spread completed_at over 7 days
    so consistency picks up multiple distinct days."""
    lessons = list((await db.execute(
        select(Lesson).where(Lesson.course_id == course.id)
        .order_by(Lesson.order).limit(count)
    )).scalars())
    now = _now()
    for idx, lesson in enumerate(lessons):
        completed_at = now - timedelta(days=(idx % 7), hours=2)
        existing = (
            await db.execute(
                select(StudentProgress).where(
                    StudentProgress.student_id == student.id,
                    StudentProgress.lesson_id == lesson.id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(StudentProgress(
                student_id=student.id, lesson_id=lesson.id,
                status="completed", completed_at=completed_at,
                watch_time_seconds=420,
            ))
        else:
            existing.status = "completed"
            existing.completed_at = completed_at
            existing.watch_time_seconds = max(existing.watch_time_seconds, 420)
    await db.flush()
    log.info("seed.progress.completed",
             student=student.email, course=course.slug, count=len(lessons))


async def _ensure_skills(db: AsyncSession) -> dict[str, Skill]:
    out: dict[str, Skill] = {}
    for slug, name, desc in SKILLS:
        skill = (
            await db.execute(select(Skill).where(Skill.slug == slug))
        ).scalar_one_or_none()
        if skill is None:
            skill = Skill(slug=slug, name=name, description=desc, difficulty=2)
            db.add(skill)
            await db.flush()
            log.info("seed.skill.created", slug=slug)
        out[slug] = skill
    return out


async def _touch_skill(
    db: AsyncSession, *, user: User, skill: Skill, last_touched: datetime
) -> None:
    state = (
        await db.execute(
            select(UserSkillState).where(
                UserSkillState.user_id == user.id,
                UserSkillState.skill_id == skill.id,
            )
        )
    ).scalar_one_or_none()
    if state is None:
        db.add(UserSkillState(
            user_id=user.id, skill_id=skill.id,
            mastery_level="practicing", confidence=0.55,
            last_touched_at=last_touched,
        ))
    else:
        state.last_touched_at = last_touched
        state.mastery_level = "practicing"
    await db.flush()


async def _ensure_capstone(
    db: AsyncSession, *, demo_user: User, anchor_lesson: Lesson
) -> Exercise:
    """Single capstone + one graded draft @ score=84."""
    capstone = (
        await db.execute(
            select(Exercise).where(
                Exercise.title == CAPSTONE_TITLE,
                Exercise.is_capstone.is_(True),
            )
        )
    ).scalar_one_or_none()
    due = _now() + timedelta(days=5)
    if capstone is None:
        capstone = Exercise(
            lesson_id=anchor_lesson.id, title=CAPSTONE_TITLE,
            description="Build a small CLI that wraps the Anthropic API.",
            exercise_type="capstone", difficulty="hard",
            is_capstone=True, pass_score=70, due_at=due, points=200,
        )
        db.add(capstone)
        await db.flush()
        log.info("seed.capstone.created", id=str(capstone.id))
    else:
        capstone.due_at = due
        capstone.is_capstone = True
        capstone.pass_score = 70
        await db.flush()

    submission = (
        await db.execute(
            select(ExerciseSubmission).where(
                ExerciseSubmission.student_id == demo_user.id,
                ExerciseSubmission.exercise_id == capstone.id,
            )
        )
    ).scalar_one_or_none()
    if submission is None:
        db.add(ExerciseSubmission(
            student_id=demo_user.id, exercise_id=capstone.id,
            code="# draft\nprint('hello, capstone')\n",
            status="graded", score=84,
            feedback="Solid first draft — tighten the error paths next pass.",
            attempt_number=1,
        ))
        await db.flush()
        log.info("seed.capstone.draft_created", student=demo_user.email)
    return capstone


async def _ensure_hard_exercise_pass(
    db: AsyncSession, *, demo_user: User, anchor_lesson: Lesson
) -> None:
    """Passed-status submission on a hard exercise inside the 48h window —
    drives the `hard_exercise_passed` micro-win."""
    ex = (
        await db.execute(
            select(Exercise).where(Exercise.title == HARD_EXERCISE_TITLE)
        )
    ).scalar_one_or_none()
    if ex is None:
        ex = Exercise(
            lesson_id=anchor_lesson.id, title=HARD_EXERCISE_TITLE,
            description="Wrap a flaky callable with exponential backoff.",
            exercise_type="coding", difficulty="hard",
            pass_score=70, points=100,
        )
        db.add(ex)
        await db.flush()

    sub = (
        await db.execute(
            select(ExerciseSubmission).where(
                ExerciseSubmission.student_id == demo_user.id,
                ExerciseSubmission.exercise_id == ex.id,
                ExerciseSubmission.status == "passed",
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        db.add(ExerciseSubmission(
            student_id=demo_user.id, exercise_id=ex.id,
            code="def retry(fn): ...",
            status="passed", score=88,
            feedback="Nice — backoff + jitter are both there.",
            attempt_number=1,
        ))
        await db.flush()
        log.info("seed.hard_exercise.passed", student=demo_user.email)


async def _ensure_misconception(db: AsyncSession, *, demo_user: User) -> None:
    """Resolved-misconception row inside the 48h window."""
    existing = (
        await db.execute(
            select(StudentMisconception).where(
                StudentMisconception.user_id == demo_user.id,
                StudentMisconception.topic == "REST idempotency",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    db.add(StudentMisconception(
        user_id=demo_user.id, topic="REST idempotency",
        student_assertion="POST is idempotent because it always creates a row.",
        tutor_correction=(
            "POST is not idempotent — repeating it usually creates duplicate "
            "resources. PUT and DELETE are the idempotent verbs."
        ),
    ))
    await db.flush()
    log.info("seed.misconception.created", student=demo_user.email)


async def _ensure_prior_sessions(
    db: AsyncSession, *, user: User, count: int = 13
) -> None:
    """Backfill ordinals 1..count so get_or_open_session opens #count+1 next."""
    existing = list((await db.execute(
        select(LearningSession).where(LearningSession.user_id == user.id)
    )).scalars().all())
    if len(existing) >= count:
        return
    now = _now()
    for ordinal in range(len(existing) + 1, count + 1):
        # Newer ordinals live closer to "now"; ordered across last 18 days.
        offset_days = 18 - int(18 * (ordinal / count))
        started_at = now - timedelta(days=offset_days, hours=ordinal % 4)
        ended_at = started_at + timedelta(minutes=45)
        db.add(LearningSession(
            user_id=user.id, ordinal=ordinal,
            started_at=started_at, ended_at=ended_at,
            warmup_done_at=started_at + timedelta(minutes=5),
            lesson_done_at=started_at + timedelta(minutes=25),
            reflect_done_at=ended_at,
        ))
    await db.flush()
    log.info("seed.sessions.backfilled", user=user.email, target=count)


async def _ensure_srs_cards(db: AsyncSession, *, user: User) -> None:
    """7 due cards with answer + hint, scattered between -3d and now."""
    svc = SRSService(db)
    now = _now()
    for idx, (concept_key, prompt, answer, hint) in enumerate(SRS_CARDS):
        card = await svc.upsert_card(
            user_id=user.id, concept_key=concept_key,
            prompt=prompt, answer=answer, hint=hint,
        )
        # Force-due regardless of prior SM-2 history; stagger across 3 days.
        offset_hours = int((idx / max(1, len(SRS_CARDS) - 1)) * 72)
        card.next_due_at = now - timedelta(hours=72 - offset_hours)
        if not card.answer:
            card.answer = answer
        if not card.hint:
            card.hint = hint
    await db.flush()
    log.info("seed.srs.cards_due", user=user.email, count=len(SRS_CARDS))


async def _ensure_cohort_events(
    db: AsyncSession, *, peers: list[User]
) -> None:
    """5 events across 3 distinct peers, ≥2 of kind=level_up, all <24h old."""
    targets: list[tuple[str, User, str]] = [
        ("level_up", peers[0], "Priya K. promoted to Python Developer"),
        ("level_up", peers[1], "Marcus L. promoted to Data Engineer"),
        ("capstone_shipped", peers[2], "Ana R. shipped 'CLI AI tool'"),
        ("streak_started", peers[0], "Priya K. started a 5-day streak"),
        ("milestone", peers[1], "Marcus L. crossed 50 lessons completed"),
    ]
    now = _now()
    for idx, (kind, actor, label) in enumerate(targets):
        existing = (
            await db.execute(
                select(CohortEvent).where(
                    CohortEvent.kind == kind,
                    CohortEvent.actor_id == actor.id,
                    CohortEvent.label == label,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        await record_event(
            db, kind=kind, actor=actor, label=label,
            occurred_at=now - timedelta(hours=idx + 1),
        )
    log.info("seed.cohort.events", count=len(targets))


# --------------------------------------------------------------------------- #
# Notebook seeding                                                            #
# --------------------------------------------------------------------------- #
# Each entry stable-keyed on (user, message_id) so reruns don't duplicate.
# We seed one already-graduated note (proves the eyebrow flips correctly)
# plus three in-review notes across distinct sources/topics so the filter
# chips on the Notebook screen have visible state to play with.
NOTEBOOK_SEED: list[tuple[str, str, str, str, str, list[str], bool]] = [
    (
        "demo-msg-rag",
        "demo-conv-rag",
        "Retrieval-Augmented Generation",
        "RAG works because dense vectors let semantic search beat keyword "
        "match — the embedder maps meaning, not letters.",
        "chat",
        ["rag", "embeddings"],
        True,
    ),
    (
        "demo-msg-async",
        "demo-conv-async",
        "asyncio.gather concurrency",
        "Use gather() when independent coroutines can run in parallel; "
        "sequential awaits block each other and waste latency.",
        "chat",
        ["async", "python"],
        False,
    ),
    (
        "demo-msg-quiz1",
        "demo-conv-quiz",
        "REST idempotency",
        "PUT and DELETE are idempotent because repeating them produces the "
        "same final state. POST usually isn't.",
        "quiz",
        ["api", "rest"],
        False,
    ),
    (
        "demo-msg-career",
        "demo-conv-career",
        "Resume action verbs",
        "Lead with measurable outcomes, not responsibilities. \"Cut p99 by "
        "40%\" beats \"responsible for performance\".",
        "career",
        ["resume"],
        False,
    ),
]


async def _ensure_notebook_entries(
    db: AsyncSession, *, user: User
) -> None:
    for (
        message_id, conversation_id, topic, body, source, tags, graduate,
    ) in NOTEBOOK_SEED:
        existing = (
            await db.execute(
                select(NotebookEntry).where(
                    NotebookEntry.user_id == user.id,
                    NotebookEntry.message_id == message_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            entry = NotebookEntry(
                user_id=user.id,
                message_id=message_id,
                conversation_id=conversation_id,
                content=body,
                title=topic,
                user_note=body,
                source_type=source,
                topic=topic,
                tags=list(tags),
            )
            db.add(entry)
            await db.flush()
            existing = entry
        if graduate and existing.graduated_at is None:
            existing.graduated_at = _now() - timedelta(days=2)
        # Seed the matching SRS card so the graduation pipeline has state.
        try:
            await SRSService(db).upsert_card(
                user_id=user.id,
                concept_key=concept_key_for(existing),
                prompt=existing.title or existing.content[:120],
                answer=existing.user_note or existing.content,
                hint="Recall the gist in your own words before reveal.",
            )
        except Exception as exc:
            # PR3/C2.1 — seeder script: best-effort SRS upsert per
            # notebook entry. Don't bring the whole reseed down on a
            # single duplicate / constraint blip.
            log.debug(
                "seed.notebook.srs_upsert_skipped",
                concept_key=concept_key_for(existing),
                error=str(exc),
            )
    await db.commit()
    log.info("seed.notebook.entries", count=len(NOTEBOOK_SEED))


# --------------------------------------------------------------------------- #
# Readiness workspace seeding                                                 #
# --------------------------------------------------------------------------- #
# Seeds: 2 portfolio autopsies (one strong, one borderline), 1 ready
# application kit (so the Kit view has visible state), and ~12 workspace
# events distributed across views (so the analytics summary endpoint
# returns realistic numbers).

AUTOPSY_SEED: list[tuple[str, str, int, str, list[str]]] = [
    (
        "CLI AI tool",
        "An async-first CLI that asks Claude for code review, retries on rate "
        "limits, and writes structured feedback to disk.",
        78,
        "Solid execution with tight scope and good failure handling. Two "
        "observability gaps separate this from a strong senior submission.",
        ["Async retry pattern with exponential backoff", "Clear function isolation"],
    ),
    (
        "Earnings sentiment notebook",
        "A notebook that scrapes 10-K filings and runs sentiment scoring "
        "across paragraphs to surface tone shifts quarter-over-quarter.",
        58,
        "Promising direction but the data pipeline is fragile and the chart "
        "lacks the punchline a recruiter would want.",
        ["Interesting domain choice", "Picked a real-world data source"],
    ),
]


async def _ensure_autopsies(
    db: AsyncSession, *, user: User
) -> list[PortfolioAutopsyResult]:
    rows: list[PortfolioAutopsyResult] = []
    for title, desc, score, headline, what_worked in AUTOPSY_SEED:
        existing = (
            await db.execute(
                select(PortfolioAutopsyResult).where(
                    PortfolioAutopsyResult.user_id == user.id,
                    PortfolioAutopsyResult.project_title == title,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            rows.append(existing)
            continue
        # Construct a defensible axes payload that mirrors what the agent
        # produces. Scores chosen so each axis trends with the headline.
        per_axis = max(40, min(100, score - 6))
        axes = {
            "architecture": {"score": per_axis, "assessment": "Clean separation."},
            "failure_handling": {
                "score": per_axis - 4,
                "assessment": "Retries land but error surfaces could be tighter.",
            },
            "observability": {
                "score": per_axis - 8,
                "assessment": "Logs are thin — add structured events.",
            },
            "scope_discipline": {
                "score": per_axis + 2,
                "assessment": "Resists feature creep; ships the spec.",
            },
        }
        row = PortfolioAutopsyResult(
            user_id=user.id,
            project_title=title,
            project_description=desc,
            code=None,
            headline=headline,
            overall_score=score,
            axes=axes,
            what_worked=what_worked,
            what_to_do_differently=[
                {
                    "issue": "Observability gap",
                    "why_it_matters": "Recruiters look for proof you can debug in prod.",
                    "what_to_do_differently": "Add a structured logger + one quantified outcome.",
                }
            ],
            production_gaps=["No metrics emitted", "No retry budget cap"],
            next_project_seed="Wrap the CLI as an HTTP service with rate-limit headers.",
            raw_request=None,
        )
        db.add(row)
        rows.append(row)
    await db.commit()
    for r in rows:
        await db.refresh(r)
    log.info("seed.autopsies", count=len(rows), user=DEMO_EMAIL)
    return rows


async def _ensure_application_kit(
    db: AsyncSession, *, user: User, autopsy: PortfolioAutopsyResult | None
) -> ApplicationKit:
    label = "Kit · Data Analyst pilot"
    existing = (
        await db.execute(
            select(ApplicationKit).where(
                ApplicationKit.user_id == user.id,
                ApplicationKit.label == label,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    manifest: dict = {
        "label": label,
        "target_role": "Data Analyst",
        "built_at": _now().isoformat(),
        "resume": {
            "title": "Demo Learner — Resume",
            "summary": "Python developer pivoting into data analytics.",
            "bullets": [
                "Built a CLI AI tool with async retries and structured logging.",
                "Shipped a 4-week notebook on earnings sentiment shifts.",
            ],
            "skills_snapshot": ["python", "pandas", "sql", "async", "apis"],
            "ats_keywords": ["python", "pandas", "sql", "data analysis"],
        },
    }
    if autopsy is not None:
        manifest["autopsy"] = {
            "id": str(autopsy.id),
            "headline": autopsy.headline,
            "overall_score": autopsy.overall_score,
            "what_worked": autopsy.what_worked,
            "what_to_do_differently": autopsy.what_to_do_differently,
        }
    row = ApplicationKit(
        user_id=user.id,
        label=label,
        target_role="Data Analyst",
        autopsy_id=autopsy.id if autopsy is not None else None,
        manifest=manifest,
        status="ready",
        pdf_blob=b"%PDF-1.4\n%seeded\n",
        generated_at=_now() - timedelta(hours=2),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    log.info("seed.application_kit", id=str(row.id), user=DEMO_EMAIL)
    return row


WORKSPACE_EVENT_SEED: list[tuple[str, str, dict | None, int]] = [
    # (view, event, payload, hours_ago)
    ("overview", "view_opened", None, 24),
    ("overview", "cta_clicked", {"kind": "open_resume"}, 23),
    ("resume", "view_opened", None, 23),
    ("resume", "subnav_clicked", {"tab": "bullets"}, 22),
    ("jd", "view_opened", None, 18),
    ("jd", "jd_preset_selected", {"preset": "data"}, 18),
    ("interview", "view_opened", None, 12),
    ("proof", "view_opened", None, 8),
    ("proof", "autopsy_started", {"project_title": "CLI AI tool"}, 7),
    ("kit", "view_opened", None, 4),
    ("kit", "kit_build_started", {"components": ["resume", "autopsy"]}, 3),
    ("kit", "kit_downloaded", {"kit_id": "seeded"}, 2),
]


async def _ensure_workspace_events(db: AsyncSession, *, user: User) -> int:
    # Cheap: keyed on (user, view, event, occurred_at) so the rerun is a no-op.
    inserted = 0
    base = _now()
    for view, event, payload, hours_ago in WORKSPACE_EVENT_SEED:
        occurred_at = base - timedelta(hours=hours_ago)
        existing = (
            await db.execute(
                select(ReadinessWorkspaceEvent).where(
                    ReadinessWorkspaceEvent.user_id == user.id,
                    ReadinessWorkspaceEvent.view == view,
                    ReadinessWorkspaceEvent.event == event,
                    ReadinessWorkspaceEvent.occurred_at == occurred_at,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        row = ReadinessWorkspaceEvent(
            user_id=user.id,
            view=view,
            event=event,
            payload=payload,
            occurred_at=occurred_at,
        )
        db.add(row)
        inserted += 1
    await db.commit()
    log.info("seed.workspace_events", inserted=inserted, user=DEMO_EMAIL)
    return inserted


# --------------------------------------------------------------------------- #
# Catalog metadata + bundles (Catalog refactor 2026-04-26)                    #
# --------------------------------------------------------------------------- #
# Each entry binds to an existing course slug (or creates one if missing) and
# fills in the rich `bullets` + `metadata` columns the new Catalog screen
# reads. Idempotent — reruns only update fields that look like defaults.
CATALOG_METADATA: list[tuple[str, dict]] = [
    (
        # Use the canonical "python-developer" course slug — there's a
        # separate "python-foundations" Today-seed course that powers the
        # progress / lessons flow; we don't co-opt its title.
        "python-developer",
        {
            "title_override": "Python Developer",
            "price_cents": 0,
            "difficulty": "beginner",
            "bullets": [
                {"text": "16 lessons · fundamentals, OOP, APIs, testing, debugging, collab", "included": True},
                {"text": "18 labs with automated test suites", "included": True},
                {"text": "1 CLI-tool capstone reviewed by your mentor", "included": True},
                {"text": "Spaced-repetition notebook across all lessons", "included": False},
            ],
            "metadata": {
                "level_label": "Level 1 · Free foundation",
                "lesson_count": 16,
                "lab_count": 18,
                "est_hours": 45,
                "est_weeks": 6,
                "completion_pct": 92,
                "accent_color": "var(--forest)",
                "tags": ["python", "foundation"],
            },
        },
    ),
    (
        "data-analyst",
        {
            "title_override": "Data Analyst",
            "price_cents": 8900,  # ₹89 in INR or $89 in USD; backend stores cents
            "difficulty": "intermediate",
            "bullets": [
                {"text": "8 lessons · SQL, pandas at scale, viz, stakeholder comms", "included": True},
                {"text": "22 labs · real retail + marketing datasets", "included": True},
                {"text": "Dashboard capstone graded by a working analyst", "included": True},
                {"text": "2 mock interviews + resume review with mentor", "included": True},
            ],
            "metadata": {
                "level_label": "Level 2 · Your next step",
                "lesson_count": 8,
                "lab_count": 22,
                "est_hours": 60,
                "est_weeks": 8,
                "placement_pct": 76,
                "accent_color": "var(--gold)",
                "ribbon_text": "Most popular",
                "tags": ["sql", "pandas", "analytics"],
                "salary_tooltip": {
                    "eyebrow": "Why unlock Data Analyst",
                    "stats": [
                        {"v": "$78k", "l": "Median entry salary (US)"},
                        {"v": "12,400", "l": "Open roles right now"},
                    ],
                    "foot": "76% of CareerForge students land a role within 90 days of promotion",
                },
            },
        },
    ),
    (
        "data-scientist",
        {
            "title_override": "Data Scientist",
            "price_cents": 14900,
            "difficulty": "intermediate",
            "bullets": [
                {"text": "10 lessons · stats, experimentation, ML foundations, deployment", "included": True},
                {"text": "28 labs · A/B tests, feature engineering, model ops", "included": True},
                {"text": "Kaggle-grade capstone with peer + mentor review", "included": True},
                {"text": "Requires Data Analyst or equivalent foundation", "included": False},
            ],
            "metadata": {
                "level_label": "Level 3 · Intermediate",
                "lesson_count": 10,
                "lab_count": 28,
                "est_hours": 90,
                "est_weeks": 12,
                "accent_color": "#3a6ea3",
                "tags": ["stats", "ml"],
            },
        },
    ),
    (
        "genai-engineer",
        {
            "title_override": "GenAI Engineer",
            "price_cents": 19900,
            "difficulty": "advanced",
            "bullets": [
                {"text": "12 lessons · LLMs, RAG, evals, deployment, observability", "included": True},
                {"text": "24 labs · LangGraph agents, prompt eval, vector stores", "included": True},
                {"text": "Production capstone: ship an agent to real users", "included": True},
                {"text": "Mock interview with a working GenAI engineer", "included": True},
            ],
            "metadata": {
                "level_label": "Level 4 · Advanced",
                "lesson_count": 12,
                "lab_count": 24,
                "est_hours": 110,
                "est_weeks": 14,
                "accent_color": "#7C3AED",
                "tags": ["genai", "llm", "rag"],
            },
        },
    ),
]


async def _ensure_catalog_metadata(db: AsyncSession) -> int:
    """Stamp `bullets` + `metadata` on each known course slug.

    For courses that don't exist yet (e.g. data-scientist, genai-engineer),
    create them with sensible defaults so the catalog has a populated grid
    in dev. Title override + price + difficulty are also applied so the
    cards render accurately.
    """
    updated = 0
    for slug, spec in CATALOG_METADATA:
        course = (
            await db.execute(select(Course).where(Course.slug == slug))
        ).scalar_one_or_none()
        if course is None:
            course = Course(
                slug=slug,
                title=spec["title_override"],
                description=f"{spec['title_override']} career track.",
                is_published=True,
                difficulty=spec["difficulty"],
                price_cents=spec["price_cents"],
            )
            db.add(course)
            await db.flush()
        # Title + price + difficulty are authoritative from the seed; only
        # update fields that look like the model defaults so a hand-edited
        # course in the DB isn't clobbered.
        if course.title != spec["title_override"]:
            course.title = spec["title_override"]
        if course.price_cents != spec["price_cents"]:
            course.price_cents = spec["price_cents"]
        if course.difficulty != spec["difficulty"]:
            course.difficulty = spec["difficulty"]
        # Always overwrite bullets + metadata — they're catalog-card payload,
        # not user-authored content.
        course.bullets = list(spec["bullets"])
        course.metadata_ = dict(spec["metadata"])
        updated += 1
    await db.commit()
    log.info("seed.catalog.metadata", updated=updated)
    return updated


CATALOG_BUNDLES: list[tuple[str, str, str, int, list[str], dict]] = [
    (
        "data-career-arc",
        "Data Career Arc",
        "Python Developer → Data Analyst → Data Scientist. Save 30% vs buying tracks individually.",
        18900,
        ["python-developer", "data-analyst", "data-scientist"],
        {
            "level_label": "Bundle · Career arc",
            "savings_pct": 30,
            "accent_color": "#7C3AED",
            "ribbon_text": "Save 30%",
        },
    ),
    (
        "ai-engineer-arc",
        "AI Engineer Arc",
        "Python Developer + GenAI Engineer. Built for self-taught engineers pivoting into LLM work.",
        16900,
        ["python-developer", "genai-engineer"],
        {
            "level_label": "Bundle · AI Engineer",
            "savings_pct": 15,
            "accent_color": "#1D9E75",
        },
    ),
]


async def _ensure_catalog_bundles(db: AsyncSession) -> int:
    """Idempotent upsert of CATALOG_BUNDLES. Resolves slugs → course UUIDs at
    seed time so the bundle's `course_ids` is always valid.
    """
    inserted = 0
    for slug, title, description, price_cents, course_slugs, metadata in CATALOG_BUNDLES:
        existing = (
            await db.execute(select(CourseBundle).where(CourseBundle.slug == slug))
        ).scalar_one_or_none()
        # Resolve course slugs → UUID strings (skip any that don't exist yet).
        resolved: list[str] = []
        for cs in course_slugs:
            row = (
                await db.execute(select(Course.id).where(Course.slug == cs))
            ).scalar_one_or_none()
            if row is not None:
                resolved.append(str(row))
        if existing is None:
            db.add(CourseBundle(
                slug=slug,
                title=title,
                description=description,
                price_cents=price_cents,
                currency="INR",
                course_ids=resolved,
                metadata_=metadata,
                is_published=True,
                sort_order=inserted,
            ))
            inserted += 1
        else:
            existing.title = title
            existing.description = description
            existing.price_cents = price_cents
            existing.course_ids = resolved
            existing.metadata_ = metadata
            existing.is_published = True
    await db.commit()
    log.info("seed.catalog.bundles", inserted=inserted)
    return inserted


# --------------------------------------------------------------------------- #
# Top-level orchestration                                                     #
# --------------------------------------------------------------------------- #
async def _ensure_path_labs(
    db: AsyncSession, *, course: Course, demo_user: User
) -> int:
    """Idempotent: attach 2-3 labs to every lesson in `course` and seed
    one passing submission on the first lab so Path's lab tray renders
    real "1 of 3 complete" copy.

    Returns the number of new exercise rows inserted (for logging).
    """
    lessons_q = (
        select(Lesson)
        .where(Lesson.course_id == course.id, Lesson.is_deleted.is_(False))
        .order_by(Lesson.order)
    )
    lessons = list((await db.execute(lessons_q)).scalars().all())
    if not lessons:
        return 0

    LAB_BLUEPRINT: list[tuple[str, str, int, int]] = [
        # (suffix, description, points, order)
        ("Retry with exponential backoff",
         "Write a function that retries a flaky API call up to 3 times, "
         "doubling the wait each attempt.",
         50, 1),
        ("Rate-limit aware queue",
         "Build a small queue that throttles outbound requests to stay "
         "under a 10/min ceiling without dropping calls.",
         80, 2),
        ("Concurrent batch processor",
         "Fan out 50 prompts through asyncio.gather and collect results "
         "without losing ordering.",
         110, 3),
    ]

    inserted = 0
    # Seed labs across 10 lessons so the "current lesson window" the Path
    # service picks (lessons 8/9/10/11 for the demo user) always has labs.
    for lesson in lessons[:10]:
        for letter_idx, (suffix, desc, points, order) in enumerate(LAB_BLUEPRINT):
            label = f"Lab {chr(ord('A') + letter_idx)} · {suffix}"
            existing = (
                await db.execute(
                    select(Exercise).where(
                        Exercise.lesson_id == lesson.id,
                        Exercise.title == label,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            db.add(Exercise(
                lesson_id=lesson.id,
                title=label,
                description=desc,
                exercise_type="coding",
                difficulty="medium",
                pass_score=70,
                points=points,
                order=order,
            ))
            inserted += 1
    if inserted:
        await db.flush()
        log.info("seed.path_labs.created", count=inserted)

    # Mark the first lab on the FIRST lesson as passed by the demo user.
    first_lab = (
        await db.execute(
            select(Exercise)
            .where(Exercise.lesson_id == lessons[0].id)
            .order_by(Exercise.order)
        )
    ).scalars().first()
    if first_lab is not None:
        sub = (
            await db.execute(
                select(ExerciseSubmission).where(
                    ExerciseSubmission.student_id == demo_user.id,
                    ExerciseSubmission.exercise_id == first_lab.id,
                )
            )
        ).scalar_one_or_none()
        if sub is None:
            db.add(ExerciseSubmission(
                student_id=demo_user.id,
                exercise_id=first_lab.id,
                status="passed",
                score=85,
                code="def retry(fn): ...",
                feedback="Backoff logic looks clean — consider adding jitter.",
            ))
            await db.flush()
            log.info("seed.path_labs.first_passed", student=demo_user.email)
    return inserted


async def _ensure_proof_wall_submissions(
    db: AsyncSession, *, peers: list[User]
) -> int:
    """Two peer-shared submissions with high scores so the Path proof wall
    renders 2 cards.

    Idempotent: keys on (student_id, code-snippet hash). We need at least one
    Exercise to attach to — finds the first non-capstone exercise. Returns
    the number of new submissions added.
    """
    if len(peers) < 2:
        return 0
    ex = (
        await db.execute(
            select(Exercise)
            .where(Exercise.is_deleted.is_(False), Exercise.is_capstone.is_(False))
            .order_by(Exercise.order)
        )
    ).scalars().first()
    if ex is None:
        return 0

    proof_payload: list[tuple[User, str, int]] = [
        (
            peers[0],
            (
                "async def ask(prompt):\n"
                "    try:\n"
                "        resp = await client.messages.create(...)\n"
                "        return resp.content[0].text\n"
                "    except APIError:\n"
                "        return await retry(prompt)"
            ),
            87,
        ),
        (
            peers[1],
            (
                "class RateLimiter:\n"
                "    async def wait(self):\n"
                "        while self.full():\n"
                "            await asyncio.sleep(1)\n"
                "        return True"
            ),
            91,
        ),
    ]

    inserted = 0
    for peer, snippet, score in proof_payload:
        existing = (
            await db.execute(
                select(ExerciseSubmission).where(
                    ExerciseSubmission.student_id == peer.id,
                    ExerciseSubmission.exercise_id == ex.id,
                    ExerciseSubmission.shared_with_peers.is_(True),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        db.add(ExerciseSubmission(
            student_id=peer.id,
            exercise_id=ex.id,
            code=snippet,
            status="passed",
            score=score,
            feedback="Solid pattern — peer-worthy.",
            shared_with_peers=True,
            share_note="Felt like the cleanest version after 4 tries.",
        ))
        inserted += 1
    if inserted:
        await db.flush()
        log.info("seed.proof_wall.created", count=inserted)
    return inserted


async def _ensure_promotion_interviews(
    db: AsyncSession, *, demo_user: User, count: int = 1
) -> int:
    """Seed `count` completed practice interviews so the Promotion rung
    "2 practice interviews" reads as in-progress (not locked at 0/2).

    Defaults to 1 so the gate stays demonstrably "current" rather than
    auto-fired — we want demo users to SEE the locked state, then complete
    interviews to feel the unlock.
    """
    existing = (
        await db.execute(
            select(InterviewSession).where(
                InterviewSession.user_id == demo_user.id,
                InterviewSession.status == "completed",
            )
        )
    ).scalars().all()
    if len(existing) >= count:
        return 0
    needed = count - len(existing)
    now = _now()
    for i in range(needed):
        db.add(InterviewSession(
            user_id=demo_user.id,
            mode="behavioral",
            status="completed",
            target_role="Data Analyst",
            level="entry",
            overall_score=78.0,
            created_at=now - timedelta(days=2 + i),
        ))
    await db.flush()
    log.info("seed.promotion_interviews.created", count=needed)
    return needed


async def _ensure_promotion_skill_states(
    db: AsyncSession, *, demo_user: User, skills: dict[str, Skill]
) -> int:
    """Mark a couple of skills as `mastered` / `proficient` so the Path
    constellation has visible "done" / "current" stars (instead of every
    star reading "Upcoming").

    Targets the canonical production slugs (`python-basics`, `http-rest`,
    `python-oop`) — they live in the seeded skills graph and appear in the
    constellation's top-5 picks because they have the lowest difficulty.
    Falls back gracefully if a slug isn't present.
    """
    inserted_or_updated = 0
    targets = [
        ("python-basics", "mastered", 0.95),
        ("python-data-structures", "mastered", 0.9),
        ("http-rest", "proficient", 0.7),
        # Synthetic slugs from the demo seed's own _ensure_skills() — kept
        # so the Today screen's current_focus query still returns one of
        # these (which is what powers the "APIs" focus card).
        ("apis", "mastered", 0.9),
        ("async_python", "proficient", 0.7),
    ]

    # Pull every real Skill row keyed by slug so we can find canonical
    # production skills as well as the synthetic ones in the demo seed.
    all_skills_by_slug: dict[str, Skill] = {
        s.slug: s for s in (await db.execute(select(Skill))).scalars().all()
    }

    for slug, level, conf in targets:
        skill = skills.get(slug) or all_skills_by_slug.get(slug)
        if skill is None:
            continue
        state = (
            await db.execute(
                select(UserSkillState).where(
                    UserSkillState.user_id == demo_user.id,
                    UserSkillState.skill_id == skill.id,
                )
            )
        ).scalar_one_or_none()
        if state is None:
            db.add(UserSkillState(
                user_id=demo_user.id,
                skill_id=skill.id,
                mastery_level=level,
                confidence=conf,
                last_touched_at=_now() - timedelta(hours=2),
            ))
            inserted_or_updated += 1
        else:
            if state.mastery_level != level:
                state.mastery_level = level
                state.confidence = conf
                inserted_or_updated += 1
    if inserted_or_updated:
        await db.flush()
        log.info("seed.skill_states.updated", count=inserted_or_updated)
    return inserted_or_updated


async def seed(db: AsyncSession) -> None:
    log.info("seed.today_demo.start", email=DEMO_EMAIL)

    demo_user = await _ensure_user(db, email=DEMO_EMAIL, full_name=DEMO_NAME)
    peer_users = [
        await _ensure_user(db, email=email, full_name=name)
        for email, name in PEER_USERS
    ]

    # Goal contract — drives header, milestone label, days_remaining.
    await GoalContractService(db).upsert_for_user(
        demo_user,
        GoalContractCreate(
            motivation="career_switch",
            deadline_months=4,
            success_statement=(
                "Land a Data Analyst role by shipping a portfolio of three "
                "production-quality projects and passing two technical screens."
            ),
            weekly_hours="6-10",
            target_role="Data Analyst",
        ),
    )

    # Courses, lessons, enrollments, completed progress.
    course_objs: dict[str, Course] = {}
    for slug, title, lesson_count, completed in COURSES:
        course = await _ensure_course(
            db, slug=slug, title=title, lesson_count=lesson_count
        )
        course_objs[slug] = course
        await _ensure_enrollment(db, student=demo_user, course=course)
        await _mark_lessons_completed(
            db, student=demo_user, course=course, count=completed
        )

    # Anchor lesson for non-curriculum exercises (capstone, hard ex).
    anchor_lesson = (await db.execute(
        select(Lesson)
        .where(Lesson.course_id == course_objs["python-foundations"].id)
        .order_by(Lesson.order).limit(1)
    )).scalar_one()

    # Skills + current focus — APIs touched last so it wins the focus query.
    skills = await _ensure_skills(db)
    base = _now() - timedelta(hours=6)
    await _touch_skill(db, user=demo_user, skill=skills["error_handling"],
                       last_touched=base)
    await _touch_skill(db, user=demo_user, skill=skills["async_python"],
                       last_touched=base + timedelta(hours=1))
    await _touch_skill(db, user=demo_user, skill=skills["apis"],
                       last_touched=_now())

    # Capstone, hard-exercise pass, misconception (drives micro_wins).
    await _ensure_capstone(db, demo_user=demo_user, anchor_lesson=anchor_lesson)
    await _ensure_hard_exercise_pass(
        db, demo_user=demo_user, anchor_lesson=anchor_lesson
    )
    await _ensure_misconception(db, demo_user=demo_user)

    # Prior 13 sessions; the live aggregator opens #14 on the next request.
    await _ensure_prior_sessions(db, user=demo_user, count=13)

    # 7 due SRS cards.
    await _ensure_srs_cards(db, user=demo_user)

    # Today's intention text.
    await upsert_today(
        db, user_id=demo_user.id,
        text="Ship a draft of the CLI AI tool capstone and review 5 SRS cards.",
    )

    # Cohort feed: 5 events across 3 peers, ≥2 level_up promotions today.
    await _ensure_cohort_events(db, peers=peer_users)

    # Notebook: 4 entries (1 graduated, 3 in-review) across 3 sources.
    await _ensure_notebook_entries(db, user=demo_user)

    # Readiness workspace: 2 autopsies, 1 ready kit, ~12 workspace events.
    autopsies = await _ensure_autopsies(db, user=demo_user)
    strongest = autopsies[0] if autopsies else None
    await _ensure_application_kit(db, user=demo_user, autopsy=strongest)
    await _ensure_workspace_events(db, user=demo_user)

    # Catalog: rich bullets + metadata on the 4 canonical career-track courses,
    # plus 2 multi-course bundles. Idempotent rerun-safe.
    await _ensure_catalog_metadata(db)
    await _ensure_catalog_bundles(db)

    # Path screen demo data — 2-3 labs per lesson on the active course, one
    # passing submission so the lab tray reads "1 of 3 complete", and two
    # peer-shared submissions for the proof wall.
    await _ensure_path_labs(
        db, course=course_objs["python-foundations"], demo_user=demo_user
    )
    await _ensure_proof_wall_submissions(db, peers=peer_users)

    # Promotion screen demo data — 1 completed practice interview (so the
    # "2 practice interviews" rung reads as in-progress, not locked at 0/2)
    # and 2 mastered/proficient skill states (so the constellation has
    # visible progress instead of all-upcoming).
    await _ensure_promotion_interviews(db, demo_user=demo_user, count=1)
    await _ensure_promotion_skill_states(db, demo_user=demo_user, skills=skills)

    log.info("seed.today_demo.done", email=DEMO_EMAIL)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await seed(session)
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
