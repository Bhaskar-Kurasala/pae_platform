"""Pure tests for 3A-4 clarification helpers."""

from __future__ import annotations

from app.services.clarification_service import (
    generate_followups,
    should_clarify,
)


def test_should_clarify_off_at_level_zero() -> None:
    out = should_clarify("how does attention work?", socratic_level=0)
    assert out.show_pills is False
    assert out.reason == "socratic_level_zero"


def test_should_clarify_off_for_short_message() -> None:
    out = should_clarify("hi", socratic_level=2)
    assert out.show_pills is False
    assert out.reason == "too_short"


def test_should_clarify_on_for_ambiguous_how() -> None:
    out = should_clarify("how does retrieval work here?", socratic_level=2)
    assert out.show_pills is True
    assert out.reason == "ambiguous_intent"
    assert len(out.pills) == 3
    assert {p.key for p in out.pills} == {"direct", "hint", "challenge"}


def test_should_clarify_on_for_stuck_phrase() -> None:
    out = should_clarify(
        "i am stuck on this embeddings problem", socratic_level=3
    )
    assert out.show_pills is True


def test_should_clarify_off_for_explicit_direct_request() -> None:
    out = should_clarify(
        "just tell me the answer to this chunking problem",
        socratic_level=2,
    )
    assert out.show_pills is False
    assert out.reason == "explicit_direct"


def test_should_clarify_off_for_explicit_practice_request() -> None:
    out = should_clarify(
        "quiz me on vector databases please", socratic_level=2
    )
    assert out.show_pills is False
    assert out.reason == "explicit_practice"


def test_should_clarify_off_when_no_signals() -> None:
    out = should_clarify(
        "thanks, that makes sense now", socratic_level=2
    )
    assert out.show_pills is False
    assert out.reason == "no_ambiguity"


def test_generate_followups_empty_for_short_reply() -> None:
    assert generate_followups("Got it.") == ()


def test_generate_followups_code_family_for_code_reply() -> None:
    reply = """Here's the fix:
```python
def compute(x):
    return x * 2
```
That should handle the common case.
"""
    pills = generate_followups(reply)
    assert {p.key for p in pills} == {
        "refactor",
        "edge_cases",
        "production",
    }


def test_generate_followups_concept_family_for_definition_reply() -> None:
    reply = (
        "An embedding is a dense vector representation of meaning. "
        "It refers to the learned coordinates in a high-dimensional space "
        "where semantically similar items sit close to each other."
    )
    pills = generate_followups(reply)
    assert {p.key for p in pills} == {"contrast", "example", "quiz"}


def test_generate_followups_generic_family_for_other_replies() -> None:
    reply = (
        "Yes, you can approach this in a few different ways depending on "
        "what your constraints are and how much data you already have "
        "available to work with."
    )
    pills = generate_followups(reply)
    assert {p.key for p in pills} == {"example", "practice", "deeper"}
