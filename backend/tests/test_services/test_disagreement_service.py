"""Pure-function tests for disagreement detection (P3 3A-6).

The DB-backed logger is covered separately; this file locks in the two
detectors (`looks_like_factual_claim` and `detect_disagreement`) and the
overlay copy anchors. Both detectors are biased toward precision — we'd
rather miss a real disagreement than pollute the misconception table with
pedagogical corrections on questions.
"""

from __future__ import annotations

import pytest

from app.services.disagreement_service import (
    DISAGREEMENT_OVERLAY,
    detect_disagreement,
    looks_like_factual_claim,
)


# --- looks_like_factual_claim ---------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Embeddings are just one-hot encodings with dimensionality reduction.",
        "Async functions in Python always run on a separate thread.",
        "ReLU is the best activation function for every layer.",
        "Transformers replaced RNNs because attention is O(n).",
        "Vector databases store word embeddings only.",
    ],
)
def test_claim_detector_positive(message: str) -> None:
    assert looks_like_factual_claim(message) is True


@pytest.mark.parametrize(
    "message",
    [
        # Question forms
        "What are embeddings?",
        "How does attention work in transformers?",
        "Are async functions always faster?",
        "Is RAG the same as fine-tuning?",
        # Hedged
        "I think embeddings are like word vectors",
        "I'm not sure if this is right, but attention masks out padding",
        "I guess transformers are better than RNNs",
        "Not sure if vector DBs need cosine or L2",
        # Help requests
        "Can you explain embeddings to me?",
        "Can you clarify what a softmax does?",
        # Empty / tiny
        "",
        "   ",
        "ok",
        "yes",
    ],
)
def test_claim_detector_negative(message: str) -> None:
    assert looks_like_factual_claim(message) is False


# --- detect_disagreement ---------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "Actually, embeddings are dense float vectors — one-hot is a different representation.",
        "That's not quite right. Async in Python uses a single event loop, not threads.",
        "A common misconception is that vector DBs only store word embeddings — any vector works.",
        "Not exactly: ReLU is popular but not universally best; softmax is for the output.",
        "One correction here — attention is O(n^2), not O(n).",
        "Let me gently push back on that: transformers are parallel, not because attention is O(n).",
        "That's a myth — the pretrained model is not the same as the fine-tuned one.",
    ],
)
def test_disagreement_detector_positive(reply: str) -> None:
    match = detect_disagreement(reply)
    assert match is not None
    assert match.marker  # non-empty
    assert match.excerpt  # non-empty context window


@pytest.mark.parametrize(
    "reply",
    [
        # Agreeable / neutral
        "Yes, that's exactly right. Embeddings are dense float vectors.",
        "Great question — let me walk you through attention.",
        "Embeddings are dense float vectors used to represent tokens in latent space.",
        # Generic negations that we explicitly DON'T match on
        "No worries, that's a common place to get stuck.",
        "This is not as complicated as it looks.",
        "",
    ],
)
def test_disagreement_detector_negative(reply: str) -> None:
    assert detect_disagreement(reply) is None


def test_disagreement_excerpt_includes_context() -> None:
    reply = (
        "Great context! Actually, embeddings are learned dense float vectors, "
        "not one-hot encodings — the dimensionality is chosen by the model."
    )
    match = detect_disagreement(reply)
    assert match is not None
    # Excerpt should include the correction body, not just the marker
    assert "dense float vectors" in match.excerpt


# --- Overlay copy ----------------------------------------------------------


def test_overlay_copy_anchors() -> None:
    # Guardrails against prompt drift — the overlay must keep the two
    # load-bearing directives: (1) push back on wrong claims, (2) don't
    # hedge when the student is simply wrong.
    assert "push back" in DISAGREEMENT_OVERLAY.lower()
    assert "yes-machine" in DISAGREEMENT_OVERLAY.lower()
    # Soft-marker guidance so the tutor has a concrete way to open.
    assert "Actually" in DISAGREEMENT_OVERLAY
