"""D19.1 CP2 — metric discipline tests (cardinality + naming linters).

Two CI gates running against the canonical REGISTRY in
``app.core.metrics``:

  1. Cardinality: no registered metric carries any label name from
     the D-C denylist (``user_id``, ``trace_id``, ``email`` etc.).
     Catches drift at boot, well before a metric backend OOMs.

  2. Naming: every registered metric matches the D-D shape
     ``aicareeros_<component>_<measurement>[_<unit>]`` with the
     ``aicareeros_`` prefix. Catches drift at registration time so
     a misnamed metric never reaches Prometheus.

Plus three positive-shape tests:

  3. The registration helpers reject denylisted labels.
  4. The registration helpers reject malformed names.
  5. ``render_latest`` returns a non-empty Prometheus exposition
     payload (substrate-functional smoke).

These run under canonical pytest-asyncio auto-mode (no anyio mark;
see followup pytest-asyncio-pytest-playwright-split-runs.md).
"""

from __future__ import annotations

import re

import pytest

from app.core.metrics import (
    REGISTRY,
    MetricRegistrationError,
    register_counter,
    register_gauge,
    register_histogram,
    render_latest,
)


# Mirrors app.core.metrics._DENYLISTED_LABELS — duplicated here so a
# typo in the source denylist doesn't silently disable the test.
_DENYLIST = frozenset(
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

_NAME_REGEX = re.compile(r"^aicareeros_[a-z][a-z0-9_]*$")


def _iter_registered_metrics() -> list[tuple[str, tuple[str, ...]]]:
    """Walk REGISTRY and return [(metric_name, label_names), ...].

    prometheus_client wraps each registered metric in a Collector;
    Counter/Histogram/Gauge expose ``_name`` + ``_labelnames``.
    Histograms also register sibling ``_count``/``_sum``/``_bucket``
    metrics under the same ``_name``; we report each unique name
    once with its declared labels.
    """
    seen: dict[str, tuple[str, ...]] = {}
    for collector in REGISTRY._collector_to_names:  # type: ignore[attr-defined]
        name = getattr(collector, "_name", None)
        labels = getattr(collector, "_labelnames", ())
        if name and name not in seen:
            seen[name] = tuple(labels)
    return sorted(seen.items())


def test_cp2_cardinality_no_denylisted_labels() -> None:
    """No registered metric carries a denylisted label.

    D-C: high-cardinality identifiers belong in logs / trace spans
    (CP1's contextvars), never in metric labels. Failure here means
    a future commit drifted away from D-C and would blow up the
    metric backend at first traffic.
    """
    violations: list[tuple[str, list[str]]] = []
    for name, labelnames in _iter_registered_metrics():
        bad = [label for label in labelnames if label.lower() in _DENYLIST]
        if bad:
            violations.append((name, bad))
    assert not violations, (
        f"Metrics with denylisted labels: {violations}. "
        f"Move these identifiers to structlog contextvars (CP1) "
        f"and use bounded labels for the metric instead."
    )


def test_cp2_naming_convention_aicareeros_prefix() -> None:
    """Every registered metric matches D-D naming.

    D-D: ``aicareeros_<component>_<measurement>[_<unit>]``. The
    component-level convention is enforced socially via dashboards
    + reviews; the prefix + lowercase-snake-case is enforced here
    because mis-prefixed metrics are an instantly-visible drift
    signal at scrape time.
    """
    violations: list[str] = []
    for name, _labels in _iter_registered_metrics():
        if not _NAME_REGEX.match(name):
            violations.append(name)
    assert not violations, (
        f"Metrics violating D-D naming convention: {violations}. "
        f"Required shape: aicareeros_<component>_<measurement>"
        f"[_<unit>]; lowercase + underscores only."
    )


def test_cp2_register_helper_rejects_denylisted_label() -> None:
    """The register_* helpers refuse a metric with a denylisted label."""
    with pytest.raises(MetricRegistrationError, match="denylisted"):
        register_counter(
            "aicareeros_test_synthetic_event",
            "Synthetic test counter that should be rejected.",
            labelnames=("user_id",),
        )
    with pytest.raises(MetricRegistrationError, match="denylisted"):
        register_histogram(
            "aicareeros_test_synthetic_duration_seconds",
            "Synthetic test histogram that should be rejected.",
            labelnames=("trace_id", "endpoint"),
        )
    with pytest.raises(MetricRegistrationError, match="denylisted"):
        register_gauge(
            "aicareeros_test_synthetic_gauge",
            "Synthetic test gauge that should be rejected.",
            labelnames=("email",),
        )


def test_cp2_register_helper_rejects_malformed_name() -> None:
    """The register_* helpers refuse a metric whose name violates D-D."""
    cases = [
        "agent_invocations",  # missing aicareeros_ prefix
        "aicareeros_",  # empty body
        "AICareerOS_Agent_Foo",  # not snake-case
        "aicareeros agent foo",  # spaces
        "aicareeros_agent-foo",  # hyphens
    ]
    for bad in cases:
        with pytest.raises(MetricRegistrationError, match="naming convention"):
            register_counter(bad, "doc")


def test_cp2_render_latest_returns_prometheus_payload() -> None:
    """The /metrics endpoint helper returns a non-empty payload in
    Prometheus exposition format. Substrate-functional smoke."""
    body, content_type = render_latest()
    assert isinstance(body, bytes)
    assert isinstance(content_type, str)
    assert content_type.startswith("text/plain") or content_type.startswith(
        "application/openmetrics"
    )
    text = body.decode("utf-8")
    # At least one D-D canonical metric must be visible. We check
    # for aicareeros_agent_invocations because it's emitted by the
    # most-trafficked path; if nothing else, this asserts the
    # registry serialised at all.
    assert "aicareeros_agent_invocations" in text
    # Format markers — every Prometheus exposition payload has
    # at least one HELP and one TYPE line.
    assert "# HELP" in text
    assert "# TYPE" in text
