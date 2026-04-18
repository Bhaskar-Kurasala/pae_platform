"""Unit tests for teach-back evaluation parser (P2-11).

The async `evaluate_explanation` calls the LLM and is covered by route-level
integration tests; here we pin the pure parser that turns LLM JSON into a
validated evaluation.
"""

from __future__ import annotations

import json

import pytest

from app.services.teach_back_service import parse_evaluation


def _good_payload() -> dict:
    return {
        "accuracy": {"score": 4, "evidence": "Correctly said embeddings are vectors."},
        "completeness": {"score": 3, "evidence": "Didn't mention dimensionality."},
        "beginner_clarity": {"score": 4, "evidence": "Uses the 'fingerprint' analogy."},
        "would_beginner_understand": True,
        "missing_ideas": ["cosine similarity", "why high-dimensional"],
        "best_sentence": "An embedding is a list of numbers that captures meaning.",
        "follow_up": "What happens if two sentences have identical embeddings?",
    }


def test_parse_valid_payload() -> None:
    ev = parse_evaluation(json.dumps(_good_payload()))
    assert ev.accuracy.score == 4
    assert ev.would_beginner_understand is True
    assert len(ev.missing_ideas) == 2
    assert ev.best_sentence.startswith("An embedding")


def test_parse_accepts_code_fenced_json() -> None:
    raw = "```json\n" + json.dumps(_good_payload()) + "\n```"
    ev = parse_evaluation(raw)
    assert ev.accuracy.score == 4


def test_parse_accepts_plain_triple_backticks() -> None:
    raw = "```\n" + json.dumps(_good_payload()) + "\n```"
    ev = parse_evaluation(raw)
    assert ev.completeness.score == 3


def test_parse_rejects_non_json() -> None:
    with pytest.raises(ValueError):
        parse_evaluation("this is not json at all")


def test_parse_rejects_score_out_of_range() -> None:
    p = _good_payload()
    p["accuracy"]["score"] = 9
    with pytest.raises(ValueError, match="accuracy.score"):
        parse_evaluation(json.dumps(p))


def test_parse_rejects_score_of_zero() -> None:
    p = _good_payload()
    p["accuracy"]["score"] = 0
    with pytest.raises(ValueError, match="accuracy.score"):
        parse_evaluation(json.dumps(p))


def test_parse_rejects_missing_rubric_block() -> None:
    p = _good_payload()
    del p["completeness"]
    with pytest.raises(ValueError, match="completeness"):
        parse_evaluation(json.dumps(p))


def test_parse_rejects_non_bool_would_understand() -> None:
    p = _good_payload()
    p["would_beginner_understand"] = "yes"
    with pytest.raises(ValueError, match="would_beginner_understand"):
        parse_evaluation(json.dumps(p))


def test_parse_rejects_missing_ideas_with_non_string_item() -> None:
    p = _good_payload()
    p["missing_ideas"] = ["ok", 42]
    with pytest.raises(ValueError, match="missing_ideas"):
        parse_evaluation(json.dumps(p))


def test_parse_rejects_non_string_evidence() -> None:
    p = _good_payload()
    p["accuracy"]["evidence"] = 123
    with pytest.raises(ValueError, match="accuracy.evidence"):
        parse_evaluation(json.dumps(p))


def test_parse_empty_missing_ideas_ok() -> None:
    p = _good_payload()
    p["missing_ideas"] = []
    ev = parse_evaluation(json.dumps(p))
    assert ev.missing_ideas == []


def test_to_dict_roundtrip() -> None:
    ev = parse_evaluation(json.dumps(_good_payload()))
    d = ev.to_dict()
    assert d["accuracy"]["score"] == 4
    assert d["missing_ideas"] == ["cosine similarity", "why high-dimensional"]
    assert d["would_beginner_understand"] is True
