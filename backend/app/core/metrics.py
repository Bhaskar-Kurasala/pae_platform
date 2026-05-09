"""D19.1 CP2 — metrics substrate.

Single chokepoint for all Prometheus metric registration on the
platform. Replaces the no-op shim that previously lived in
``app/agents/primitives/metrics.py`` (which now re-exports a subset
of these symbols for back-compat).

Substrate guarantees per D19.1 architectural decisions:

  D-C cardinality discipline — enforced at registration time.
    ``register_*`` rejects label names from a fixed denylist
    (``user_id``, ``session_id``, ``trace_id``, ``email``, etc.).
    Not a guideline; a hard constraint. Caught at boot, not at log
    volume. See ``_DENYLISTED_LABELS``.

  D-D naming convention — enforced at registration time.
    Metric names must match
    ``{service}_{component}_{measurement}[_{unit}]`` with
    ``service=aicareeros``. Names that don't match are rejected with
    a clear error. ``_seconds`` for durations (Prometheus convention),
    ``_bytes`` for sizes, ``_inr`` for rupees, count-style metrics
    omit the unit suffix. See ``_NAME_REGEX`` and the helper.

  Single registry — every metric registers against
    ``REGISTRY`` (an explicit ``CollectorRegistry`` instance, NOT
    the prometheus_client default). Avoids cross-test bleed when
    ``importlib.reload`` is used; lets the ``/metrics`` endpoint
    and the cardinality linter test work against a known graph.

The 9 canonical D-D metrics are registered at module import; the 5
supplementary internal metrics (agent eval score, tool call duration,
memory recall, memory writes, inter-agent depth) follow under the
same naming rules.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)

log = structlog.get_logger().bind(layer="metrics")

# ---------------------------------------------------------------------------
# Substrate primitives — registry, naming convention, cardinality denylist
# ---------------------------------------------------------------------------

REGISTRY = CollectorRegistry(auto_describe=True)
"""Single explicit registry. The /metrics endpoint scrapes this one."""

_SERVICE_PREFIX = "aicareeros"

# D-D shape: {service}_{component}_{measurement}[_{unit}]
# Components are not enforced by the regex (drift would surface first
# at dashboard authoring time, not at boot), but the {service}_ prefix
# IS enforced — that's the load-bearing convention for namespacing
# vs. third-party metrics that may share the registry in future
# multi-service deployments.
_NAME_REGEX = re.compile(rf"^{_SERVICE_PREFIX}_[a-z][a-z0-9_]*$")

# Cardinality denylist — D-C enforcement.
# Labels that combine with naturally-unbounded values (user IDs, trace
# IDs, free-form text) blow up the metric backend. We refuse to
# register a metric with any of these labels at boot. The structlog
# substrate (CP1) is the right place for those identifiers — metrics
# carry aggregates, logs carry per-event detail, and trace spans
# carry per-request causality.
_DENYLISTED_LABELS: frozenset[str] = frozenset(
    {
        "user_id",
        "userid",
        "session_id",
        "sessionid",
        "trace_id",
        "traceid",
        "request_id",
        "requestid",
        "email",
        "username",
        "ip",
        "ip_address",
        "full_name",
        "name",
    }
)


class MetricRegistrationError(ValueError):
    """Raised when a metric registration violates D-C or D-D."""


def _validate_metric(name: str, labelnames: tuple[str, ...]) -> None:
    """D-C + D-D enforcement gate. Called by every register_* helper."""
    if not _NAME_REGEX.match(name):
        raise MetricRegistrationError(
            f"Metric name {name!r} violates D-D naming convention. "
            f"Required shape: {_SERVICE_PREFIX}_<component>_<measurement>"
            f"[_<unit>]; lowercase + underscores only."
        )
    bad = sorted({label for label in labelnames if label.lower() in _DENYLISTED_LABELS})
    if bad:
        raise MetricRegistrationError(
            f"Metric {name!r} would register denylisted high-cardinality "
            f"label(s) {bad}. Cardinality discipline is non-negotiable "
            f"(D-C). Use structlog contextvars (request_id/trace_id/"
            f"user_id) for per-event correlation; metrics carry "
            f"aggregates only. See app/core/metrics.py _DENYLISTED_LABELS."
        )


def register_counter(
    name: str,
    documentation: str,
    labelnames: tuple[str, ...] = (),
) -> Counter:
    """Register a Counter against REGISTRY. D-D / D-C enforced."""
    _validate_metric(name, labelnames)
    return Counter(
        name=name,
        documentation=documentation,
        labelnames=labelnames,
        registry=REGISTRY,
    )


def register_histogram(
    name: str,
    documentation: str,
    labelnames: tuple[str, ...] = (),
    buckets: tuple[float, ...] | None = None,
) -> Histogram:
    """Register a Histogram against REGISTRY. D-D / D-C enforced.

    ``buckets`` defaults to prometheus_client's standard latency
    buckets when omitted (good for *_seconds metrics); pass an
    explicit tuple for custom shapes (e.g. cost-in-INR distributions).
    """
    _validate_metric(name, labelnames)
    kwargs: dict[str, Any] = {
        "name": name,
        "documentation": documentation,
        "labelnames": labelnames,
        "registry": REGISTRY,
    }
    if buckets is not None:
        kwargs["buckets"] = buckets
    return Histogram(**kwargs)


def register_gauge(
    name: str,
    documentation: str,
    labelnames: tuple[str, ...] = (),
) -> Gauge:
    """Register a Gauge against REGISTRY. D-D / D-C enforced."""
    _validate_metric(name, labelnames)
    return Gauge(
        name=name,
        documentation=documentation,
        labelnames=labelnames,
        registry=REGISTRY,
    )


# ---------------------------------------------------------------------------
# Canonical D-D metrics (9) — the launch-tier set
# ---------------------------------------------------------------------------

# API
API_REQUESTS = register_counter(
    "aicareeros_api_requests",
    "Count of HTTP requests served by the API.",
    labelnames=("endpoint", "method", "status_code"),
)
API_REQUEST_DURATION_SECONDS = register_histogram(
    "aicareeros_api_request_duration_seconds",
    "Request latency in seconds, observed at the API gateway.",
    labelnames=("endpoint", "method"),
)

# Agent
AGENT_INVOCATIONS = register_counter(
    "aicareeros_agent_invocations",
    "Count of agent run() invocations by agent and outcome.",
    labelnames=("agent_id", "outcome"),
)
AGENT_INVOCATION_DURATION_SECONDS = register_histogram(
    "aicareeros_agent_invocation_duration_seconds",
    "Wall-clock time of a single agent run() in seconds.",
    labelnames=("agent_id",),
)
AGENT_COST_INR_TOTAL = register_counter(
    "aicareeros_agent_cost_inr_total",
    "Sum of per-invocation cost_inr written to agent_invocation_log.",
    labelnames=("agent_id",),
)

# DB
DB_POOL_CONNECTIONS_IN_USE = register_gauge(
    "aicareeros_db_pool_connections_in_use",
    "Current count of connections checked out of the SQLAlchemy pool.",
)
DB_QUERY_DURATION_SECONDS = register_histogram(
    "aicareeros_db_query_duration_seconds",
    "Per-query wall time, classified by SQL DML verb.",
    labelnames=("query_type",),
)

# Celery
CELERY_TASKS = register_counter(
    "aicareeros_celery_tasks",
    "Count of Celery task executions by task and outcome.",
    labelnames=("task_name", "outcome"),
)

# Auth
AUTH_EVENTS = register_counter(
    "aicareeros_auth_events",
    "Count of authentication events (signup/login/logout/failure).",
    labelnames=("event_type",),
)


# ---------------------------------------------------------------------------
# Supplementary metrics — agent-internal observability the codebase
# already emits via the legacy shim. Renamed to D-D shape; symbol
# names preserved for back-compat re-export below.
# ---------------------------------------------------------------------------

AGENT_EVAL_SCORE = register_histogram(
    "aicareeros_agent_eval_score",
    "Critic score returned for an agent attempt (0.0-1.0).",
    labelnames=("agent_id",),
    # Eval scores are bounded [0, 1] — small linear bucket set.
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
TOOL_CALL_DURATION_SECONDS = register_histogram(
    "aicareeros_agent_tool_call_duration_seconds",
    "Wall time spent inside a single tool execution.",
    labelnames=("tool", "status"),
)
MEMORY_RECALL_HITS = register_counter(
    "aicareeros_agent_memory_recall_hits",
    "Number of memory rows returned by recall().",
    labelnames=("mode",),
)
MEMORY_RECALL_DURATION_SECONDS = register_histogram(
    "aicareeros_agent_memory_recall_duration_seconds",
    "Wall time of a recall() call.",
    labelnames=("mode",),
)
MEMORY_WRITES_TOTAL = register_counter(
    "aicareeros_agent_memory_writes_total",
    "Number of memories written to agent_memory.",
    labelnames=("scope",),
)
INTER_AGENT_CALL_DEPTH = register_histogram(
    "aicareeros_agent_inter_agent_call_depth",
    "Maximum chain depth observed for an outermost execute().",
    # Depth is 1..agent_call_max_depth (default 5). Pin buckets so
    # the histogram is meaningful at low cardinality.
    buckets=(1, 2, 3, 4, 5, 6, 7, 8, 10),
)


# ---------------------------------------------------------------------------
# Helpers exposed to the rest of the codebase
# ---------------------------------------------------------------------------


def render_latest() -> tuple[bytes, str]:
    """Render REGISTRY in Prometheus text exposition format.

    Returns (body, content_type) so the FastAPI route at /metrics can
    return them directly. Pinned to the text exposition format used
    by every Prometheus-compatible backend; switch to OpenMetrics
    later if the backend choice (CP5) requires it.
    """
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


__all__ = [
    "REGISTRY",
    "MetricRegistrationError",
    "register_counter",
    "register_histogram",
    "register_gauge",
    "render_latest",
    # Canonical D-D metrics
    "API_REQUESTS",
    "API_REQUEST_DURATION_SECONDS",
    "AGENT_INVOCATIONS",
    "AGENT_INVOCATION_DURATION_SECONDS",
    "AGENT_COST_INR_TOTAL",
    "DB_POOL_CONNECTIONS_IN_USE",
    "DB_QUERY_DURATION_SECONDS",
    "CELERY_TASKS",
    "AUTH_EVENTS",
    # Supplementary
    "AGENT_EVAL_SCORE",
    "TOOL_CALL_DURATION_SECONDS",
    "MEMORY_RECALL_HITS",
    "MEMORY_RECALL_DURATION_SECONDS",
    "MEMORY_WRITES_TOTAL",
    "INTER_AGENT_CALL_DEPTH",
]
