"""Embeddings dimension + determinism tests.

Lives in the primitives test directory but doesn't need Postgres —
purely exercises the python helper. The reason these tests matter:
the migration's `vector(1536)` column will reject any insert with a
mis-dimmed array, and the hash fallback is the only thing keeping
local + CI runs from needing a Voyage key.

If any of these break, the memory layer's writes start failing in
prod with `vector dimension mismatch` — much harder to diagnose
post-deploy than a broken unit test.
"""

from __future__ import annotations

import math

import pytest

from app.agents.primitives.embeddings import (
    EMBEDDING_DIM,
    _hash_fallback_vector,
    _pad_to_target_dim,
    embed_text,
)


pytestmark = pytest.mark.asyncio


async def test_hash_fallback_returns_exactly_1536_dims() -> None:
    """The whole point of the fallback: it must match the column dim.

    A 1024 (Voyage native) or 1500 (truncated) vector would silently
    fail the prod insert — exactly the bug we're guarding against.
    """
    vec = _hash_fallback_vector("hello world")
    assert len(vec) == EMBEDDING_DIM


async def test_hash_fallback_is_deterministic() -> None:
    """Same input → bit-for-bit same vector.

    This is what makes the fallback usable for tests: you can write
    a memory row in setup, recall it later, and the cosine math is
    reproducible.
    """
    a = _hash_fallback_vector("priya wants the genai role")
    b = _hash_fallback_vector("priya wants the genai role")
    assert a == b


async def test_hash_fallback_canonicalizes_whitespace_and_case() -> None:
    a = _hash_fallback_vector("  Priya Wants the Genai Role  ")
    b = _hash_fallback_vector("priya wants the genai role")
    assert a == b


async def test_hash_fallback_is_l2_normalized() -> None:
    """Cosine similarity behaves correctly only when both inputs are
    L2-normalized. Verifying here so a future refactor that drops the
    norm step gets caught."""
    vec = _hash_fallback_vector("test text")
    norm = math.sqrt(sum(x * x for x in vec))
    assert math.isclose(norm, 1.0, rel_tol=1e-6)


async def test_hash_fallback_distinct_inputs_distinct_vectors() -> None:
    """Two unrelated phrases should land far apart on the unit sphere."""
    a = _hash_fallback_vector("python is a programming language")
    b = _hash_fallback_vector("the eiffel tower is in paris")
    # Cosine similarity (since both are normalized) = sum(a_i * b_i)
    sim = sum(x * y for x, y in zip(a, b))
    # Far from 1.0 (identical) and from -1.0 (opposite). We don't
    # assert a tight bound because the hash-derived distribution can
    # legitimately drift; the contract is just "very different".
    assert -0.2 < sim < 0.2


async def test_hash_fallback_handles_empty_string() -> None:
    vec = _hash_fallback_vector("")
    assert len(vec) == EMBEDDING_DIM
    norm = math.sqrt(sum(x * x for x in vec))
    assert math.isclose(norm, 1.0, rel_tol=1e-6)


async def test_pad_zero_extends_short_vector() -> None:
    short = [1.0, 2.0, 3.0]
    out = _pad_to_target_dim(short, 1536)
    assert len(out) == 1536
    assert out[:3] == [1.0, 2.0, 3.0]
    assert all(x == 0.0 for x in out[3:])


async def test_pad_truncates_long_vector() -> None:
    long = [float(i) for i in range(2000)]
    out = _pad_to_target_dim(long, 1536)
    assert len(out) == 1536
    # Truncation keeps the leading slice.
    assert out == [float(i) for i in range(1536)]


async def test_embed_text_falls_back_when_no_voyage_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: embed_text() returns a 1536-dim vector even with no
    API key. The previous test catches the helper directly; this one
    catches the integration path that real callers hit."""
    monkeypatch.setattr(
        "app.core.config.settings.voyage_api_key", "", raising=False
    )
    vec = await embed_text("hello world")
    assert len(vec) == EMBEDDING_DIM


async def test_embed_text_empty_input_returns_dim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.voyage_api_key", "", raising=False
    )
    vec = await embed_text("")
    assert len(vec) == EMBEDDING_DIM
