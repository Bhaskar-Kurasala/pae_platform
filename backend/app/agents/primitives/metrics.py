"""Agent-primitives metrics shim — D19.1 CP2 update.

Historically this module was a pure no-op shim authored to give the
agent primitives stable instrumentation symbols *before* the
prometheus_client dependency landed. CP2 replaces those no-ops with
real metrics registered against the canonical ``CollectorRegistry`` in
``app/core/metrics.py``.

To keep the 18 existing call sites stable across the migration, this
module re-exports the legacy symbol names and provides two thin
millisecond → second adapters so call sites that previously called
``observe(duration_ms)`` keep working without edit. The Prometheus
metric they actually populate is the new ``_seconds``-suffixed
histogram (D-D convention), so dashboards and queries see the right
unit even though the call-site contract is unchanged.

When/why to use which symbol:

  * Existing primitive code (tools.py, memory.py, evaluation.py,
    communication.py) — keep importing from here. No edits needed.
  * New code anywhere — import directly from ``app.core.metrics``.
    The canonical symbols there have ``_SECONDS`` suffixes and accept
    seconds directly; no implicit conversion.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.core import metrics as _metrics

log = structlog.get_logger().bind(layer="metrics")


class _MillisecondHistogramAdapter:
    """Adapter so legacy callers can keep passing ``duration_ms``.

    Wraps a real prometheus_client Histogram (or a labels()-bound
    child). ``observe(duration_ms)`` divides by 1000 before delegating
    so the underlying metric — named ``..._seconds`` per D-D — gets
    the unit it claims to carry. ``labels(**kwargs)`` returns a new
    adapter wrapping the labels()-bound child.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def labels(self, **kwargs: str) -> "_MillisecondHistogramAdapter":
        return _MillisecondHistogramAdapter(self._inner.labels(**kwargs))

    def observe(self, value_ms: float) -> None:
        self._inner.observe(value_ms / 1000.0)


# ── Re-exports / adapters ──────────────────────────────────────────────

# Counters keep their symbol names; underlying Prometheus name is the
# new D-D-conformant aicareeros_* variant authored in core/metrics.py.
MEMORY_RECALL_HITS = _metrics.MEMORY_RECALL_HITS
MEMORY_WRITES_TOTAL = _metrics.MEMORY_WRITES_TOTAL

# Histograms — keep the _MS symbol name to leave call sites unchanged,
# but route through the ms→s adapter so the underlying metric value
# is in seconds. The legacy AGENT_EVAL_SCORE_HISTOGRAM symbol maps to
# the new AGENT_EVAL_SCORE (no unit conversion; eval scores are 0..1).
AGENT_EVAL_SCORE_HISTOGRAM = _metrics.AGENT_EVAL_SCORE
TOOL_CALL_DURATION_MS = _MillisecondHistogramAdapter(
    _metrics.TOOL_CALL_DURATION_SECONDS
)
MEMORY_RECALL_DURATION_MS = _MillisecondHistogramAdapter(
    _metrics.MEMORY_RECALL_DURATION_SECONDS
)
INTER_AGENT_CALL_DEPTH = _metrics.INTER_AGENT_CALL_DEPTH


__all__ = [
    "AGENT_EVAL_SCORE_HISTOGRAM",
    "TOOL_CALL_DURATION_MS",
    "MEMORY_RECALL_HITS",
    "MEMORY_RECALL_DURATION_MS",
    "MEMORY_WRITES_TOTAL",
    "INTER_AGENT_CALL_DEPTH",
]
