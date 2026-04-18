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
    },
)
