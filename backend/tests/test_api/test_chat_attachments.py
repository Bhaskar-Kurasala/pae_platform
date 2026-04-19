"""Tests for the P1-6 chat-attachments surface.

Covers:
  - auth required
  - PNG image upload → 201 + slim projection
  - .exe / disallowed mime → 415
  - oversized payload (>10 MB) → 413
  - empty payload → 400
  - foreign user cannot see / bind another user's pending attachment
  - attaching to `/api/v1/agents/stream` binds the row to the user message
  - stream rejects unknown attachment ids with 404
  - stream rejects >4 attachments with 400
  - images reach the LLM as base64 image blocks; text files reach as fenced
    code-block prefixes inside the user turn
"""

from __future__ import annotations

import base64
import struct
import uuid
import zlib
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.v1.routes.chat import _storage_dep
from app.core.database import Base, get_db
from app.main import app
from app.services.attachment_storage import LocalFSAttachmentStorage

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


def _make_png(width: int = 2, height: int = 2) -> bytes:
    """Hand-roll a tiny valid PNG so the test doesn't depend on Pillow."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # Raw row data: filter byte + RGB triplets.
    raw = b""
    for _ in range(height):
        raw += b"\x00" + b"\xff\x00\x00" * width
    idat = zlib.compress(raw)
    iend = b""
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", iend)


@pytest.fixture
async def client(tmp_path: Path) -> AsyncGenerator[AsyncClient, None]:
    """Per-test FastAPI client against an in-memory SQLite engine + tmp-dir storage."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Tests run with a throwaway base dir so uploaded bytes can't leak
    # into the checked-in var/ tree.
    tmp_storage = LocalFSAttachmentStorage(tmp_path / "attachments")

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[_storage_dep] = lambda: tmp_storage

    with (
        patch("app.core.database.AsyncSessionLocal", session_factory),
        patch("app.api.v1.routes.stream.AsyncSessionLocal", session_factory),
        patch(
            "app.api.v1.routes.stream.build_default_storage",
            return_value=tmp_storage,
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Forwarded-For": "127.0.0.1"},
        ) as ac:
            yield ac

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


class _CapturingLLM:
    """Fake LLM that records the messages passed in so we can assert on the
    content blocks the stream route actually hands to Claude."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self.captured_messages: list[Any] | None = None

    async def astream(self, messages: list[Any]) -> AsyncIterator[Any]:
        self.captured_messages = messages

        class _Chunk:
            def __init__(self, text: str) -> None:
                self.content = text

        for t in self._tokens:
            yield _Chunk(t)


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Test User",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


# ---------------------------------------------------------------------------
# Upload route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/chat/attachments",
        files={"file": ("pixel.png", _make_png(), "image/png")},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_png_image_ok(client: AsyncClient) -> None:
    token = await _register_and_login(client, "att_png@example.com")
    png_bytes = _make_png()

    resp = await client.post(
        "/api/v1/chat/attachments",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("tiny.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["filename"] == "tiny.png"
    assert body["mime_type"] == "image/png"
    assert body["size_bytes"] == len(png_bytes)
    uuid.UUID(body["id"])
    # No storage_key leakage to the client.
    assert "storage_key" not in body


@pytest.mark.asyncio
async def test_upload_rejects_exe_with_415(client: AsyncClient) -> None:
    token = await _register_and_login(client, "att_exe@example.com")
    resp = await client.post(
        "/api/v1/chat/attachments",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "file": (
                "evil.exe",
                b"MZ\x00\x00" + b"\x00" * 100,
                "application/x-msdownload",
            )
        },
    )
    assert resp.status_code == 415


@pytest.mark.asyncio
async def test_upload_rejects_oversized_with_413(client: AsyncClient) -> None:
    token = await _register_and_login(client, "att_big@example.com")
    # Build a "PNG" with an honest size slightly over the 10 MB cap. Mime gate
    # passes (image/png) so we exercise the size-limit path specifically.
    too_big = b"\x89PNG\r\n\x1a\n" + b"0" * (10 * 1024 * 1024 + 1)
    resp = await client.post(
        "/api/v1/chat/attachments",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("huge.png", too_big, "image/png")},
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_upload_rejects_empty_with_400(client: AsyncClient) -> None:
    token = await _register_and_login(client, "att_empty@example.com")
    resp = await client.post(
        "/api/v1/chat/attachments",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("blank.png", b"", "image/png")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_octet_stream_ipynb_fallback_to_text(
    client: AsyncClient,
) -> None:
    """Browsers sometimes send `.ipynb` as `application/octet-stream` — the
    service normalizes that via the extension fallback table."""
    token = await _register_and_login(client, "att_ipynb@example.com")
    body = b'{"cells": [], "metadata": {}}'
    resp = await client.post(
        "/api/v1/chat/attachments",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("nb.ipynb", body, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["mime_type"] == "application/x-ipynb+json"


# ---------------------------------------------------------------------------
# Stream binding + Claude content blocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_binds_attachment_and_sends_image_block(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "att_stream@example.com")
    png_bytes = _make_png()

    upload = await client.post(
        "/api/v1/chat/attachments",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("tiny.png", png_bytes, "image/png")},
    )
    att_id = upload.json()["id"]

    fake_llm = _CapturingLLM(["Got it", " — nice colors"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={
                "message": "What's in this image?",
                "attachment_ids": [att_id],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        async for _ in resp.aiter_bytes():
            pass

    # Final HumanMessage in the prompt should be a list of blocks with
    # an image block carrying base64(png_bytes) + a text block with the
    # user's question.
    assert fake_llm.captured_messages is not None
    human = fake_llm.captured_messages[-1]
    assert isinstance(human.content, list)
    image_blocks = [b for b in human.content if b.get("type") == "image"]
    text_blocks = [b for b in human.content if b.get("type") == "text"]
    assert len(image_blocks) == 1
    src = image_blocks[0]["source"]
    assert src["media_type"] == "image/png"
    assert src["data"] == base64.b64encode(png_bytes).decode("ascii")
    assert len(text_blocks) == 1
    assert "What's in this image?" in text_blocks[0]["text"]

    # The attachment row should now be bound to the persisted user message.
    conv_list = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    conv_id = conv_list.json()[0]["id"]
    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    user_msg = next(m for m in detail.json()["messages"] if m["role"] == "user")
    # Re-uploading the same pending id should now 404 since it's bound.
    retry = await client.post(
        "/api/v1/agents/stream",
        json={"message": "again", "attachment_ids": [att_id]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert retry.status_code == 404
    assert user_msg["content"]  # sanity


@pytest.mark.asyncio
async def test_stream_with_text_file_fences_body_in_prompt(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "att_py@example.com")
    py_body = b"def add(a, b):\n    return a + b\n"
    upload = await client.post(
        "/api/v1/chat/attachments",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("snippet.py", py_body, "text/x-python")},
    )
    att_id = upload.json()["id"]

    fake_llm = _CapturingLLM(["thanks"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={
                "message": "Please review",
                "attachment_ids": [att_id],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        async for _ in resp.aiter_bytes():
            pass

    human = fake_llm.captured_messages[-1]  # type: ignore[index]
    assert isinstance(human.content, list)
    text_block = next(b for b in human.content if b.get("type") == "text")
    text = text_block["text"]
    assert "### File: snippet.py" in text
    assert "```python" in text
    assert "def add(a, b):" in text
    assert "Please review" in text


@pytest.mark.asyncio
async def test_stream_foreign_user_cannot_bind_anothers_attachment(
    client: AsyncClient,
) -> None:
    alice_token = await _register_and_login(client, "att_alice@example.com")
    bob_token = await _register_and_login(client, "att_bob@example.com")

    upload = await client.post(
        "/api/v1/chat/attachments",
        headers={"Authorization": f"Bearer {alice_token}"},
        files={"file": ("tiny.png", _make_png(), "image/png")},
    )
    alice_att_id = upload.json()["id"]

    fake_llm = _CapturingLLM(["nope"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={
                "message": "sneaky",
                "attachment_ids": [alice_att_id],
            },
            headers={"Authorization": f"Bearer {bob_token}"},
        )
    # Ownership mismatch collapses to 404 (same shape the chat routes use).
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stream_rejects_unknown_attachment_id(client: AsyncClient) -> None:
    token = await _register_and_login(client, "att_unknown@example.com")
    fake_llm = _CapturingLLM(["nope"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={
                "message": "hi",
                "attachment_ids": [str(uuid.uuid4())],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stream_rejects_over_four_attachments_with_422(
    client: AsyncClient,
) -> None:
    """Five ids in the payload → Pydantic rejects with 422 (max_length=4)."""
    token = await _register_and_login(client, "att_over@example.com")
    ids = [str(uuid.uuid4()) for _ in range(5)]
    resp = await client.post(
        "/api/v1/agents/stream",
        json={"message": "hi", "attachment_ids": ids},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_stream_without_attachments_stays_plain_text(
    client: AsyncClient,
) -> None:
    """Baseline: the legacy text-only path still sends a `str` HumanMessage."""
    token = await _register_and_login(client, "att_baseline@example.com")
    fake_llm = _CapturingLLM(["ok"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={"message": "just text"},
            headers={"Authorization": f"Bearer {token}"},
        )
        async for _ in resp.aiter_bytes():
            pass
    human = fake_llm.captured_messages[-1]  # type: ignore[index]
    assert isinstance(human.content, str)
    assert human.content == "just text"
