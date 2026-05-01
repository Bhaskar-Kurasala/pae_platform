"""Embeddings client for the Agentic OS memory layer.

Single point of contact for "turn this string into a 1536-dim float
vector". Two backends:

  • **Voyage** (preferred). When `VOYAGE_API_KEY` is set, calls
    Voyage-3 (`voyage-3` is 1024 native dims) and zero-pads the
    response to 1536 so it fits the migration's column type.
    Cosine similarity is identity-invariant under zero-padding, so
    Voyage embeddings remain comparable with each other after
    padding — and any future provider that natively emits 1536
    (OpenAI text-embedding-3-small) drops in unchanged.

  • **Deterministic hash** (dev / test fallback). When the key is
    unset OR the network call fails, we synthesize a stable 1536-dim
    vector from the input text via SHA-256 + reproducible RNG. Same
    input always returns the same vector, different inputs return
    near-orthogonal vectors. NOT suitable for prod recall quality —
    suitable for dimension-correctness tests and offline dev.

The fallback is the production-grade safety net the spec called out:
without it, every test using the memory layer would either need a
live Voyage key or would silently insert a `vector(1024)` and fail
the prod dimension check. With it, dev / test / CI all exercise the
same write/recall code path and the same column shape.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import struct
from collections.abc import Sequence
from typing import Final

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings

log = structlog.get_logger().bind(layer="embeddings")

# Mirror of agent_memory.embedding column type. Single source of truth
# for the dimension across the codebase.
EMBEDDING_DIM: Final[int] = 1536
VOYAGE_NATIVE_DIM: Final[int] = 1024
VOYAGE_TIMEOUT_SECONDS: Final[float] = 8.0
VOYAGE_API_URL: Final[str] = "https://api.voyageai.com/v1/embeddings"


class EmbeddingError(RuntimeError):
    """Raised when embedding generation fails permanently."""


def _hash_fallback_vector(text: str) -> list[float]:
    """Deterministic 1536-dim vector from arbitrary text.

    SHA-256 produces 256 bits. We need 1536 floats. Strategy: reseed
    SHA-256 with `(text || counter)` repeatedly, harvest 8 bytes per
    float, convert to a float in [-1, 1], then L2-normalize so cosine
    similarity behaves the same as with a real model.

    The text is canonicalized (lowercased + stripped) so cosmetic
    whitespace differences don't break determinism.

    Performance: ~0.3 ms per call on commodity hardware. Tests stay
    fast, no network call.
    """
    canonical = (text or "").strip().lower().encode("utf-8")
    floats: list[float] = []
    counter = 0
    while len(floats) < EMBEDDING_DIM:
        digest = hashlib.sha256(canonical + counter.to_bytes(4, "big")).digest()
        # 32 bytes / 8 bytes per float = 4 floats per iteration.
        for chunk_idx in range(0, 32, 8):
            (raw_int,) = struct.unpack(">Q", digest[chunk_idx : chunk_idx + 8])
            # Map to [-1, 1) deterministically. Bit 63 is sign, the
            # rest gives magnitude in 53-bit mantissa precision.
            scaled = ((raw_int / float(1 << 64)) - 0.5) * 2.0
            floats.append(scaled)
            if len(floats) == EMBEDDING_DIM:
                break
        counter += 1

    # L2 normalize so cosine similarity is well-behaved.
    norm = math.sqrt(sum(f * f for f in floats))
    if norm == 0.0:
        # Vanishingly unlikely (would need 1536 floats summing to 0).
        # Return a unit vector along axis 0 so the column never sees NaN.
        floats = [0.0] * EMBEDDING_DIM
        floats[0] = 1.0
        return floats
    return [f / norm for f in floats]


def _pad_to_target_dim(vector: Sequence[float], target: int) -> list[float]:
    """Zero-pad (or truncate) to the target dim.

    Cosine similarity between two padded-from-the-same-native-dim
    vectors is identity-invariant: sum(a_i * b_i) is unchanged because
    the padded tail is zero on both sides.

    ⚠️ Important caveat — cross-model comparison is **unsupported**:
    a vector that was *natively* 1536-dim (e.g. OpenAI
    text-embedding-3-small, Cohere embed-v3) and a vector that was
    natively 1024-dim and zero-padded to 1536 (current Voyage-3 path)
    occupy different effective subspaces of the column. The padded
    row's last 512 dims are forced to zero; the native-1536 row's
    last 512 dims carry real signal. Cosine similarity between these
    two rows is then arbitrarily skewed — recall quality silently
    degrades for any query that mixes them.

    Rule of thumb: keep one source model active per environment, or
    re-embed historical rows when the model changes. The migration
    does not enforce this; it's a callers' invariant maintained by
    only ever wiring one provider behind `embed_text()` at a time.
    """
    out = list(vector)
    if len(out) > target:
        return out[:target]
    if len(out) < target:
        out.extend([0.0] * (target - len(out)))
    return out


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4.0),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
)
async def _voyage_embed(text: str, api_key: str) -> list[float]:
    """One Voyage embed call with bounded retry.

    Tenacity handles transient network blips. A 4xx (auth, bad input)
    is *not* retried — those bubble immediately as EmbeddingError so
    the caller can fall back to the hash function rather than burn
    its retry budget on requests that will never succeed.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": [text],
        "model": settings.embeddings_model or "voyage-3",
        "input_type": "document",
    }
    async with httpx.AsyncClient(timeout=VOYAGE_TIMEOUT_SECONDS) as client:
        resp = await client.post(VOYAGE_API_URL, json=payload, headers=headers)
    if resp.status_code in (400, 401, 403, 404):
        raise EmbeddingError(
            f"Voyage rejected the request ({resp.status_code}): {resp.text[:160]}"
        )
    resp.raise_for_status()
    body = resp.json()
    try:
        vector = body["data"][0]["embedding"]
    except (KeyError, IndexError) as exc:
        raise EmbeddingError(f"Unexpected Voyage response shape: {exc}") from exc
    if not isinstance(vector, list) or not all(isinstance(x, (int, float)) for x in vector):
        raise EmbeddingError("Voyage returned a non-numeric embedding")
    if len(vector) != VOYAGE_NATIVE_DIM:
        log.warning(
            "embeddings.voyage.unexpected_dim",
            got=len(vector),
            expected=VOYAGE_NATIVE_DIM,
        )
    return [float(x) for x in vector]


async def embed_text(text: str) -> list[float]:
    """Public entry point — returns a 1536-dim vector for `text`.

    Order of operations:
      1. If `VOYAGE_API_KEY` is set, try Voyage with bounded retries.
         On success: pad to 1536 and return.
         On `EmbeddingError` (4xx) or repeated 5xx: fall through to (2).
      2. Use the deterministic hash fallback. Always returns 1536 dims.

    Always emits a structlog line tagged with the chosen backend and
    the resulting vector dimension — observability for the backend
    choice is critical because "why does this row look like noise?" is
    the first question on day 2 if recall quality drops.
    """
    if not text or not text.strip():
        # Empty input → empty-text hash so the call shape is stable
        # but the vector is at least deterministic.
        log.debug("embeddings.empty_input")
        return _hash_fallback_vector("")

    api_key = (settings.voyage_api_key or "").strip()
    if api_key:
        try:
            raw = await _voyage_embed(text, api_key)
            padded = _pad_to_target_dim(raw, EMBEDDING_DIM)
            log.debug(
                "embeddings.ok",
                backend="voyage",
                native_dim=len(raw),
                returned_dim=len(padded),
            )
            return padded
        except EmbeddingError as exc:
            # Permanent failure — log loud and fall back so the caller
            # can still write *something* without crashing.
            log.warning(
                "embeddings.voyage.permanent_failure",
                error=str(exc),
                falling_back=True,
            )
        except Exception as exc:  # noqa: BLE001 - last-ditch safety
            log.warning(
                "embeddings.voyage.transient_failure_after_retries",
                error=str(exc),
                falling_back=True,
            )

    fallback = _hash_fallback_vector(text)
    log.debug(
        "embeddings.ok",
        backend="hash_fallback",
        returned_dim=len(fallback),
    )
    return fallback


async def embed_batch(texts: Sequence[str]) -> list[list[float]]:
    """Convenience batch wrapper.

    Voyage supports batching natively, but to keep the interface
    simple we just gather single-text calls. If batch latency becomes
    a bottleneck, replace this with a single API call passing
    `input=[…]` and re-pad each row.
    """
    return await asyncio.gather(*(embed_text(t) for t in texts))


__all__ = [
    "EMBEDDING_DIM",
    "EmbeddingError",
    "embed_text",
    "embed_batch",
]
