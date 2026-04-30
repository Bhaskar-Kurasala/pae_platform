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
    },
)
