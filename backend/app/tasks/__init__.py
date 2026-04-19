"""Celery task modules.

Importing this package registers all task modules with the Celery app so that
`celery -A app.core.celery_app` can discover them.
"""

from app.tasks import (  # noqa: F401
    growth_snapshots,
    inactivity_sweep,
    weekly_letters,
    weekly_review,
)
