"""Chat attachment service (P1-6).

Owns:
  - mime-type + size gate (reject → 415 / 413 via HTTPException)
  - writing the file bytes through an `AttachmentStorage` backend
  - DB row creation on upload
  - ownership-verified binding of pending attachments to a user message
  - building Anthropic-compatible content blocks (image/base64 or
    fenced-code-with-filename) from a set of bound attachments, read on
    demand at stream time

The service layer deliberately does the mime/size gate so the route stays
dumb; the ruleset is trivial to extend later (e.g. add .csv, .json).
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chat_attachment import ChatAttachment
from app.repositories.attachment_repository import AttachmentRepository
from app.services.attachment_storage import AttachmentStorage

log = structlog.get_logger()


# Allow-list of accepted mime types for P1-6. The corresponding file
# extensions are kept alongside for filename sanity-checks when a browser
# sends `application/octet-stream` for .ipynb (happens in some OSes).
IMAGE_MIME_TYPES: frozenset[str] = frozenset({"image/png", "image/jpeg"})

TEXT_MIME_TYPES: frozenset[str] = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/x-python",
        "application/x-python",
        "application/x-python-code",
        "application/json",  # .ipynb is technically application/json
        "application/x-ipynb+json",
    }
)

ALLOWED_MIME_TYPES: frozenset[str] = IMAGE_MIME_TYPES | TEXT_MIME_TYPES

# Filename extension fallback: some browsers submit
# `application/octet-stream` for obscure text types. We fall back to the
# extension only if the declared mime type is generic.
_EXT_FALLBACK_MIME: dict[str, str] = {
    ".py": "text/x-python",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".ipynb": "application/x-ipynb+json",
}


def _normalize_mime(mime: str, filename: str) -> str:
    """If the browser sent a generic mime and the extension is known, use
    that instead. Returns the original mime otherwise."""
    if mime in ALLOWED_MIME_TYPES:
        return mime
    if mime in ("application/octet-stream", ""):
        lower = filename.lower()
        for ext, fallback in _EXT_FALLBACK_MIME.items():
            if lower.endswith(ext):
                return fallback
    return mime


def _map_text_mime_to_language(mime: str, filename: str) -> str:
    """Pick a fenced-code-block language hint for a text attachment."""
    lower = filename.lower()
    if lower.endswith(".py"):
        return "python"
    if lower.endswith(".md"):
        return "markdown"
    if lower.endswith(".ipynb"):
        return "json"
    if mime == "text/markdown":
        return "markdown"
    if mime in ("text/x-python", "application/x-python", "application/x-python-code"):
        return "python"
    return ""


class AttachmentService:
    def __init__(self, db: AsyncSession, storage: AttachmentStorage) -> None:
        self.db = db
        self.storage = storage
        self.repo = AttachmentRepository(db)

    async def upload(
        self,
        *,
        user_id: uuid.UUID,
        filename: str,
        mime_type: str,
        data: bytes,
    ) -> ChatAttachment:
        """Validate + persist a pending attachment.

        Raises:
            HTTPException 413 when `data` exceeds `attachments_max_bytes`.
            HTTPException 415 when the mime type isn't in the allow-list.
        """
        normalized_mime = _normalize_mime(mime_type, filename)

        if normalized_mime not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"Unsupported attachment type: {mime_type!r}. "
                    "Allowed: PNG, JPEG images and .py / .md / .txt / .ipynb files."
                ),
            )

        size = len(data)
        if size > settings.attachments_max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Attachment exceeds the {settings.attachments_max_bytes} byte limit "
                    f"(got {size} bytes)."
                ),
            )
        if size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Attachment is empty.",
            )

        storage_key = await self.storage.put(
            user_id=user_id, filename=filename, data=data
        )
        row = await self.repo.create(
            user_id=user_id,
            filename=filename,
            mime_type=normalized_mime,
            size_bytes=size,
            storage_key=storage_key,
        )
        log.info(
            "attachment.uploaded",
            user_id=str(user_id),
            attachment_id=str(row.id),
            mime_type=normalized_mime,
            size_bytes=size,
        )
        return row

    async def verify_and_fetch_pending(
        self, *, user_id: uuid.UUID, ids: Sequence[uuid.UUID]
    ) -> list[ChatAttachment]:
        """Fetch the pending rows for `ids` owned by `user_id`.

        Raises:
            HTTPException 400 when more than the per-message cap is asked for.
            HTTPException 404 when any id is missing / not owned / already
                bound (we collapse these into one status code so the error
                doesn't leak which specific id is invalid).
        """
        if not ids:
            return []
        if len(ids) > settings.attachments_max_per_message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Too many attachments: max "
                    f"{settings.attachments_max_per_message} per message."
                ),
            )

        # De-dup but preserve original order for deterministic downstream use.
        seen: set[uuid.UUID] = set()
        unique: list[uuid.UUID] = []
        for aid in ids:
            if aid in seen:
                continue
            seen.add(aid)
            unique.append(aid)

        rows = await self.repo.list_pending_for_user(user_id, unique)
        if len(rows) != len(unique):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more attachments were not found or aren't yours.",
            )
        # Reorder to match caller-provided order.
        by_id = {r.id: r for r in rows}
        return [by_id[aid] for aid in unique]

    async def bind_to_message(
        self, attachments: Sequence[ChatAttachment], message_id: uuid.UUID
    ) -> None:
        if not attachments:
            return
        await self.repo.bind_to_message(attachments, message_id)

    async def list_for_message(
        self, message_id: uuid.UUID
    ) -> list[ChatAttachment]:
        return await self.repo.list_for_message(message_id)

    async def build_claude_content_blocks(
        self, attachments: Iterable[ChatAttachment], *, text_message: str
    ) -> list[dict[str, Any]] | str:
        """Build an Anthropic content-block list for a user turn that has
        attachments bound to it.

        Returns either:
          - a plain `str` (no attachments → legacy text-only content) so the
            existing code path downstream stays unchanged, OR
          - a list of content blocks shaped for `anthropic.Message` content:
              * `{"type": "image", "source": {"type": "base64",
                   "media_type": ..., "data": ...}}` for images
              * a prefixed text block for each code/text file:
                  "### File: <filename>\n```<lang>\n<body>\n```"
              * final text block = the user's typed message

        We read each attachment's bytes on demand here rather than streaming
        them — Claude's SDK doesn't accept file handles for image content
        blocks, so we need the full bytes in memory at send time anyway.
        A bounded cap (10 MB × 4 = 40 MB worst case) keeps this reasonable.
        """
        atts = list(attachments)
        if not atts:
            return text_message

        image_blocks: list[dict[str, Any]] = []
        text_prefix: list[str] = []

        for att in atts:
            try:
                raw = await self.storage.get_bytes(att.storage_key)
            except FileNotFoundError:
                log.warning(
                    "attachment.missing_bytes",
                    attachment_id=str(att.id),
                    storage_key=att.storage_key,
                )
                continue
            except Exception as exc:
                log.warning(
                    "attachment.read_failed",
                    attachment_id=str(att.id),
                    error=str(exc),
                )
                continue

            if att.mime_type in IMAGE_MIME_TYPES:
                image_blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": att.mime_type,
                            "data": base64.b64encode(raw).decode("ascii"),
                        },
                    }
                )
            else:
                # Decode as UTF-8 with replacement so a malformed byte doesn't
                # kill the whole stream. Students upload human-edited text
                # files; strict decoding isn't worth the failure mode.
                try:
                    body = raw.decode("utf-8")
                except UnicodeDecodeError:
                    body = raw.decode("utf-8", errors="replace")
                lang = _map_text_mime_to_language(att.mime_type, att.filename)
                fence_open = f"```{lang}" if lang else "```"
                text_prefix.append(
                    f"### File: {att.filename}\n{fence_open}\n{body}\n```"
                )

        blocks: list[dict[str, Any]] = []
        for img in image_blocks:
            blocks.append(img)
        combined = "\n\n".join(text_prefix)
        combined = combined + "\n\n" + text_message if combined else text_message
        blocks.append({"type": "text", "text": combined})
        return blocks
