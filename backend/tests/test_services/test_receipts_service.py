"""Unit tests for receipts_service pure helpers."""
from __future__ import annotations

import pytest

from app.services.receipts_service import aggregate_reflections, compute_week_over_week


# ---------------------------------------------------------------------------
# compute_week_over_week
# ---------------------------------------------------------------------------


def test_improvement() -> None:
    result = compute_week_over_week(prior_lessons=3, current_lessons=5)
    assert result["lessons_delta"] == 2
    assert result["lessons_trend"] == "up"


def test_regression() -> None:
    result = compute_week_over_week(prior_lessons=5, current_lessons=2)
    assert result["lessons_delta"] == -3
    assert result["lessons_trend"] == "down"


def test_no_change() -> None:
    result = compute_week_over_week(prior_lessons=4, current_lessons=4)
    assert result["lessons_delta"] == 0
    assert result["lessons_trend"] == "flat"


def test_first_week_no_prior() -> None:
    result = compute_week_over_week(prior_lessons=None, current_lessons=3)
    assert result["lessons_trend"] == "first_week"
    assert result["lessons_delta"] is None


# ---------------------------------------------------------------------------
# aggregate_reflections
# ---------------------------------------------------------------------------


def test_aggregate_reflections_dominant() -> None:
    moods = ["good", "good", "rough", "good", "ok"]
    result = aggregate_reflections(moods)
    assert result["dominant_mood"] == "good"
    assert result["mood_counts"]["good"] == 3


def test_aggregate_reflections_empty() -> None:
    result = aggregate_reflections([])
    assert result["dominant_mood"] == "none"


def test_aggregate_reflections_single() -> None:
    result = aggregate_reflections(["ok"])
    assert result["dominant_mood"] == "ok"
    assert result["mood_counts"] == {"ok": 1}
