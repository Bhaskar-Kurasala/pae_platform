"""D17b/ITEM 3 (Path E) — pin tests for compose_lead_in_opener.

Pure deterministic tests; no LLM, no DB. The composer takes a
StudentLeadInSignals input and returns a string opener (or None).
Trigger windows + priority order are pinned here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agents.primitives.lead_in_composer import compose_lead_in_opener
from app.agents.tools.universal.read_student_lead_in_signals import (
    ReadStudentLeadInSignalsOutput,
)


def _signals(**overrides) -> ReadStudentLeadInSignalsOutput:
    """Build a baseline (all-None / zero) signals object with selective
    overrides. Healthy-student default."""
    base = {
        "days_since_last_session": 1,
        "most_recent_mock_pass_at": None,
        "most_recent_transition_completed_at": None,
        "current_slip_type": None,
        "recent_activity_days_count_7d": 0,
    }
    base.update(overrides)
    return ReadStudentLeadInSignalsOutput(**base)


_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)


# ── Rule 1 — returning-after-absence ─────────────────────────────────


def test_returning_after_absence_fires_for_career_coach() -> None:
    signals = _signals(days_since_last_session=7)
    opener = compose_lead_in_opener(
        signals, agent_name="career_coach", now=_NOW
    )
    assert opener is not None
    assert "Welcome back" in opener
    assert "stepped away" in opener


def test_returning_after_absence_fires_for_study_planner_with_different_copy() -> None:
    """Same trigger; different agent voice."""
    signals = _signals(days_since_last_session=8)
    opener = compose_lead_in_opener(
        signals, agent_name="study_planner", now=_NOW
    )
    assert opener is not None
    assert "Last week's plan" in opener
    assert "re-set" in opener
    # Must NOT be the career_coach template
    assert "Welcome back" not in opener


# ── Rule 2 — mock-pass (career_coach only) ───────────────────────────


def test_mock_pass_fires_for_career_coach_within_24h() -> None:
    signals = _signals(
        most_recent_mock_pass_at=_NOW - timedelta(hours=12),
    )
    opener = compose_lead_in_opener(
        signals, agent_name="career_coach", now=_NOW
    )
    assert opener is not None
    assert "Nice work on that mock" in opener
    assert "step closer" in opener


# ── Rule 3 — gate-cleared (career_coach only) ────────────────────────


def test_gate_cleared_fires_for_career_coach_with_role_identity_brief() -> None:
    signals = _signals(
        most_recent_transition_completed_at=_NOW - timedelta(hours=24),
    )
    opener = compose_lead_in_opener(
        signals,
        agent_name="career_coach",
        role_identity_brief="data as a tool for understanding the world",
        next_role_display_name="Data Analyst",
        now=_NOW,
    )
    assert opener is not None
    assert "Congratulations" in opener
    assert "Data Analyst" in opener
    assert "data as a tool for understanding the world" in opener


def test_gate_cleared_falls_back_to_no_brief_template_when_brief_missing() -> None:
    """Graceful fallback when role_state.next_transition is unavailable."""
    signals = _signals(
        most_recent_transition_completed_at=_NOW - timedelta(hours=10),
    )
    opener = compose_lead_in_opener(
        signals, agent_name="career_coach", now=_NOW
    )
    assert opener is not None
    assert "Congratulations on clearing the gate" in opener
    assert "What do you want to focus on next?" in opener


# ── Rule 4 — stalled (study_planner only) ────────────────────────────


def test_stalled_fires_for_study_planner() -> None:
    signals = _signals(
        current_slip_type="capstone_stalled",
        days_since_last_session=2,
    )
    opener = compose_lead_in_opener(
        signals, agent_name="study_planner", now=_NOW
    )
    assert opener is not None
    assert "exercises haven't been clicking" in opener
    assert "walk through" in opener


# ── Rule 5 — momentum (study_planner only) ───────────────────────────


def test_momentum_fires_for_study_planner_when_active_and_no_slip() -> None:
    signals = _signals(
        recent_activity_days_count_7d=4,
        current_slip_type=None,
        days_since_last_session=1,
    )
    opener = compose_lead_in_opener(
        signals, agent_name="study_planner", now=_NOW
    )
    assert opener is not None
    assert "consistent" in opener
    assert "tighter plan" in opener


# ── Healthy student → None ───────────────────────────────────────────


def test_healthy_student_returns_none() -> None:
    """No signals warrant a lead-in; baseline behavior preserved."""
    signals = _signals()  # all-default, healthy
    assert (
        compose_lead_in_opener(
            signals, agent_name="career_coach", now=_NOW
        )
        is None
    )
    assert (
        compose_lead_in_opener(
            signals, agent_name="study_planner", now=_NOW
        )
        is None
    )


# ── Priority ordering ────────────────────────────────────────────────


def test_returning_after_absence_priority_beats_stalled_for_study_planner() -> None:
    """A study_planner student who BOTH has a stall signal AND has been
    gone 5+ days gets the **returning-after-absence** framing first.

    Re-engagement is the more urgent product signal. The stall is
    still in the data; the agent can address it after the opener
    re-establishes presence.
    """
    signals = _signals(
        days_since_last_session=7,
        current_slip_type="capstone_stalled",
    )
    opener = compose_lead_in_opener(
        signals, agent_name="study_planner", now=_NOW
    )
    assert opener is not None
    assert "Last week's plan" in opener  # returning-after-absence template
    assert "exercises haven't been clicking" not in opener


# ── Agent-template mismatch ──────────────────────────────────────────


def test_mock_pass_signal_does_not_fire_for_study_planner() -> None:
    """mock-pass is career_coach-only. study_planner with a fresh mock
    pass + healthy otherwise = None (no template applies for that
    agent / signal combination)."""
    signals = _signals(
        most_recent_mock_pass_at=_NOW - timedelta(hours=2),
        days_since_last_session=1,
    )
    opener = compose_lead_in_opener(
        signals, agent_name="study_planner", now=_NOW
    )
    # No study_planner-applicable signal fired.
    assert opener is None


# ── Window boundary edges (extra discipline) ─────────────────────────


def test_absence_below_threshold_does_not_fire() -> None:
    """4 days absent is below the 5-day threshold; no opener."""
    signals = _signals(days_since_last_session=4)
    assert (
        compose_lead_in_opener(
            signals, agent_name="career_coach", now=_NOW
        )
        is None
    )


def test_mock_pass_outside_24h_window_does_not_fire() -> None:
    """A 25-hour-old mock pass is outside the celebration window."""
    signals = _signals(
        most_recent_mock_pass_at=_NOW - timedelta(hours=25),
    )
    assert (
        compose_lead_in_opener(
            signals, agent_name="career_coach", now=_NOW
        )
        is None
    )


def test_momentum_blocked_by_stall_signal() -> None:
    """Momentum requires no current slip; with a slip present, the
    stalled rule fires first (priority order also enforces this)."""
    signals = _signals(
        recent_activity_days_count_7d=5,
        current_slip_type="capstone_stalled",
        days_since_last_session=1,
    )
    opener = compose_lead_in_opener(
        signals, agent_name="study_planner", now=_NOW
    )
    assert opener is not None
    # Stalled wins, not momentum
    assert "exercises haven't been clicking" in opener
    assert "consistent" not in opener
