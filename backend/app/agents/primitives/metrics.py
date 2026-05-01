"""Lightweight metrics shim for the Agentic OS primitives.

Designed so call sites can be instrumented today without adding the
`prometheus_client` dependency. When you're ready to flip to real
Prometheus, replace the `_Counter` / `_Histogram` no-op classes here
with thin wrappers around `prometheus_client.Counter` / `Histogram`
and add the `/metrics` endpoint — call sites do not change.

Exposed symbols (stable contract):

    metrics.AGENT_EXECUTIONS_TOTAL.labels(agent="…").inc()
    metrics.AGENT_EVAL_SCORE_HISTOGRAM.labels(agent="…").observe(0.82)
    metrics.TOOL_CALL_DURATION_MS.labels(tool="…").observe(123)
    metrics.MEMORY_RECALL_HITS.labels(mode="…").inc(n)
    metrics.MEMORY_RECALL_DURATION_MS.labels(mode="…").observe(45)
    metrics.MEMORY_WRITES_TOTAL.labels(scope="…").inc()
    metrics.INTER_AGENT_CALL_DEPTH.observe(3)

All operations are O(1), non-blocking, and currently no-ops. Each shim
also emits a structlog `metrics.observe` / `metrics.inc` line at debug
level so you can grep for spikes during dev even before Prometheus
lands.
"""

from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger().bind(layer="metrics")


class _Counter:
    """No-op counter that mimics prometheus_client.Counter API."""

    def __init__(self, name: str, description: str, labelnames: tuple[str, ...] = ()) -> None:
        self._name = name
        self._description = description
        self._labelnames = labelnames
        self._labels: dict[str, str] = {}

    def labels(self, **kwargs: str) -> "_Counter":
        # Returns a new instance carrying the labels — same shape as
        # prometheus_client. No-op binding so call sites are stable.
        c = _Counter(self._name, self._description, self._labelnames)
        c._labels = {**self._labels, **kwargs}
        return c

    def inc(self, amount: float = 1.0) -> None:
        log.debug("metrics.inc", metric=self._name, amount=amount, **self._labels)


class _Histogram:
    """No-op histogram. observe() drops the value into a debug log line."""

    def __init__(self, name: str, description: str, labelnames: tuple[str, ...] = ()) -> None:
        self._name = name
        self._description = description
        self._labelnames = labelnames
        self._labels: dict[str, str] = {}

    def labels(self, **kwargs: str) -> "_Histogram":
        h = _Histogram(self._name, self._description, self._labelnames)
        h._labels = {**self._labels, **kwargs}
        return h

    def observe(self, value: float) -> None:
        log.debug("metrics.observe", metric=self._name, value=value, **self._labels)


# ── Stable metric names (don't rename without updating dashboards) ──────

AGENT_EXECUTIONS_TOTAL = _Counter(
    "agent_executions_total",
    "Count of agent execute() invocations.",
    labelnames=("agent", "status"),
)
AGENT_EVAL_SCORE_HISTOGRAM = _Histogram(
    "agent_eval_score",
    "Critic score returned for an agent attempt.",
    labelnames=("agent",),
)
TOOL_CALL_DURATION_MS = _Histogram(
    "tool_call_duration_ms",
    "Time spent inside a single tool execution.",
    labelnames=("tool", "status"),
)
MEMORY_RECALL_HITS = _Counter(
    "memory_recall_hits",
    "Number of memory rows returned by recall().",
    labelnames=("mode",),
)
MEMORY_RECALL_DURATION_MS = _Histogram(
    "memory_recall_duration_ms",
    "Wall time of a recall() call.",
    labelnames=("mode",),
)
MEMORY_WRITES_TOTAL = _Counter(
    "memory_writes_total",
    "Number of memories written to agent_memory.",
    labelnames=("scope",),
)
INTER_AGENT_CALL_DEPTH = _Histogram(
    "inter_agent_call_depth",
    "Maximum chain depth observed for an outermost execute().",
)


__all__ = [
    "AGENT_EXECUTIONS_TOTAL",
    "AGENT_EVAL_SCORE_HISTOGRAM",
    "TOOL_CALL_DURATION_MS",
    "MEMORY_RECALL_HITS",
    "MEMORY_RECALL_DURATION_MS",
    "MEMORY_WRITES_TOTAL",
    "INTER_AGENT_CALL_DEPTH",
]


def _ensure_unused() -> Any:  # pragma: no cover
    """Reference symbols so an aggressive linter doesn't strip them."""
    return [
        AGENT_EXECUTIONS_TOTAL,
        AGENT_EVAL_SCORE_HISTOGRAM,
        TOOL_CALL_DURATION_MS,
        MEMORY_RECALL_HITS,
        MEMORY_RECALL_DURATION_MS,
        MEMORY_WRITES_TOTAL,
        INTER_AGENT_CALL_DEPTH,
    ]
