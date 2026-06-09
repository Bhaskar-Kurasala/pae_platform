"""D10 Checkpoint 1 — BillingSupportOutput schema validation.

Pure pydantic round-trips. No DB; no LLM; no agent class yet
(that's Checkpoint 2). These tests pin the schema shape from
Pass 3c E1 verbatim and the cross-field invariants enforced by
the model_validator.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.agents.billing_support import BillingSupportOutput


# ── Happy path ──────────────────────────────────────────────────────


def test_minimal_valid_output() -> None:
    """Smallest legal payload: answer + confidence."""
    out = BillingSupportOutput(
        answer="Your refund is processing.",
        confidence="high",
    )
    assert out.answer == "Your refund is processing."
    assert out.confidence == "high"
    assert out.grounded_in == []
    assert out.suggested_action is None
    assert out.self_serve_url is None
    assert out.escalation_ticket_id is None


def test_full_grounded_response_round_trips() -> None:
    """Pass 3c E1 Example 1 shape: refund check with lookup grounding."""
    payload = {
        "answer": (
            "Your refund for order CF-20260428-X7M2 is currently "
            "processing. Refunds typically arrive in your bank "
            "account 5-7 business days from the initiation date."
        ),
        "grounded_in": ["order CF-20260428-X7M2", "refund initiated 2026-04-28"],
        "suggested_action": "wait",
        "confidence": "high",
    }
    out = BillingSupportOutput(**payload)
    # JSON round-trip preserves shape
    rebuilt = BillingSupportOutput.model_validate_json(out.model_dump_json())
    assert rebuilt == out


def test_self_serve_with_url() -> None:
    """self_serve action with a URL is valid."""
    out = BillingSupportOutput(
        answer="Cancel from your account settings here.",
        suggested_action="self_serve",
        self_serve_url="https://aicareeros.com/account/cancel",
        confidence="high",
    )
    assert out.self_serve_url == "https://aicareeros.com/account/cancel"


def test_escalation_with_ticket_id() -> None:
    """Pass 3c E1 Example 3: escalation with ticket id."""
    out = BillingSupportOutput(
        answer="I've escalated to our admin team with ref TKT-2026-005.",
        grounded_in=["3 charges in 14 days after cancel request"],
        suggested_action="contact_support",
        escalation_ticket_id="TKT-2026-005",
        confidence="high",
    )
    assert out.escalation_ticket_id == "TKT-2026-005"
    assert out.suggested_action == "contact_support"


# ── Field-level validation ──────────────────────────────────────────


def test_answer_required_and_nonempty() -> None:
    with pytest.raises(ValidationError):
        BillingSupportOutput(answer="", confidence="high")  # min_length=1


def test_answer_capped_at_4000_chars() -> None:
    """The defensive cap from the schema docstring kicks in."""
    too_long = "A" * 4001
    with pytest.raises(ValidationError):
        BillingSupportOutput(answer=too_long, confidence="high")


def test_confidence_is_required() -> None:
    with pytest.raises(ValidationError):
        BillingSupportOutput(answer="hi")  # type: ignore[call-arg]


def test_confidence_must_be_one_of_three_levels() -> None:
    with pytest.raises(ValidationError):
        BillingSupportOutput(answer="ok", confidence="medium-ish")  # type: ignore[arg-type]


def test_suggested_action_must_be_in_literal_set() -> None:
    with pytest.raises(ValidationError):
        BillingSupportOutput(
            answer="ok",
            confidence="high",
            suggested_action="escalate",  # type: ignore[arg-type]
        )


def test_extra_fields_forbidden() -> None:
    """The Pass 3c §A.7 + schemas/agents/__init__.py convention:
    extra='forbid' so an LLM that hallucinates a key fails loudly."""
    with pytest.raises(ValidationError):
        BillingSupportOutput(
            answer="ok",
            confidence="high",
            mood="optimistic",  # type: ignore[call-arg]
        )


# ── Coupled-field invariants (model_validator) ──────────────────────


def test_self_serve_url_requires_self_serve_action() -> None:
    """The model_validator catches the inconsistent tuple."""
    with pytest.raises(ValidationError, match="self_serve_url"):
        BillingSupportOutput(
            answer="here is a link",
            confidence="high",
            suggested_action="wait",  # not self_serve
            self_serve_url="https://aicareeros.com/help",
        )


def test_self_serve_action_without_url_is_allowed() -> None:
    """Action without URL is valid — the URL is optional even on
    self_serve (e.g., 'go to your account settings' is a self-serve
    action with no specific link)."""
    out = BillingSupportOutput(
        answer="Go to your account settings to cancel.",
        confidence="medium",
        suggested_action="self_serve",
    )
    assert out.suggested_action == "self_serve"
    assert out.self_serve_url is None


def test_grounded_in_entries_capped_at_200_chars() -> None:
    """Long grounded_in references are rejected to keep the
    structured output predictable for downstream consumers."""
    over = "x" * 201
    with pytest.raises(ValidationError, match="200 chars"):
        BillingSupportOutput(
            answer="ok",
            confidence="high",
            grounded_in=[over],
        )


def test_grounded_in_with_short_entries_passes() -> None:
    out = BillingSupportOutput(
        answer="ok",
        confidence="high",
        grounded_in=["order CF-1", "refund #42"],
    )
    assert out.grounded_in == ["order CF-1", "refund #42"]
