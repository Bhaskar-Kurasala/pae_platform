"""D19.1 CP1.3 — Celery auto-propagation of structlog correlation IDs.

The substrate guarantees: a task enqueued from a request context inherits
the request's correlation IDs (request_id, trace_id, user_id, agent_id,
session_id, cohort_id) without the call site having to pass them. The
task's structlog context is restored at dequeue and torn down at
completion so a long-running worker process can never leak context
between tasks.

Mechanism:

  1. ``CorrelatedTask`` — a ``celery.Task`` subclass that overrides
     ``apply_async`` to read the *enqueueing* process's current
     structlog contextvars and merge them into the task's headers
     (Celery preserves headers across the broker round-trip when
     ``task_serializer='json'``, which celery_app.py sets).

  2. ``_bind_task_context`` — wired to ``task_prerun``. Reads the
     headers off the task request and binds them to structlog
     contextvars in the worker process. If no upstream IDs are
     present (beat-scheduled task, manual ``send_task`` from a CLI,
     eager-mode test without a request) we mint a fresh trace_id at
     task entry and tag ``trace_origin="task"`` so downstream logs
     announce the lack of upstream correlation.

  3. ``_unbind_task_context`` — wired to ``task_postrun``. Clears the
     keys we own. We use ``unbind_contextvars`` (not
     ``clear_contextvars``) so any contextvars bound by the task body
     itself for telemetry survive long enough for the postrun signal
     to log them, and then are cleared by the next task's prerun.

The ``@register`` step at module import wires the signals exactly
once. Importing this module from ``celery_app.py`` is enough.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from celery import Task
from celery.signals import task_postrun, task_prerun

# Header keys we ship across the broker. Mirrors the structlog
# contextvars set by RequestIDMiddleware (CP1.1) and the auth dep
# (CP1.2a) and BaseAgent.run (CP1.2c). cohort_id and session_id are
# accepted defensively even though no upstream binds them yet —
# cheap to ship; ready when CP1's downstream consumers light them up.
_PROPAGATED_KEYS: tuple[str, ...] = (
    "request_id",
    "trace_id",
    "user_id",
    "agent_id",
    "session_id",
    "cohort_id",
)


class CorrelatedTask(Task):
    """Celery Task base that auto-propagates structlog correlation IDs.

    Override of ``apply_async`` is the only call site that runs in the
    *enqueueing* process. ``.delay()`` is a thin wrapper around
    ``apply_async`` in stock Celery, so propagation rides under both
    APIs without any call-site changes.
    """

    abstract = True

    def apply_async(  # type: ignore[override]
        self,
        args: Any = None,
        kwargs: Any = None,
        task_id: str | None = None,
        producer: Any = None,
        link: Any = None,
        link_error: Any = None,
        shadow: str | None = None,
        **options: Any,
    ) -> Any:
        # Read the enqueueing process's structlog context. When called
        # from a request that came through RequestIDMiddleware these
        # are set; otherwise the dict is empty and propagation no-ops
        # cleanly.
        ctx = structlog.contextvars.get_contextvars() or {}
        propagated = {
            key: str(value)
            for key, value in ctx.items()
            if key in _PROPAGATED_KEYS and value is not None
        }
        if propagated:
            existing_headers = options.get("headers") or {}
            # Don't clobber explicit headers a caller may have set;
            # propagation is additive.
            merged = {**propagated, **existing_headers}
            options["headers"] = merged
        return super().apply_async(
            args=args,
            kwargs=kwargs,
            task_id=task_id,
            producer=producer,
            link=link,
            link_error=link_error,
            shadow=shadow,
            **options,
        )


def _extract_propagated(task: Any) -> dict[str, str]:
    """Pull our header keys off the task's request envelope.

    Celery exposes incoming headers via ``task.request.headers`` (when
    the broker preserved them) or stuffs them under ``task.request``
    attributes for some serializers. We read both shapes defensively.
    """
    headers = getattr(getattr(task, "request", None), "headers", None) or {}
    if isinstance(headers, dict):
        return {
            key: str(headers[key])
            for key in _PROPAGATED_KEYS
            if key in headers and headers[key] is not None
        }
    return {}


def _bind_task_context(
    sender: Any = None,
    task_id: str | None = None,
    task: Any = None,
    args: Any = None,
    kwargs: Any = None,
    **_: Any,
) -> None:
    """task_prerun handler — restore structlog context inside the worker."""
    propagated = _extract_propagated(task or sender)

    if propagated:
        structlog.contextvars.bind_contextvars(**propagated)
        return

    # No upstream context — task is beat-scheduled or manually invoked.
    # Mint a fresh trace_id so log lines from this task are still
    # correlatable, and tag trace_origin="task" so an operator grepping
    # for a missing upstream knows there isn't one. Keep request_id
    # unbound to make the absence obvious in the JSON.
    fresh_trace_id = uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(
        trace_id=fresh_trace_id,
        trace_origin="task",
    )


def _unbind_task_context(
    sender: Any = None,
    task_id: str | None = None,
    task: Any = None,
    state: str | None = None,
    **_: Any,
) -> None:
    """task_postrun handler — clear our keys so the next task starts fresh.

    D19.1 CP2 — also increments aicareeros_celery_tasks with the
    task_name + outcome labels. ``state`` is Celery's task state
    string (SUCCESS / FAILURE / RETRY / REVOKED); we map to a 3-value
    outcome enum for cardinality discipline (the raw state strings
    work too, but normalising guards against future Celery version
    drift introducing new states).
    """
    # Determine task name + outcome before touching contextvars so a
    # crash in the metric emit doesn't leave stale context bound.
    task_name = "unknown"
    if task is not None:
        task_name = getattr(task, "name", None) or str(task)
    elif sender is not None:
        task_name = getattr(sender, "name", None) or str(sender)

    if state == "SUCCESS":
        outcome = "success"
    elif state in ("FAILURE", "REVOKED"):
        outcome = "error"
    elif state == "RETRY":
        outcome = "retry"
    else:
        outcome = "other"

    try:
        from app.core.metrics import CELERY_TASKS

        CELERY_TASKS.labels(task_name=task_name, outcome=outcome).inc()
    except Exception:  # noqa: BLE001
        # Telemetry never load-bearing for task correctness.
        pass

    structlog.contextvars.unbind_contextvars(
        *_PROPAGATED_KEYS, "trace_origin"
    )


def register_celery_logging_signals() -> None:
    """Wire prerun/postrun signal handlers exactly once.

    Idempotent: Celery's signal connect short-circuits a duplicate
    connection. Safe to call from multiple boot paths (web process
    importing celery_app, worker process boot).
    """
    task_prerun.connect(_bind_task_context, weak=False)
    task_postrun.connect(_unbind_task_context, weak=False)


# Wire on module import. The import in celery_app.py is the only
# entry point we need.
register_celery_logging_signals()
