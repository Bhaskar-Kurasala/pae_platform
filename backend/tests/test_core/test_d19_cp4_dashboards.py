"""D19.1 CP4 — dashboard discipline tests.

Five CI gates against the dashboard-as-code artifacts in
``docs/operations/dashboards/``:

  1. JSON parse — every dashboard file is valid JSON.
  2. Schema shape — every dashboard has the canonical fields
     (id / title / owner / description / runbook /
     time_range_default / panels), and every panel has the
     canonical fields (id / title / panel_type / description /
     query).
  3. Owner present — D-F enforcement: every dashboard has a
     non-empty owner field. Unowned dashboards are deleted, not
     maintained.
  4. Metric references resolve — every metric named in a panel
     query corresponds to a metric registered in
     ``app.core.metrics.REGISTRY``. Catches typos like
     ``aicareeros_agent_cost`` (no `_inr`) at CI time.
  5. Runbook anchors exist — every dashboard's ``runbook`` link
     points at a heading that's actually present in
     ``docs/operations/runbooks.md``.

Together these prevent the most common dashboard-rot failure
modes: stale metric names, broken runbook links, owner drift.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.core.metrics import REGISTRY


# Locate dashboards + runbooks. Two valid locations:
#
#  1. Repo root /docs/operations/ — canonical position (host runs).
#  2. /docs/operations/ — bind-mounted into the runner container by
#     docker-compose.playwright.yml since the runner image only
#     bakes /app/ from the ./backend context.
#
# Prefer (2) when present (canonical environment), fall back to (1).
def _operations_root() -> Path:
    candidates = [
        Path("/docs/operations"),
        Path(__file__).resolve().parents[3] / "docs" / "operations",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Both missing — let later tests fail with a clear message.
    return candidates[-1]


_OPS_ROOT = _operations_root()
_DASHBOARDS_DIR = _OPS_ROOT / "dashboards"
_RUNBOOKS_PATH = _OPS_ROOT / "runbooks.md"


_REQUIRED_DASHBOARD_FIELDS = (
    "id",
    "title",
    "owner",
    "description",
    "runbook",
    "time_range_default",
    "panels",
)
_REQUIRED_PANEL_FIELDS = ("id", "title", "panel_type", "description", "query")


def _dashboard_files() -> list[Path]:
    if not _DASHBOARDS_DIR.exists():
        return []
    return sorted(p for p in _DASHBOARDS_DIR.iterdir() if p.suffix == ".json")


def _registered_metric_names() -> set[str]:
    """Return every metric name registered against the canonical
    REGISTRY. Includes both bare counter / gauge names and the
    histogram base name (without _bucket / _count / _sum suffixes
    prometheus_client adds at scrape time)."""
    names: set[str] = set()
    for collector in REGISTRY._collector_to_names:  # type: ignore[attr-defined]
        n = getattr(collector, "_name", None)
        if isinstance(n, str) and n:
            names.add(n)
    return names


def _runbook_anchors() -> set[str]:
    """Extract every heading anchor from runbooks.md.

    Markdown auto-anchors lowercase the heading and replace spaces
    with hyphens. We extract `## heading` and `### heading` lines
    and produce slug forms; that's the same shape as the
    ``runbook`` field references in dashboard files.
    """
    if not _RUNBOOKS_PATH.exists():
        return set()
    text = _RUNBOOKS_PATH.read_text(encoding="utf-8")
    anchors: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if not m:
            continue
        slug = m.group(1).strip().lower().replace(" ", "-")
        # Drop punctuation that markdown anchor generators strip.
        slug = re.sub(r"[^a-z0-9\-]", "", slug)
        anchors.add(slug)
    return anchors


# ---------------------------------------------------------------------------
# (1) JSON parse + (2) schema shape + (3) owner present
# ---------------------------------------------------------------------------


def test_dashboard_directory_has_six_dashboards() -> None:
    """Per D19.1 D-F + the CP4 spec: 6 dashboards (api / agent /
    cost / db / auth / operational). Catches accidental deletion."""
    files = _dashboard_files()
    ids = sorted(p.stem for p in files)
    assert ids == [
        "agent-health",
        "api-health",
        "auth-events",
        "cost",
        "db-health",
        "operational",
    ], f"unexpected dashboard set: {ids}"


@pytest.mark.parametrize("path", _dashboard_files(), ids=lambda p: p.stem)
def test_dashboard_parses_and_has_schema(path: Path) -> None:
    """Every dashboard file is valid JSON with the canonical fields.

    D19.3 update: ``placeholder`` panels (deferred-feature stubs)
    and ``source: db_query`` panels (DB-sourced rather than
    metric-sourced) are exempt from the ``query.metric`` requirement
    — they have other shape contracts validated elsewhere.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in _REQUIRED_DASHBOARD_FIELDS:
        assert field in data, (
            f"{path.name}: missing required field {field!r}"
        )
    assert data["id"] == path.stem, (
        f"{path.name}: 'id' field {data['id']!r} doesn't match filename"
    )
    panels = data["panels"]
    assert isinstance(panels, list) and panels, (
        f"{path.name}: 'panels' must be a non-empty list"
    )
    for panel in panels:
        # All panel types share id / title / panel_type / description.
        for field in ("id", "title", "panel_type", "description"):
            assert field in panel, (
                f"{path.name} panel {panel.get('id', '?')}: "
                f"missing required field {field!r}"
            )
        panel_type = panel.get("panel_type")
        source = panel.get("source", "metric")
        if panel_type == "placeholder":
            # Placeholder panels document deferred features.
            assert "placeholder_reason" in panel, (
                f"{path.name} panel {panel['id']}: placeholder panel "
                f"missing required field 'placeholder_reason'"
            )
            continue
        # Non-placeholder panels must carry a query.
        assert "query" in panel, (
            f"{path.name} panel {panel['id']}: missing required field 'query'"
        )
        if source == "db_query":
            # DB-sourced panels use SQL, not a metric reference.
            assert "sql" in panel["query"], (
                f"{path.name} panel {panel['id']}: source=db_query "
                f"requires query.sql"
            )
            continue
        # Standard metric-backed panel.
        assert "metric" in panel["query"], (
            f"{path.name} panel {panel['id']}: query missing 'metric'"
        )


@pytest.mark.parametrize("path", _dashboard_files(), ids=lambda p: p.stem)
def test_dashboard_has_owner(path: Path) -> None:
    """D-F: every dashboard has exactly one named owner."""
    data = json.loads(path.read_text(encoding="utf-8"))
    owner = data.get("owner")
    assert isinstance(owner, str) and owner.strip(), (
        f"{path.name}: owner must be a non-empty string"
    )


# ---------------------------------------------------------------------------
# (4) Metric references resolve
# ---------------------------------------------------------------------------


def _strip_histogram_suffix(metric: str) -> str:
    """Map _bucket / _count / _sum back to the base histogram name
    that's actually registered."""
    for suffix in ("_bucket", "_count", "_sum"):
        if metric.endswith(suffix):
            return metric[: -len(suffix)]
    return metric


@pytest.mark.parametrize("path", _dashboard_files(), ids=lambda p: p.stem)
def test_dashboard_panel_metrics_are_registered(path: Path) -> None:
    """Every metric referenced in a panel query resolves to a metric
    registered in REGISTRY. Catches naming drift at CI time.

    D19.3 update: ``placeholder`` panels (no query) and
    ``source: db_query`` panels (sql, not metric) are skipped.
    """
    registered = _registered_metric_names()
    data = json.loads(path.read_text(encoding="utf-8"))
    unknown: list[tuple[str, str]] = []
    for panel in data["panels"]:
        if panel.get("panel_type") == "placeholder":
            continue
        if panel.get("source") == "db_query":
            continue
        metric = panel["query"]["metric"]
        base_metric = _strip_histogram_suffix(metric)
        if base_metric not in registered:
            unknown.append((panel["id"], metric))
    assert not unknown, (
        f"{path.name}: panel(s) reference unregistered metrics: "
        f"{unknown}. Registered metrics: {sorted(registered)}"
    )


# ---------------------------------------------------------------------------
# (5) Runbook anchors exist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _dashboard_files(), ids=lambda p: p.stem)
def test_dashboard_runbook_link_resolves(path: Path) -> None:
    """Every dashboard's runbook link points at a heading that
    actually exists in runbooks.md."""
    data = json.loads(path.read_text(encoding="utf-8"))
    runbook_link = data["runbook"]
    # The link form is "../runbooks.md#anchor" — extract the anchor.
    if "#" not in runbook_link:
        pytest.fail(
            f"{path.name}: runbook link {runbook_link!r} has no anchor"
        )
    anchor = runbook_link.rsplit("#", 1)[-1]
    anchors = _runbook_anchors()
    assert anchor in anchors, (
        f"{path.name}: runbook anchor {anchor!r} not found in "
        f"runbooks.md (available anchors: {sorted(anchors)})"
    )
