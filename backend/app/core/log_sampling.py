"""D19.1 CP1.4 — structlog sampling processor.

Implements the D-E sampling rules from the D19.1 spec:

  - 100% retention for ERROR / CRITICAL
  - 100% retention for WARNING (no threshold gating in CP1; D19.2
    adds noise-aware thresholds when alerts arrive).
  - INFO sampled at LOG_SAMPLE_INFO_RATE (default 1.0; can be
    lowered to 0.10 in production once log volume justifies it).
  - DEBUG sampled at LOG_SAMPLE_DEBUG_RATE (default 0.01).

Determinism: the sample decision is computed from a hash of the
current ``trace_id`` (when bound) modulo a fixed-precision integer.
Same trace, same rate → same decision. A given trace's INFO logs
are therefore either *all* retained or *all* discarded; we never
ship half a request's logs to the backend, which would defeat
correlation.

Without a trace_id (e.g. early app-boot logs before any request)
we fall back to a per-call random decision. The lost correlation
is acceptable because pre-request lines have nothing to correlate
*to*; the boot logs themselves are sequenced by timestamp.

Configuration: read once at process import via env vars. Runtime-
tunable per the D-E rationale by restarting the process with new
env values; full live-reload would need a config service we don't
have yet (deferred to D19.x).
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
from typing import Any

import structlog

# ---------------------------------------------------------------------------
# Config — env-driven, read once.
# ---------------------------------------------------------------------------


def _read_rate(env_var: str, default: float) -> float:
    """Parse a 0.0-1.0 sampling rate from env. Out-of-range falls back."""
    raw = os.environ.get(env_var)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


SAMPLE_INFO_RATE: float = _read_rate("LOG_SAMPLE_INFO_RATE", 1.0)
SAMPLE_DEBUG_RATE: float = _read_rate("LOG_SAMPLE_DEBUG_RATE", 0.01)

# Sentinel returned by structlog processors to drop a log line.
_DROP_MARKER = structlog.DropEvent

# Hashing: 32-bit space is plenty for a probability comparison; trims
# the cost of a SHA-256 round to a couple of microseconds per log call.
_HASH_SPACE = 1 << 32


def _is_retained_for_trace(trace_id: str, rate: float) -> bool:
    """Deterministic-per-trace retention decision.

    For ``rate=0.10`` we want 10% of *traces* retained, not 10% of
    log lines. So we hash the trace_id alone — every line emitted
    inside that trace will see the same decision.
    """
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    digest = hashlib.blake2b(trace_id.encode("utf-8"), digest_size=4).digest()
    bucket = int.from_bytes(digest, "big") / _HASH_SPACE
    return bucket < rate


def _is_retained_random(rate: float) -> bool:
    """Per-call probabilistic retention. Used when no trace_id is bound."""
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    return random.random() < rate


# ---------------------------------------------------------------------------
# structlog processor.
# ---------------------------------------------------------------------------


def sampling_processor(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Drop INFO/DEBUG events probabilistically; pass WARN/ERROR untouched.

    Determinism: when a ``trace_id`` is in the event dict (because
    ``merge_contextvars`` has run earlier in the chain) we hash it
    for the decision. Without a trace_id we fall back to per-call
    random. Either way, ERROR / CRITICAL / WARNING always pass.
    """
    # method_name is "info", "warning", "error", etc. We map back to
    # the stdlib log level for the threshold comparison.
    level_no = logging.getLevelName(method_name.upper())
    if not isinstance(level_no, int):
        # Unknown / custom level — pass through.
        return event_dict

    if level_no >= logging.WARNING:
        return event_dict

    rate = SAMPLE_INFO_RATE if level_no >= logging.INFO else SAMPLE_DEBUG_RATE
    if rate >= 1.0:
        return event_dict

    trace_id = event_dict.get("trace_id")
    if isinstance(trace_id, str) and trace_id:
        retained = _is_retained_for_trace(trace_id, rate)
    else:
        retained = _is_retained_random(rate)

    if retained:
        return event_dict
    raise _DROP_MARKER
