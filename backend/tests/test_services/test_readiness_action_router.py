"""Action router tests.

Coverage:

  1. known_intents_resolve — every registered intent maps to a route.
  2. unknown_intent_falls_back_to_thin_data — defense-in-depth: the
     verdict prompt restricts the vocabulary, but if the LLM emits
     something unexpected, the router never crashes — it routes to the
     Today page with the thin-data label.
  3. suggested_label_wins_when_valid — verdict-generated labels are
     imperative-voiced; the router preserves them.
  4. suggested_label_falls_back_to_default_when_blank — empty / pure-
     whitespace labels fall back to the catalog default.
  5. suggested_label_truncated_at_120 — over-length labels are trimmed
     with a Unicode ellipsis to keep the button rendering predictable.
  6. catalog_round_trip — known_intents() returns the catalog's keys
     so callers can assert against the registered set.
"""

from __future__ import annotations

from app.services.readiness_action_router import known_intents, route_intent


def test_known_intents_resolve() -> None:
    for intent in known_intents():
        routed = route_intent(intent)
        assert routed.intent == intent
        assert routed.route.startswith("/")
        assert routed.label  # non-empty default


def test_unknown_intent_falls_back_to_thin_data() -> None:
    routed = route_intent("entirely-made-up-intent")
    assert routed.intent == "thin_data"
    assert routed.route == "/today"


def test_none_intent_falls_back_to_thin_data() -> None:
    routed = route_intent(None)
    assert routed.intent == "thin_data"


def test_suggested_label_wins_when_valid() -> None:
    routed = route_intent(
        "skills_gap",
        suggested_label="Open the system design lesson",
    )
    assert routed.label == "Open the system design lesson"


def test_suggested_label_falls_back_to_default_when_blank() -> None:
    routed = route_intent("skills_gap", suggested_label="   ")
    assert routed.label == "Open the next lesson"


def test_suggested_label_truncated_at_120() -> None:
    long = "x" * 200
    routed = route_intent("skills_gap", suggested_label=long)
    assert len(routed.label) == 118  # 117 + ellipsis char (1)
    assert routed.label.endswith("…")


def test_catalog_round_trip() -> None:
    assert "skills_gap" in known_intents()
    assert "thin_data" in known_intents()
    assert "ready_to_apply" in known_intents()
