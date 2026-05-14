"""D1 — MIME sniffing tests for validate_upload_mime helper."""
from __future__ import annotations

import sys
from io import BytesIO
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_upload(
    *,
    content: bytes,
    content_type: str = "application/pdf",
    filename: str = "test.pdf",
) -> MagicMock:
    """Build a minimal UploadFile mock."""
    mock = MagicMock()
    buf = BytesIO(content)
    mock.filename = filename
    mock.content_type = content_type

    async def _read(n: int = -1) -> bytes:
        if n == -1:
            return buf.read()
        return buf.read(n)

    async def _seek(pos: int) -> None:
        buf.seek(pos)

    mock.read = _read
    mock.seek = _seek
    return mock


def _magic_module(*, detected_mime: str) -> ModuleType:
    """Return a stub `magic` module that always returns `detected_mime`."""
    mod = ModuleType("magic")
    mod.from_buffer = lambda data, mime=False: detected_mime  # type: ignore[attr-defined]
    return mod


# Minimal magic bytes for different file types
_PDF_BYTES = b"%PDF-1.4 fake pdf content here"
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
_EXE_BYTES = b"MZ" + b"\x00" * 100  # Windows PE / DOS executable
_DOCX_BYTES = b"PK\x03\x04" + b"\x00" * 100  # ZIP-based (DOCX)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_pdf_accepted() -> None:
    from app.core.uploads import ALLOWED_CHAT_ATTACHMENT_MIMES, validate_upload_mime

    upload = _make_upload(content=_PDF_BYTES, content_type="application/pdf")
    with patch.dict(sys.modules, {"magic": _magic_module(detected_mime="application/pdf")}):
        result = await validate_upload_mime(upload, allowed_mimes=ALLOWED_CHAT_ATTACHMENT_MIMES)
    assert result == "application/pdf"


@pytest.mark.asyncio
async def test_valid_png_accepted() -> None:
    from app.core.uploads import ALLOWED_CHAT_ATTACHMENT_MIMES, validate_upload_mime

    upload = _make_upload(content=_PNG_BYTES, content_type="image/png", filename="photo.png")
    with patch.dict(sys.modules, {"magic": _magic_module(detected_mime="image/png")}):
        result = await validate_upload_mime(upload, allowed_mimes=ALLOWED_CHAT_ATTACHMENT_MIMES)
    assert result == "image/png"


@pytest.mark.asyncio
async def test_exe_disguised_as_pdf_rejected() -> None:
    """Core attack vector: malware.exe renamed to resume.pdf with forged Content-Type."""
    from app.core.uploads import ALLOWED_CHAT_ATTACHMENT_MIMES, validate_upload_mime

    upload = _make_upload(
        content=_EXE_BYTES,
        content_type="application/pdf",
        filename="resume.pdf",
    )
    with patch.dict(sys.modules, {"magic": _magic_module(detected_mime="application/x-dosexec")}):
        with pytest.raises(HTTPException) as exc_info:
            await validate_upload_mime(upload, allowed_mimes=ALLOWED_CHAT_ATTACHMENT_MIMES)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "File type not supported"


@pytest.mark.asyncio
async def test_unknown_bytes_pass_through_for_service_gate() -> None:
    """Garbage bytes detected as application/octet-stream are passed through
    by D1 (not blocked at MIME-sniff layer). The service extension-fallback table
    is the final gate for generic binary blobs — D1 only blocks positively-
    identified disallowed types (e.g. application/x-dosexec)."""
    from app.core.uploads import ALLOWED_CHAT_ATTACHMENT_MIMES, validate_upload_mime

    upload = _make_upload(content=b"\x00\x01\x02\x03" * 100, content_type="application/pdf")
    with patch.dict(sys.modules, {"magic": _magic_module(detected_mime="application/octet-stream")}):
        # application/octet-stream is a pass-through — no exception raised here.
        result = await validate_upload_mime(upload, allowed_mimes=ALLOWED_CHAT_ATTACHMENT_MIMES)
    assert result == "application/octet-stream"


@pytest.mark.asyncio
async def test_file_seek_reset_after_validation() -> None:
    """After validate_upload_mime, seek(0) was called so downstream can re-read."""
    from app.core.uploads import ALLOWED_CHAT_ATTACHMENT_MIMES, validate_upload_mime

    content = _PDF_BYTES
    upload = _make_upload(content=content, content_type="application/pdf")

    seek_calls: list[int] = []
    original_seek = upload.seek

    async def _tracked_seek(pos: int) -> None:
        seek_calls.append(pos)
        await original_seek(pos)

    upload.seek = _tracked_seek

    with patch.dict(sys.modules, {"magic": _magic_module(detected_mime="application/pdf")}):
        await validate_upload_mime(upload, allowed_mimes=ALLOWED_CHAT_ATTACHMENT_MIMES)

    assert 0 in seek_calls, "seek(0) must be called after reading preview bytes"


@pytest.mark.asyncio
async def test_resume_allowed_mimes_subset_rejects_jpeg() -> None:
    """ALLOWED_RESUME_MIMES is stricter — rejects JPEG even if valid MIME."""
    from app.core.uploads import ALLOWED_RESUME_MIMES, validate_upload_mime

    upload = _make_upload(
        content=b"\xff\xd8\xff" + b"\x00" * 100,
        content_type="image/jpeg",
        filename="photo.jpg",
    )
    with patch.dict(sys.modules, {"magic": _magic_module(detected_mime="image/jpeg")}):
        with pytest.raises(HTTPException) as exc_info:
            await validate_upload_mime(upload, allowed_mimes=ALLOWED_RESUME_MIMES)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_degraded_fallback_when_magic_unavailable() -> None:
    """When python-magic is not installed, validate_upload_mime falls back to
    the claimed Content-Type and logs a warning rather than crashing."""
    from app.core.uploads import ALLOWED_CHAT_ATTACHMENT_MIMES, validate_upload_mime

    upload = _make_upload(content=_PDF_BYTES, content_type="application/pdf")

    # Remove 'magic' from sys.modules to simulate unavailability.
    orig = sys.modules.pop("magic", None)
    try:
        result = await validate_upload_mime(upload, allowed_mimes=ALLOWED_CHAT_ATTACHMENT_MIMES)
        # Falls back to claimed content_type = "application/pdf" → accepted.
        assert result == "application/pdf"
    finally:
        if orig is not None:
            sys.modules["magic"] = orig
