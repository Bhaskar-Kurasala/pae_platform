"""Attachment storage backend abstraction (P1-6).

Defines a thin `AttachmentStorage` protocol so the chat-attachment route can
stay agnostic of where bytes actually live. Today we ship a local-filesystem
implementation for dev + tests; a future S3-backed impl will slot in via
dependency injection without touching the route or service.

Design notes:
  - All I/O is async. Local-fs uses `aiofiles`; the S3 impl will use `aiobotocore`
    (out of scope for P1-6).
  - `put` returns an opaque `storage_key` that `get_bytes` / `delete` accept
    back. For local-fs this is a relative path under `settings.attachments_dir`;
    for S3 it will be the object key.
  - The route reads the file's bytes once for Claude (base64 for images,
    decoded text for code) and doesn't keep the attachment mapped in memory
    across turns. Storage layer doesn't need streaming reads for v1.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol

import aiofiles
import aiofiles.os
import structlog

log = structlog.get_logger()


class AttachmentStorage(Protocol):
    """Abstract put/get/delete surface for chat attachment bytes."""

    async def put(self, *, user_id: uuid.UUID, filename: str, data: bytes) -> str:
        """Persist `data` under a new storage key. Returns the key."""
        ...

    async def get_bytes(self, storage_key: str) -> bytes:
        """Read the bytes for a previously-stored attachment."""
        ...

    async def delete(self, storage_key: str) -> None:
        """Best-effort delete. Should not raise on missing keys."""
        ...


class LocalFSAttachmentStorage:
    """Stores attachment bytes under `base_dir` as `<user_id>/<uuid>-<safe_name>`.

    Why this shape:
      - Namespacing by user id keeps browsing easy in dev and makes future
        per-user quotas trivial.
      - Prefixing the filename with a fresh UUID avoids collisions when two
        users upload the same name (or the same user uploads a duplicate) and
        removes any chance of a path-traversal payload leaking through.
      - The original filename suffix is preserved (after sanitization) so
        offline inspection is human-friendly during development.

    TODO(P1-6 → prod): replace with an `S3AttachmentStorage` impl that uses
    aiobotocore / boto3 for `put_object` / `get_object` / `delete_object`.
    The `storage_key` contract stays identical (opaque string), so callers
    won't need to change.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)

    @staticmethod
    def _safe_suffix(filename: str) -> str:
        """Return a filesystem-safe filename fragment derived from `filename`.

        Strips directory components and keeps only an allow-listed character
        set. Defends against path traversal even though callers already
        sanitize — storage is the last line of defence.
        """
        stem = Path(filename).name  # strip any dirs
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        cleaned = "".join(ch if ch in allowed else "_" for ch in stem)
        # Paranoid: cap to 120 chars so we don't exceed filesystem limits.
        return cleaned[:120] or "attachment.bin"

    async def put(self, *, user_id: uuid.UUID, filename: str, data: bytes) -> str:
        user_dir = self._base / str(user_id)
        # `aiofiles.os.makedirs` is thread-async; ok to call on every put —
        # the underlying `os.makedirs(exist_ok=True)` no-ops if present.
        await aiofiles.os.makedirs(user_dir, exist_ok=True)
        safe = self._safe_suffix(filename)
        key_name = f"{uuid.uuid4().hex}-{safe}"
        full_path = user_dir / key_name
        async with aiofiles.open(full_path, "wb") as f:
            await f.write(data)
        # Return the *relative* storage key so a rebase of `base_dir` (dev ↔
        # container ↔ prod) doesn't invalidate existing rows.
        return f"{user_id}/{key_name}"

    async def get_bytes(self, storage_key: str) -> bytes:
        full_path = self._resolve(storage_key)
        async with aiofiles.open(full_path, "rb") as f:
            return await f.read()

    async def delete(self, storage_key: str) -> None:
        full_path = self._resolve(storage_key)
        try:
            await aiofiles.os.remove(full_path)
        except FileNotFoundError:
            return
        except OSError as exc:
            # Non-fatal — log and move on. Disk cleanup isn't a correctness
            # issue for the chat surface, just hygiene.
            log.warning(
                "attachment.delete_failed",
                storage_key=storage_key,
                error=str(exc),
            )

    def _resolve(self, storage_key: str) -> Path:
        """Resolve `storage_key` → absolute path, rejecting traversal."""
        # Reject anything that would escape the base dir.
        if "\x00" in storage_key or storage_key.startswith(("/", "\\")):
            raise ValueError(f"Invalid storage key: {storage_key!r}")
        candidate = (self._base / storage_key).resolve()
        base_resolved = self._base.resolve()
        # Path.is_relative_to is 3.9+; python >=3.12 is required by pyproject.
        if not candidate.is_relative_to(base_resolved):
            raise ValueError(f"Storage key escapes base dir: {storage_key!r}")
        return candidate


def build_default_storage() -> AttachmentStorage:
    """Factory used by the route dependency. Kept as a separate function so
    tests can monkeypatch it to point at a tmp dir without re-importing the
    settings module."""
    from app.core.config import settings

    return LocalFSAttachmentStorage(settings.attachments_dir)
