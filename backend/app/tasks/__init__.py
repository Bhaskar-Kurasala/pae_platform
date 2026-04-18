"""Celery task modules.

Importing this package registers all task modules with the Celery app so that
`celery -A app.core.celery_app` can discover them.
"""

from app.tasks import growth_snapshots, weekly_letters  # noqa: F401
