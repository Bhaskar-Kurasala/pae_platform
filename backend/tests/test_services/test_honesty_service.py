"""Pure-function tests for the honesty hedge detector (P3 3A-8)."""

from __future__ import annotations

import pytest

from app.services.honesty_service import (
    HONESTY_OVERLAY,
    detect_honesty_hedge,
)


@pytest.mark.parametrize(
    "reply",
    [
        "I'm not sure — that library might not exist. Let me share two hypotheses.",
        "I don't know for certain, but the common pattern here is retry with jitter.",
        "I'm not certain about the exact signature; let me describe what's typical.",
        "Let me think out loud: if `foo_bar` is real, it would probably take a callable.",
        "I can't verify that paper's claim — I don't have it in what I've read.",
        "I'd need to check the docs to be sure, but from what I remember…",
        "I'm not 100% sure on the flag name; it's likely `--strict` or `--exact`.",
        "That function name might not be real — let me offer some candidates.",
    ],
)
def test_hedge_detector_positive(reply: str) -> None:
    match = detect_honesty_hedge(reply)
    assert match is not None
    assert match.marker


@pytest.mark.parametrize(
    "reply",
    [
        "Absolutely — `fastapi.Depends` is the standard injection primitive.",
        "Yes, that's how it works. Use `asyncio.gather` to run both in parallel.",
        "Great question. Async functions return coroutines.",
        "You can import `numpy as np` — that's the convention.",
        "",
    ],
)
def test_hedge_detector_negative(reply: str) -> None:
    assert detect_honesty_hedge(reply) is None


def test_overlay_copy_anchors() -> None:
    text = HONESTY_OVERLAY.lower()
    # Must name the "say so" behavior and the "don't fabricate" rule.
    assert "i'm not sure" in text
    assert "never fabricate" in text
    # Must instruct giving hypotheses as an alternative to a confident
    # wrong answer — that's the pedagogical payoff.
    assert "hypotheses" in text
