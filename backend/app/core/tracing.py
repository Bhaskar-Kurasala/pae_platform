"""D19.1 CP3 — OpenTelemetry tracing substrate.

Configures the global OpenTelemetry tracer provider with:

  * W3C trace context propagation (the standard ``traceparent`` /
    ``tracestate`` header pair). Replaces the CP1 defensive read in
    ``request_id.py`` with full bidirectional propagation: incoming
    ``traceparent`` is honoured at request entry; outgoing HTTP /
    Celery / DB calls inject the current span's context into their
    request headers.

  * Auto-instrumentations for FastAPI requests, SQLAlchemy queries,
    Redis calls, outbound httpx + requests, and Celery (the
    instrumentation packages handle propagation + span creation
    without per-call-site boilerplate).

  * Configurable OTLP exporter (HTTP transport) — pluggable per D-G.
    When ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, spans are exported
    over OTLP/HTTP. When unset, a local in-process span processor
    keeps spans in memory for the smoke test (and silently drops
    them in production — backends pick this up at CP5 closure).

  * Head-based sampling per D-E (CP3 ships head-based; tail-based
    "include if any span errored or any span exceeded p99 latency"
    is a collector-level decision deferred to CP5 backend choice).
    ``ParentBased(TraceIdRatioBased(rate))`` honours upstream sample
    decisions; rate defaults to 0.01 (1% baseline) per D-E.

  * Privacy substrate via ``set_safe_span_attribute`` — a thin wrapper
    over ``span.set_attribute`` that rejects denylisted keys at the
    substrate boundary. Same shape as CP2's metric-label cardinality
    discipline; convention enforcement happens at the substrate, not
    every call site.

The ``init_tracing()`` entry point is idempotent and no-op-safe:
calling it twice is fine, calling it without any env config is fine
(spans are created but not exported). Mirrors the design of
``app/core/sentry.py`` and ``app/core/telemetry.py``.
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.sampling import (
    ParentBased,
    TraceIdRatioBased,
)
from opentelemetry.trace import Span

log = structlog.get_logger().bind(layer="tracing")

_initialized = False
_tracer: trace.Tracer | None = None

# Service identity shipped on every span. Mirrors the metric naming
# prefix from CP2 so a backend correlating logs / metrics / traces
# can join on the service name without per-pillar lookup tables.
_SERVICE_NAME = "aicareeros"


# ---------------------------------------------------------------------------
# Privacy denylist — D-F enforcement at the substrate layer.
# ---------------------------------------------------------------------------

# Span attribute keys we refuse to set. Mirrors the structlog
# discipline (CP1) and the metric-label denylist (CP2): trace spans
# carry IDs and metadata, never payloads. Prompt contents and response
# contents can carry secrets, PII, or unbounded text — they don't
# belong in span attributes.
_DENYLISTED_SPAN_KEYS: frozenset[str] = frozenset(
    {
        # PII fields
        "email",
        "username",
        "user.email",
        "user.name",
        "user.full_name",
        "ip",
        "ip_address",
        "client_ip",
        "user.ip",
        # Payload fields — content of the LLM round-trip
        "prompt",
        "prompt_text",
        "system_prompt",
        "user_message",
        "user_input",
        "response",
        "response_text",
        "response_content",
        "completion",
        "llm.prompt",
        "llm.response",
        # Secrets / tokens
        "api_key",
        "secret",
        "password",
        "token",
        "authorization",
    }
)


class SpanAttributeError(ValueError):
    """Raised when a caller tries to set a denylisted span attribute."""


def set_safe_span_attribute(span: Span, key: str, value: Any) -> None:
    """Set a span attribute after validating the key against the
    denylist. Caller bears no responsibility — convention is
    enforced at the substrate boundary, mirrors CP2's
    ``register_*`` helpers and CP1's correlation-ID binders.

    Drift mode: rather than silently swallow a denylisted key (which
    would mask consumer drift), we raise. The privacy linter test
    in tests/test_core/test_d19_cp3_tracing_discipline.py exercises
    this path so a regression is caught at CI.
    """
    if key.lower() in _DENYLISTED_SPAN_KEYS:
        raise SpanAttributeError(
            f"Span attribute key {key!r} is denylisted. Trace spans "
            f"carry IDs + metadata, not payloads / PII / secrets. "
            f"Move per-event content into structlog (CP1); use a "
            f"non-payload attribute name here (e.g. token counts, "
            f"model id, agent id, status enums)."
        )
    span.set_attribute(key, value)


# ---------------------------------------------------------------------------
# Init / shutdown
# ---------------------------------------------------------------------------


def _build_sampler() -> ParentBased:
    """Construct the head-based sampler.

    ``OTEL_TRACES_SAMPLER_ARG`` env var overrides the default 1%.
    Range-clamped to [0.0, 1.0]. Per D-E rationale, the rate is
    runtime-tunable so D19.2-D19.5 can adjust based on real-load
    observations.
    """
    raw = os.environ.get("OTEL_TRACES_SAMPLER_ARG", "0.01")
    try:
        rate = float(raw)
    except ValueError:
        log.warning("tracing.bad_sampler_arg", raw=raw, fallback=0.01)
        rate = 0.01
    rate = max(0.0, min(1.0, rate))
    # ParentBased honours upstream sample decisions — if the caller's
    # traceparent already says "sampled=1" we keep the trace; if
    # "sampled=0" we drop it; if no parent we delegate to the ratio
    # sampler. Standard OTel pattern; matches what production
    # collectors expect.
    return ParentBased(root=TraceIdRatioBased(rate))


def init_tracing() -> None:
    """Configure the global tracer provider. Idempotent.

    Behavior matrix:

      * ``OTEL_EXPORTER_OTLP_ENDPOINT`` set → batch-export spans to
        the configured collector via OTLP/HTTP. Production path.

      * ``OTEL_TRACES_CONSOLE_EXPORTER=1`` set → spans printed to
        stdout as JSON (debugging aid; useful when wiring up the
        backend choice in CP5).

      * Neither set → tracer provider is configured but no exporter
        is attached. Spans are still created (so application code
        can call ``set_span_attribute`` without crashing) but they
        evaporate after the trace context closes. This is the safe
        default for dev and CI.

    The auto-instrumentations are wired separately via
    ``instrument_auto()`` so callers can choose to skip them in
    test environments where spurious DB / Redis spans pollute
    assertions.
    """
    global _initialized, _tracer
    if _initialized:
        return
    _initialized = True

    resource = Resource.create({"service.name": _SERVICE_NAME})
    provider = TracerProvider(resource=resource, sampler=_build_sampler())

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        try:
            otlp_exporter = OTLPSpanExporter(
                endpoint=endpoint.rstrip("/") + "/v1/traces"
            )
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            log.info("tracing.otlp_enabled", endpoint=endpoint)
        except Exception as exc:  # noqa: BLE001
            # Telemetry must never block boot.
            log.warning("tracing.otlp_init_failed", error=str(exc))

    if os.environ.get("OTEL_TRACES_CONSOLE_EXPORTER") == "1":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        log.info("tracing.console_exporter_enabled")

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(_SERVICE_NAME)
    log.info("tracing.initialized", service=_SERVICE_NAME)


def get_tracer() -> trace.Tracer:
    """Return the platform tracer. Lazy-initializes if not yet set up.

    Most call sites should prefer the higher-level helpers (e.g.
    ``trace_agent_run`` context manager) over raw ``tracer.start_span``.
    """
    if _tracer is None:
        init_tracing()
    assert _tracer is not None  # noqa: S101 — init_tracing populates it
    return _tracer


# ---------------------------------------------------------------------------
# Auto-instrumentation
# ---------------------------------------------------------------------------


def instrument_auto(*, app: Any | None = None) -> None:
    """Attach OpenTelemetry auto-instrumentations.

    Called from ``app/main.py`` after the FastAPI app is constructed
    (FastAPI instrumentation needs the app object) and from
    ``app/core/celery_app.py`` after the Celery instance is built.

    Each instrumentor is fail-soft: an instrumentation init crash
    must never block app boot. The relevant instrumentation just
    silently doesn't activate; structlog logs the reason so an
    operator notices.
    """
    # FastAPI — pass the app explicitly so the instrumentor wraps
    # *this* app, not whatever happens to be in the default lookup.
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import (
                FastAPIInstrumentor,
            )

            FastAPIInstrumentor.instrument_app(app)
            log.info("tracing.fastapi_instrumented")
        except Exception as exc:  # noqa: BLE001
            log.warning("tracing.fastapi_instrument_failed", error=str(exc))

    # SQLAlchemy — instrument the engine declared in
    # app.core.database. Auto-instrumentation hooks before/after
    # cursor execution events; ours are already there for slow-query
    # logging, so this layers on top without conflict.
    try:
        from opentelemetry.instrumentation.sqlalchemy import (
            SQLAlchemyInstrumentor,
        )

        from app.core.database import engine as _db_engine

        SQLAlchemyInstrumentor().instrument(
            engine=_db_engine.sync_engine,
            enable_commenter=False,
        )
        log.info("tracing.sqlalchemy_instrumented")
    except Exception as exc:  # noqa: BLE001
        log.warning("tracing.sqlalchemy_instrument_failed", error=str(exc))

    # Redis
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
        log.info("tracing.redis_instrumented")
    except Exception as exc:  # noqa: BLE001
        log.warning("tracing.redis_instrument_failed", error=str(exc))

    # httpx — outbound HTTP from the platform's async clients.
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        log.info("tracing.httpx_instrumented")
    except Exception as exc:  # noqa: BLE001
        log.warning("tracing.httpx_instrument_failed", error=str(exc))

    # requests — outbound HTTP from sync libs (Razorpay etc.).
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor

        RequestsInstrumentor().instrument()
        log.info("tracing.requests_instrumented")
    except Exception as exc:  # noqa: BLE001
        log.warning("tracing.requests_instrument_failed", error=str(exc))


def instrument_celery() -> None:
    """Attach Celery auto-instrumentation. Called from
    ``app/core/celery_app.py`` after the Celery app is built. The
    instrumentation hooks ``task_prerun`` / ``task_postrun`` / etc.
    so spans cross the broker round-trip; combined with our existing
    ``CorrelatedTask`` (CP1) which already injects W3C-format
    ``trace_id`` into headers, this gives broker-side W3C
    propagation natively.
    """
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor().instrument()
        log.info("tracing.celery_instrumented")
    except Exception as exc:  # noqa: BLE001
        log.warning("tracing.celery_instrument_failed", error=str(exc))


__all__ = [
    "SpanAttributeError",
    "get_tracer",
    "init_tracing",
    "instrument_auto",
    "instrument_celery",
    "set_safe_span_attribute",
]
