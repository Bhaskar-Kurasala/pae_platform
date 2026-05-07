"""D13 CP3 Phase 1.8 — Bug 23 regression test (LLM shape drift in
mock_interview specifically).

Pins the agent's _parse_output composition (strip_extra_fields →
truncate_to_schema → model_validate) against the exact failure
shape that hit Phase 4 live: the LLM emitted handoff_type at the
top level of MockInterviewOutput instead of nested inside
handoff_request.

Pre-Bug-23 fix: Pydantic raised ValidationError because
MockInterviewOutput has extra="forbid".

Post-fix: strip_extra_fields drops the rogue top-level handoff_type
before validation runs. The agent's output is valid, even though
the LLM produced a wrong-shaped dict.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.agents.mock_interview import _parse_output
from app.schemas.agents.mock_interview import MockInterviewOutput


def test_parse_output_drops_rogue_top_level_handoff_type() -> None:
    """The exact Bug 23 shape from CP3 Phase 4 retry: LLM flattened
    handoff_type to top level. Strip helper drops it; validation
    passes."""
    sid = uuid.uuid4()
    bug23_payload = {
        "session_id": str(sid),
        "mode": "behavioral",
        "turn_kind": "session_summary",
        "question": None,
        "evaluation": None,
        "feedback": None,
        "session_summary": {
            "overall_score_0_to_100": 70,
            "headline": "Solid interview overall.",
            "strengths": ["concrete examples"],
            "weaknesses": ["unquantified results"],
            "suggested_next_action": "Quantify outcomes.",
        },
        "handoff_request": None,
        # Bug 23 leak: handoff_type emitted at top level.
        "handoff_type": "suggested",
    }
    raw = json.dumps(bug23_payload)
    out = _parse_output(raw, session_id=sid, mode="behavioral")
    # No ValidationError → fix held.
    assert isinstance(out, MockInterviewOutput)
    assert out.turn_kind == "session_summary"
    assert out.handoff_request is None  # rogue field didn't leak into the model


def test_parse_output_drops_multiple_rogue_top_level_fields() -> None:
    """Defensive: more aggressive shape drift (several flattened
    fields) is still absorbed."""
    sid = uuid.uuid4()
    payload = {
        "session_id": str(sid),
        "mode": "coding",
        "turn_kind": "question",
        "question": {
            "question_text": "Implement an LRU cache.",
            "rubric_summary": "Big-O, eviction, thread-safety.",
            "expected_minutes": 25,
        },
        "evaluation": None,
        "feedback": None,
        "session_summary": None,
        "handoff_request": None,
        # Multiple rogue keys.
        "handoff_type": "suggested",
        "target_agent": "senior_engineer",
        "reason": "leaked nested fields",
        "extra_metadata": {"foo": "bar"},
    }
    out = _parse_output(json.dumps(payload), session_id=sid, mode="coding")
    assert out.turn_kind == "question"
    assert out.question is not None
    assert out.question.question_text == "Implement an LRU cache."


def test_parse_output_strips_rogue_keys_inside_handoff_request() -> None:
    """Strip is recursive — unknown keys inside the nested
    HandoffRequest are also dropped."""
    sid = uuid.uuid4()
    payload = {
        "session_id": str(sid),
        "mode": "coding",
        "turn_kind": "session_summary",
        "question": None,
        "evaluation": None,
        "feedback": None,
        "session_summary": {
            "overall_score_0_to_100": 60,
            "headline": "Mid-level coding.",
            "strengths": ["clean naming"],
            "weaknesses": ["amortized analysis"],
            "suggested_next_action": "Drill DS&A.",
        },
        "handoff_request": {
            "target_agent": "senior_engineer",
            "reason": "Coding-round failure.",
            "suggested_context": {"weakness_topic": "amortized_analysis"},
            "handoff_type": "suggested",
            # Rogue nested key — strip should drop it.
            "extra_nested_key": "drop_me",
        },
    }
    out = _parse_output(json.dumps(payload), session_id=sid, mode="coding")
    assert out.handoff_request is not None
    assert out.handoff_request.target_agent == "senior_engineer"
    # Validates against MockInterviewOutput's HandoffRequest, no error.


def test_parse_output_preserves_clean_dict_unchanged() -> None:
    """Sanity: when the LLM produces a clean dict, no fields drop."""
    sid = uuid.uuid4()
    clean_payload = {
        "session_id": str(sid),
        "mode": "behavioral",
        "turn_kind": "feedback",
        "question": None,
        "evaluation": None,
        "feedback": {
            "overall_assessment": "Strong storytelling, weak metrics.",
            "one_thing_to_practice": "Quantify outcomes.",
        },
        "session_summary": None,
        "handoff_request": None,
    }
    out = _parse_output(
        json.dumps(clean_payload), session_id=sid, mode="behavioral"
    )
    assert out.feedback is not None
    assert out.feedback.overall_assessment == "Strong storytelling, weak metrics."
