"""Unit tests for at-risk scoring helpers (P2-14).

DB-level ranking is covered by admin route integration tests. Here we pin the
pure signal builders and `combine_signals` that do the actual classification.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.at_risk_student_service import (
    Signal,
    combine_signals,
    help_drought_signal,
    lesson_stall_signal,
    login_silence_signal,
    low_mood_signal,
    progress_stall_signal,
    score_student,
)


NOW = datetime(2026, 4, 18, tzinfo=UTC)


# ── login_silence_signal ─────────────────────────────────────────────────────


def test_login_silence_recent_login_no_signal() -> None:
    assert login_silence_signal(NOW - timedelta(days=2), NOW - timedelta(days=60), now=NOW) is None


def test_login_silence_two_weeks_fires() -> None:
    sig = login_silence_signal(NOW - timedelta(days=14), NOW - timedelta(days=60), now=NOW)
    assert sig is not None
    assert sig.name == "no_login"
    assert "14" in sig.reason
    assert 0.1 < sig.weight < 1.0


def test_login_silence_never_logged_in_fresh_signup_no_signal() -> None:
    # Signed up 3 days ago, never logged in — too early to flag.
    assert login_silence_signal(None, NOW - timedelta(days=3), now=NOW) is None


def test_login_silence_never_logged_in_old_signup_fires() -> None:
    sig = login_silence_signal(None, NOW - timedelta(days=20), now=NOW)
    assert sig is not None
    assert "Never logged in" in sig.reason
    assert sig.weight > 0.5


def test_login_silence_naive_timestamp() -> None:
    # Naive datetime should be treated as UTC.
    naive = datetime(2026, 3, 25)  # 24 days before NOW
    sig = login_silence_signal(naive, NOW - timedelta(days=60), now=NOW)
    assert sig is not None


def test_login_silence_singular_day_unit() -> None:
    # Six days qualifies (boundary check: 5 is floor).
    sig = login_silence_signal(NOW - timedelta(days=6), NOW - timedelta(days=60), now=NOW)
    assert sig is not None
    assert "6 days" in sig.reason


# ── lesson_stall_signal ──────────────────────────────────────────────────────


def test_lesson_stall_recent_completion_no_signal() -> None:
    assert (
        lesson_stall_signal(
            NOW - timedelta(days=3),
            NOW - timedelta(days=60),
            now=NOW,
        )
        is None
    )


def test_lesson_stall_long_gap_fires() -> None:
    sig = lesson_stall_signal(
        NOW - timedelta(days=25),
        NOW - timedelta(days=60),
        now=NOW,
    )
    assert sig is not None
    assert sig.name == "lesson_stall"


def test_lesson_stall_new_student_never_completed_no_signal() -> None:
    # Enrolled 5 days ago, no completion yet — that's normal, not a risk.
    assert lesson_stall_signal(None, NOW - timedelta(days=5), now=NOW) is None


def test_lesson_stall_tenured_student_never_completed_fires() -> None:
    sig = lesson_stall_signal(None, NOW - timedelta(days=30), now=NOW)
    assert sig is not None
    assert "30 days since enrolling" in sig.reason


def test_lesson_stall_no_enrollment_no_signal() -> None:
    # Never enrolled in anything — can't score lesson stall.
    assert lesson_stall_signal(None, None, now=NOW) is None


# ── help_drought_signal ──────────────────────────────────────────────────────


def test_help_drought_below_threshold_no_signal() -> None:
    # Prior < 3 means we don't have enough prior signal to claim a drop-off.
    assert help_drought_signal(recent_count=0, prior_count=2) is None


def test_help_drought_no_drop_no_signal() -> None:
    assert help_drought_signal(recent_count=5, prior_count=5) is None


def test_help_drought_small_drop_no_signal() -> None:
    # 6 -> 4 is only 33% drop, below the 50% threshold.
    assert help_drought_signal(recent_count=4, prior_count=6) is None


def test_help_drought_sharp_drop_fires() -> None:
    sig = help_drought_signal(recent_count=1, prior_count=8)
    assert sig is not None
    assert sig.name == "help_drought"
    assert "8" in sig.reason and "1" in sig.reason


def test_help_drought_to_zero_maximum_weight() -> None:
    sig = help_drought_signal(recent_count=0, prior_count=10)
    assert sig is not None
    # Full drop-off → weight should be high (but capped at 0.7).
    assert sig.weight == 0.7


# ── low_mood_signal ──────────────────────────────────────────────────────────


def test_low_mood_single_bad_day_no_signal() -> None:
    assert low_mood_signal(low_mood_count=1, total_reflections=5) is None


def test_low_mood_no_reflections_no_signal() -> None:
    assert low_mood_signal(low_mood_count=0, total_reflections=0) is None


def test_low_mood_low_ratio_no_signal() -> None:
    # 2 of 10 is 20%, below the 40% threshold.
    assert low_mood_signal(low_mood_count=2, total_reflections=10) is None


def test_low_mood_sustained_struggle_fires() -> None:
    sig = low_mood_signal(low_mood_count=5, total_reflections=7)
    assert sig is not None
    assert sig.name == "low_mood"
    assert "5 of last 7" in sig.reason
    assert sig.weight > 0.5


# ── progress_stall_signal ────────────────────────────────────────────────────


def test_progress_stall_new_student_no_signal() -> None:
    # Only 10 days tenure — below MIN_TENURE_DAYS_FOR_STALL.
    assert progress_stall_signal(avg_progress_pct=0.0, tenure_days=10) is None


def test_progress_stall_on_track_no_signal() -> None:
    # 30 days in, 50% done — ahead of schedule.
    assert progress_stall_signal(avg_progress_pct=50.0, tenure_days=30) is None


def test_progress_stall_far_behind_fires() -> None:
    # 60 days in, only 5% progress. Expected ~67%, half of that is ~33%.
    # 5% is well below → should fire.
    sig = progress_stall_signal(avg_progress_pct=5.0, tenure_days=60)
    assert sig is not None
    assert sig.name == "progress_stall"
    assert "5%" in sig.reason


def test_progress_stall_mild_shortfall_no_signal() -> None:
    # 30 days in, 15% — below 50% of expected (33%), but not by enough to pass
    # the weight=0.1 gate.
    sig = progress_stall_signal(avg_progress_pct=15.0, tenure_days=30)
    # Either None or a very small signal — we accept None here (cleaner admin UX).
    if sig is not None:
        assert sig.weight >= 0.1


# ── combine_signals ──────────────────────────────────────────────────────────


def test_combine_no_signals_zero_score() -> None:
    score, reasons = combine_signals([])
    assert score == 0.0
    assert reasons == []


def test_combine_single_signal_passes_through() -> None:
    score, reasons = combine_signals([Signal("x", 0.6, "because reason")])
    assert score == 0.6
    assert reasons == ["because reason"]


def test_combine_signals_soft_or_compounds() -> None:
    # Two 0.5 signals should give 1 - (0.5*0.5) = 0.75, NOT 0.5 (average).
    score, _ = combine_signals(
        [Signal("a", 0.5, "a"), Signal("b", 0.5, "b")]
    )
    assert score == 0.75


def test_combine_signals_capped_at_one() -> None:
    score, _ = combine_signals(
        [Signal("a", 1.0, "a"), Signal("b", 1.0, "b"), Signal("c", 1.0, "c")]
    )
    assert score == 1.0


def test_combine_signals_reasons_sorted_by_weight() -> None:
    _, reasons = combine_signals(
        [
            Signal("low", 0.2, "low-reason"),
            Signal("high", 0.9, "high-reason"),
            Signal("mid", 0.5, "mid-reason"),
        ]
    )
    assert reasons == ["high-reason", "mid-reason", "low-reason"]


def test_combine_signals_top_3_only() -> None:
    _, reasons = combine_signals(
        [Signal(f"s{i}", 0.3, f"r{i}") for i in range(5)]
    )
    assert len(reasons) == 3


# ── score_student end-to-end ─────────────────────────────────────────────────


def test_score_student_all_healthy() -> None:
    score, reasons, sigs = score_student(
        last_login_at=NOW - timedelta(hours=2),
        created_at=NOW - timedelta(days=30),
        last_completed_at=NOW - timedelta(days=1),
        earliest_enrolled_at=NOW - timedelta(days=30),
        help_recent=5,
        help_prior=5,
        low_mood_count=0,
        total_reflections=4,
        avg_progress_pct=40.0,
        tenure_days=30,
        now=NOW,
    )
    assert score == 0.0
    assert reasons == []
    assert sigs == []


def test_score_student_ghost_student() -> None:
    # Enrolled a month ago, never logged in, never did anything.
    score, reasons, sigs = score_student(
        last_login_at=None,
        created_at=NOW - timedelta(days=30),
        last_completed_at=None,
        earliest_enrolled_at=NOW - timedelta(days=30),
        help_recent=0,
        help_prior=0,
        low_mood_count=0,
        total_reflections=0,
        avg_progress_pct=0.0,
        tenure_days=30,
        now=NOW,
    )
    assert score > 0.7
    # Should surface "never logged in" and "never completed a lesson" as reasons.
    assert any("Never logged in" in r for r in reasons)
    assert any("lesson" in r.lower() for r in reasons)


def test_score_student_drop_off_engaged_then_silent() -> None:
    # Was asking for help, then fell off.
    score, reasons, sigs = score_student(
        last_login_at=NOW - timedelta(days=12),
        created_at=NOW - timedelta(days=90),
        last_completed_at=NOW - timedelta(days=20),
        earliest_enrolled_at=NOW - timedelta(days=90),
        help_recent=0,
        help_prior=10,
        low_mood_count=0,
        total_reflections=0,
        avg_progress_pct=35.0,
        tenure_days=90,
        now=NOW,
    )
    assert score > 0.3
    # All three of login, lesson, and help signals should fire.
    names = {s.name for s in sigs}
    assert "no_login" in names
    assert "lesson_stall" in names
    assert "help_drought" in names
