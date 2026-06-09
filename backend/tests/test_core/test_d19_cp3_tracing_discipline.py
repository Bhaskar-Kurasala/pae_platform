"""D19.1 CP3 — tracing-substrate discipline tests.

Three CI gates running against the OpenTelemetry substrate in
``app/core/tracing.py``:

  1. Privacy: the ``set_safe_span_attribute`` helper rejects every
     denylisted key (PII / payload / secret).

  2. Init idempotency: ``init_tracing`` is safe to call multiple
     times; calling it without env vars produces a working tracer
     that simply doesn't export.

  3. W3C trace context propagation: the global propagator carries
     ``traceparent`` / ``tracestate`` across HTTP-style header
     extracts and injects.

Plus a positive-shape end-to-end smoke:

  4. A simulated FastAPI request emits an agent span with the
     expected attribute set + correlated trace_id; an
     ``InMemorySpanExporter`` captures everything for assertions
     so the test doesn't depend on a live OTLP collector.

These run under canonical pytest-asyncio auto-mode (no anyio mark;
see followup pytest-asyncio-pytest-playwright-split-runs.md).
"""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.core.tracing import (
    SpanAttributeError,
    get_tracer,
    init_tracing,
    set_safe_span_attribute,
)


# Mirrors app.core.tracing._DENYLISTED_SPAN_KEYS — duplicated here so a
# typo in the source denylist doesn't silently disable the test.
_PII_DENYLIST = (
    "email",
    "user.email",
    "ip_address",
    "client_ip",
)
_PAYLOAD_DENYLIST = (
    "prompt",
    "prompt_text",
    "system_prompt",
    "user_message",
    "user_input",
    "response",
    "response_text",
    "completion",
    "llm.prompt",
    "llm.response",
)
_SECRET_DENYLIST = (
    "api_key",
    "secret",
    "password",
    "token",
    "authorization",
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_tracer() -> tuple[trace.Tracer, InMemorySpanExporter]:
    """Provide a fresh TracerProvider with an InMemorySpanExporter
    so individual tests can inspect the spans they emit. Restores
    the previous global provider on teardown.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    saved = trace.get_tracer_provider()
    trace.set_tracer_provider(provider)
    yield provider.get_tracer("d19-cp3-test"), exporter
    # Best-effort restore. Some OTel versions reject set_tracer_provider
    # being called twice; we just continue.
    try:
        trace.set_tracer_provider(saved)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# (1) Privacy denylist
# ---------------------------------------------------------------------------


def test_set_safe_span_attribute_rejects_pii(
    in_memory_tracer: tuple[trace.Tracer, InMemorySpanExporter],
) -> None:
    tracer, _ = in_memory_tracer
    with tracer.start_as_current_span("test.span") as span:
        for key in _PII_DENYLIST:
            with pytest.raises(SpanAttributeError, match="denylisted"):
                set_safe_span_attribute(span, key, "value")


def test_set_safe_span_attribute_rejects_payloads(
    in_memory_tracer: tuple[trace.Tracer, InMemorySpanExporter],
) -> None:
    tracer, _ = in_memory_tracer
    with tracer.start_as_current_span("test.span") as span:
        for key in _PAYLOAD_DENYLIST:
            with pytest.raises(SpanAttributeError, match="denylisted"):
                set_safe_span_attribute(span, key, "value")


def test_set_safe_span_attribute_rejects_secrets(
    in_memory_tracer: tuple[trace.Tracer, InMemorySpanExporter],
) -> None:
    tracer, _ = in_memory_tracer
    with tracer.start_as_current_span("test.span") as span:
        for key in _SECRET_DENYLIST:
            with pytest.raises(SpanAttributeError, match="denylisted"):
                set_safe_span_attribute(span, key, "value")


def test_set_safe_span_attribute_allows_safe_keys(
    in_memory_tracer: tuple[trace.Tracer, InMemorySpanExporter],
) -> None:
    """Bounded-shape attributes (IDs, counts, model names, outcomes)
    must pass the denylist."""
    tracer, exporter = in_memory_tracer
    with tracer.start_as_current_span("test.span") as span:
        set_safe_span_attribute(span, "agent_id", "career_coach")
        set_safe_span_attribute(span, "agent.model", "claude-sonnet-4-6")
        set_safe_span_attribute(span, "agent.tokens_in", 1234)
        set_safe_span_attribute(span, "agent.tokens_out", 567)
        set_safe_span_attribute(span, "agent.cost_inr", 0.45)
        set_safe_span_attribute(span, "agent.outcome", "success")
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    attrs = dict(spans[0].attributes or {})
    assert attrs["agent_id"] == "career_coach"
    assert attrs["agent.model"] == "claude-sonnet-4-6"
    assert attrs["agent.tokens_in"] == 1234
    assert attrs["agent.cost_inr"] == 0.45
    assert attrs["agent.outcome"] == "success"


def test_set_safe_span_attribute_case_insensitive() -> None:
    """The denylist match is case-insensitive — an attacker can't
    bypass via 'Email' or 'EMAIL'."""
    tracer = trace.get_tracer("d19-cp3-test-case")
    with tracer.start_as_current_span("test.span") as span:
        for variant in ("Email", "EMAIL", "Api_Key", "PASSWORD"):
            with pytest.raises(SpanAttributeError, match="denylisted"):
                set_safe_span_attribute(span, variant, "value")


# ---------------------------------------------------------------------------
# (2) Init idempotency + no-op safety
# ---------------------------------------------------------------------------


def test_init_tracing_is_idempotent() -> None:
    """Calling init_tracing twice must not crash. Safe to invoke
    from multiple boot paths (FastAPI main, Celery worker init)."""
    init_tracing()
    init_tracing()
    init_tracing()
    tracer = get_tracer()
    assert tracer is not None


def test_get_tracer_lazy_inits_when_unconfigured() -> None:
    """Even when init_tracing has not been called, get_tracer should
    work — it lazy-inits to the no-op default. Catches bootstrap
    ordering bugs where a span is created before init runs."""
    tracer = get_tracer()
    with tracer.start_as_current_span("lazy-init-check") as span:
        assert span is not None
        # If this test runs before any other, start_as_current_span
        # will silently no-op or return a NonRecordingSpan; either
        # way we shouldn't crash.


# ---------------------------------------------------------------------------
# (3) W3C trace context propagation
# ---------------------------------------------------------------------------


def test_w3c_traceparent_round_trips_through_propagator(
    in_memory_tracer: tuple[trace.Tracer, InMemorySpanExporter],
) -> None:
    """Inject a span context into a carrier dict, extract it on the
    other side, and verify the trace_id matches. This is the
    contract Celery instrumentation + httpx instrumentation rely on
    when crossing process boundaries."""
    tracer, _ = in_memory_tracer
    with tracer.start_as_current_span("propagation-test") as span:
        original_trace_id = span.get_span_context().trace_id
        carrier: dict[str, str] = {}
        inject(carrier)
    # The propagator should have written a traceparent header.
    assert "traceparent" in carrier, (
        f"OTel propagator did not inject traceparent into carrier; "
        f"keys actually present: {list(carrier.keys())}"
    )
    # Round-trip via extract — simulating the receiving side
    # (Celery worker, downstream HTTP service).
    ctx = extract(carrier)
    extracted_span = trace.get_current_span(ctx)
    extracted_trace_id = extracted_span.get_span_context().trace_id
    assert extracted_trace_id == original_trace_id, (
        f"trace_id round-trip failed: original={original_trace_id:032x}, "
        f"extracted={extracted_trace_id:032x}"
    )


# ---------------------------------------------------------------------------
# (4) Positive-shape end-to-end: agent span captured with attributes
# ---------------------------------------------------------------------------


def test_agent_span_carries_expected_attributes(
    in_memory_tracer: tuple[trace.Tracer, InMemorySpanExporter],
) -> None:
    """Smoke: a span tagged with the same attributes BaseAgent.run /
    AgenticBaseAgent.execute set is captured + readable by an
    in-memory exporter. Substrate-functional check — proves the
    helper + tracer + exporter pipe end-to-end without a live
    OTLP collector."""
    tracer, exporter = in_memory_tracer
    with tracer.start_as_current_span("agent.simulated_career_coach") as span:
        set_safe_span_attribute(span, "agent_id", "simulated_career_coach")
        set_safe_span_attribute(span, "agent.model", "claude-sonnet-4-6")
        set_safe_span_attribute(span, "agent.tokens_in", 100)
        set_safe_span_attribute(span, "agent.tokens_out", 200)
        set_safe_span_attribute(span, "agent.cost_inr", 0.12)
        set_safe_span_attribute(span, "agent.outcome", "success")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "agent.simulated_career_coach"
    attrs = dict(s.attributes or {})
    assert attrs["agent_id"] == "simulated_career_coach"
    assert attrs["agent.tokens_in"] == 100
    assert attrs["agent.tokens_out"] == 200
    assert attrs["agent.cost_inr"] == 0.12
    assert attrs["agent.outcome"] == "success"
    # Privacy guard — none of the denylisted keys appear
    for redacted in _PII_DENYLIST + _PAYLOAD_DENYLIST + _SECRET_DENYLIST:
        assert redacted not in attrs, (
            f"denylisted attribute {redacted!r} leaked into span"
        )
