from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks",
        "app.tasks.growth_snapshots",
        "app.tasks.weekly_letters",
        "app.tasks.weekly_review",
        "app.tasks.inactivity_sweep",
        "app.tasks.risk_scoring",
        "app.tasks.outreach_automation",
        "app.tasks.refresh_student_daily_cost",
        # Agentic OS — concrete body for the proactive primitive's
        # task name. Registered as a normal Celery task; beat
        # entries built by `register_proactive_schedules` (below)
        # target this name.
        "app.tasks.proactive_runner",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "growth-snapshots-weekly": {
            "task": "app.tasks.growth_snapshots.build_weekly_snapshots",
            # Sunday 00:00 UTC — end of the week we're snapshotting.
            "schedule": crontab(minute=0, hour=0, day_of_week=0),
        },
        "weekly-letters": {
            "task": "app.tasks.weekly_letters.send_weekly_letters",
            # Sunday 01:00 UTC — 1h after snapshots land.
            "schedule": crontab(minute=0, hour=1, day_of_week=0),
        },
        "weekly-review-quiz": {
            "task": "app.tasks.weekly_review.assemble_weekly_reviews",
            # Sunday 02:00 UTC — 1h after weekly letters (P3 3B #93).
            "schedule": crontab(minute=0, hour=2, day_of_week=0),
        },
        "inactivity-sweep": {
            "task": "app.tasks.inactivity_sweep.sweep_inactive_students",
            # Monday 09:00 UTC — start of week (P3 3B #152).
            "schedule": crontab(minute=0, hour=9, day_of_week=1),
        },
        # F1 — nightly student risk scoring. 03:00 UTC = off-peak for
        # Neon (Asia is asleep, US is mid-evening), and 6 hours before
        # the inactivity sweep so admin's morning queue has fresh
        # signals.
        "risk-scoring-nightly": {
            "task": "app.tasks.risk_scoring.score_all_users",
            "schedule": crontab(minute=0, hour=3),
        },
        # F9 — nightly outreach automation. 09:00 UTC = 6 hours after
        # F1's risk scoring at 03:00 UTC. The window gives the operator
        # time to sanity-check the morning queue on /admin before
        # automated emails fly out. Default is dry-run; real sends
        # require ENV=production AND OUTREACH_AUTO_SEND=1 (gated in
        # the service to avoid accidental fan-out).
        "outreach-automation-nightly": {
            "task": "app.tasks.outreach_automation.run_nightly_outreach",
            "schedule": crontab(minute=0, hour=9),
        },
        # D9 / Pass 3f §D.1 — refresh per-student daily cost rollup
        # every 60 seconds. CONCURRENTLY refresh; cost ceiling
        # enforcement reads this view via _compute_today_cost_inr.
        # 60s drift = ~5% over-grant max at 50 INR/day ceiling, which
        # is acceptable for a soft cap (Pass 3f §D.1 reasoning).
        "refresh-student-daily-cost": {
            "task": "app.tasks.refresh_student_daily_cost.refresh",
            "schedule": 60.0,  # seconds; Celery accepts float for sub-minute
        },
    },
)


# ── Agentic OS boot-order hook ──────────────────────────────────────
#
# Beat reads `celery_app.conf.beat_schedule` once at scheduler boot
# and ignores anything registered afterward. So the order is fixed:
#
#   1. Import agentic agent modules — fires `__init_subclass__` and
#      any `@proactive(...)` decorators inside them, populating the
#      module-level `_proactive_schedules` list.
#   2. `register_proactive_schedules(celery_app)` merges those
#      entries into `celery_app.conf.beat_schedule`.
#   3. Celery beat starts and reads the merged dict.
#
# A swallowed import error in step 1 means a proactive flow silently
# stops working. `load_agentic_agents` re-raises with module
# context, so any breakage shows up in the beat boot logs as
# `AgenticAgentImportError: failed to import agent module ...`.
#
# Wrapping in a try/except here would defeat the loud-fail
# contract — let the exception propagate. Beat will refuse to start
# (which is what we want; a partial agent set is worse than no
# agents).
def _boot_agentic_os() -> None:
    """Wire the agentic OS into Celery beat at module import time.

    Called once when this module is imported (which Celery itself
    does on worker / beat boot). The function is idempotent:
    re-entry is safe because `load_agentic_agents` uses
    `importlib.import_module` (cached) and
    `register_proactive_schedules` merges into the existing dict.
    """
    from app.agents._agentic_loader import load_agentic_agents
    from app.agents.primitives.proactive import register_proactive_schedules

    load_agentic_agents()
    register_proactive_schedules(celery_app)


# INTENTIONALLY UNWRAPPED — DO NOT add try/except around this call.
#
# A swallowed import error here means a proactive flow silently
# stops working in prod and nobody notices for a week. The
# loud-fail contract is described in `_agentic_loader.py` and the
# trace-semantics section of `AGENTIC_OS.md`.
#
# If a "wrap this for resilience" instinct fires while reading this,
# read the conventions doc first. Resilience here is wrong: a partial
# agent set is worse than no agents, and we need beat to refuse to
# start when an agent module is broken.
_boot_agentic_os()


# D9 / Pass 3g §H.3 — eager-load the safety primitive at WORKER process
# init, not at module import.
#
# Why worker_process_init and not _boot_agentic_os: Celery forks a
# pool of worker processes, and each fork copies module-imported state
# but NOT lazily-initialized resources. Loading Presidio at module
# import would burn ~750 MB × N workers in the parent process AND
# leak that copy into every fork. Loading at worker_process_init
# means each worker pays the cost once, in its own address space,
# producing a predictable per-worker memory profile.
#
# The launch-blocker for D16 (interrupt_agent on Celery) requires this
# to be wired before D16 deploys; tracked at
# docs/followups/celery-safety-memory-bump.md.
from celery.signals import worker_process_init  # noqa: E402


@worker_process_init.connect
def _eager_load_safety_in_worker(**_kwargs: object) -> None:
    """Load Presidio + spaCy en_core_web_lg in this worker process.

    Same pattern as FastAPI's lifespan: pay the load cost at startup
    so the first task doesn't surprise an operator with a slow
    response. Predictable memory profile > fast cold-start.

    Fail-soft: a missing Presidio install logs but doesn't kill the
    worker. The agentic_base safety helpers also fall back gracefully
    when the gate isn't available.
    """
    try:
        from app.agents.primitives.safety import get_default_gate

        get_default_gate()
    except Exception as exc:  # noqa: BLE001
        # Worker keeps booting without the safety primitive.
        # Production deployments should have Presidio installed; dev
        # / test environments without it just lose safety scans.
        import structlog

        structlog.get_logger().warning(
            "celery.worker.safety_gate_load_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
