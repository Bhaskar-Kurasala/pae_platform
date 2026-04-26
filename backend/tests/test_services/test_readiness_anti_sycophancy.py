"""Anti-sycophancy evaluator tests.

Coverage:

  1. clean_verdict_produces_no_flags — a specific, evidence-grounded
     verdict against a real-signal snapshot raises zero flags.
  2. forbidden_phrase_in_headline_is_flagged — "keep up the great work"
     style language fires the phrase blacklist.
  3. forbidden_phrase_in_evidence_is_flagged — flatter caught even when
     buried inside an evidence chip's text.
  4. generic_headline_pattern_is_flagged — "You're on the right track!"
     matches a pattern and fires generic_headline.
  5. missing_gap_when_weakness_visible_is_flagged — snapshot shows
     open weaknesses, verdict has zero gap chips → sycophancy by
     omission. The deliberately-weak-student regression case the spec
     calls out.
  6. thin_data_snapshot_does_not_require_gap — when the snapshot has
     no real signal yet, the gap-presence check is skipped.
  7. report_serializes_to_dict — for persistence on the verdict row.
"""

from __future__ import annotations

from app.services.readiness_anti_sycophancy import (
    SycophancyReport,
    evaluate_verdict,
)


def _strong_snapshot() -> dict:
    """Snapshot with real signal AND visible weakness."""
    return {
        "lessons_completed": 12,
        "exercises_submitted": 8,
        "mocks_taken": 2,
        "open_weaknesses": [{"concept": "system_design", "severity": 0.7}],
        "recent_mock_scores": [0.55, 0.62],
    }


def _thin_snapshot() -> dict:
    """Snapshot with no real signal."""
    return {
        "lessons_completed": 1,
        "exercises_submitted": 0,
        "mocks_taken": 0,
        "open_weaknesses": [],
        "recent_mock_scores": [],
    }


def test_clean_verdict_produces_no_flags() -> None:
    """Specific, falsifiable, mixes strengths and gaps."""
    report = evaluate_verdict(
        headline="System design is the gap; everything else is in shape.",
        evidence=[
            {
                "text": "Shipped 8 exercises in 60 days",
                "evidence_id": "exercises_submitted",
                "kind": "strength",
            },
            {
                "text": "No system design exposure yet",
                "evidence_id": "weakness:system_design",
                "kind": "gap",
            },
        ],
        snapshot_summary=_strong_snapshot(),
    )
    assert isinstance(report, SycophancyReport)
    assert report.has_flags() is False


def test_forbidden_phrase_in_headline_is_flagged() -> None:
    report = evaluate_verdict(
        headline="Keep up the great work — you're on the right path!",
        evidence=[
            {
                "text": "Shipped 8 exercises in 60 days",
                "evidence_id": "exercises_submitted",
                "kind": "strength",
            },
            {
                "text": "No system design exposure yet",
                "evidence_id": "weakness:system_design",
                "kind": "gap",
            },
        ],
        snapshot_summary=_strong_snapshot(),
    )
    assert "keep up the" in report.forbidden_phrases_hit


def test_forbidden_phrase_in_evidence_is_flagged() -> None:
    report = evaluate_verdict(
        headline="System design is the gap.",
        evidence=[
            {
                "text": "Amazing progress on Python this month",
                "evidence_id": "exercises_submitted",
                "kind": "strength",
            },
            {
                "text": "No system design exposure yet",
                "evidence_id": "weakness:system_design",
                "kind": "gap",
            },
        ],
        snapshot_summary=_strong_snapshot(),
    )
    assert "amazing progress" in report.forbidden_phrases_hit


def test_generic_headline_pattern_is_flagged() -> None:
    """A non-blacklisted but structurally vibe-only headline matches a
    generic-headline regex. (Headlines that ALSO hit the phrase
    blacklist surface there instead — both surfaces flag sycophancy,
    we just want to ensure something fires.)"""
    report = evaluate_verdict(
        # Pattern matches but phrase is not on the explicit blacklist.
        headline="You're on track.",
        evidence=[
            {
                "text": "Lessons completed",
                "evidence_id": "lessons_completed",
                "kind": "strength",
            },
            {
                "text": "Open weakness still there",
                "evidence_id": "weakness:system_design",
                "kind": "gap",
            },
        ],
        snapshot_summary=_strong_snapshot(),
    )
    assert "generic_headline" in report.flags


def test_blacklisted_headline_caught_even_if_pattern_misses() -> None:
    """Belt-and-braces: 'You're on the right track!' hits both the
    phrase blacklist and the regex. The product property we need is
    'something fires' — any sycophancy gets surfaced."""
    report = evaluate_verdict(
        headline="You're on the right track!",
        evidence=[
            {
                "text": "Lessons completed",
                "evidence_id": "lessons_completed",
                "kind": "strength",
            },
            {
                "text": "Open weakness still there",
                "evidence_id": "weakness:system_design",
                "kind": "gap",
            },
        ],
        snapshot_summary=_strong_snapshot(),
    )
    assert report.has_flags()


def test_missing_gap_when_weakness_visible_is_flagged() -> None:
    """The deliberately-weak-student regression from the spec.
    Snapshot shows open weakness; verdict has only strengths."""
    report = evaluate_verdict(
        headline="You're applying with strong fundamentals.",
        evidence=[
            {
                "text": "12 lessons completed",
                "evidence_id": "lessons_completed",
                "kind": "strength",
            },
            {
                "text": "8 exercises shipped",
                "evidence_id": "exercises_submitted",
                "kind": "strength",
            },
        ],
        snapshot_summary=_strong_snapshot(),
    )
    assert "missing_gap_when_weakness_visible" in report.flags


def test_thin_data_snapshot_does_not_require_gap() -> None:
    """Thin-data verdict with only one chip should not trigger the
    gap-presence check — there's no real signal to demand a gap from."""
    report = evaluate_verdict(
        headline="Not enough activity yet to tell where you stand.",
        evidence=[
            {
                "text": "1 lesson completed in the last 30 days",
                "evidence_id": "lessons_completed",
                "kind": "neutral",
            }
        ],
        snapshot_summary=_thin_snapshot(),
    )
    assert "missing_gap_when_weakness_visible" not in report.flags


def test_report_serializes_to_dict() -> None:
    report = evaluate_verdict(
        headline="Keep it up!",
        evidence=[
            {
                "text": "fine",
                "evidence_id": "lessons_completed",
                "kind": "strength",
            }
        ],
        snapshot_summary=_strong_snapshot(),
    )
    d = report.to_dict()
    assert "flags" in d
    assert "forbidden_phrases_hit" in d
    assert "keep it up" in d["forbidden_phrases_hit"]
