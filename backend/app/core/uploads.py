"""File upload MIME sniffing — D1 security control.

Uses python-magic (libmagic binding) to detect the real MIME type from
file bytes rather than trusting the Content-Type header or file extension.
"""
from __future__ import annotations

import structlog
from fastapi import HTTPException, UploadFile, status

log = structlog.get_logger()

# Allowed MIME types per upload purpose.
# Mirrors AttachmentService.ALLOWED_MIME_TYPES plus document types.
# application/octet-stream is NOT listed here — when magic detects (or the
# browser declares) a generic binary type, validate_upload_mime passes it
# through without blocking so the service extension-fallback table can
# normalise it (e.g. nb.ipynb → application/x-ipynb+json). The service then
# applies its own allow-list as the final gate.
ALLOWED_CHAT_ATTACHMENT_MIMES: frozenset[str] = frozenset({
    # Documents
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    # Images
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    # Text / code — mirrored from AttachmentService.ALLOWED_MIME_TYPES
    "text/plain",
    "text/markdown",
    "text/x-python",
    "application/x-python",
    "application/x-python-code",
    "application/json",
    "application/x-ipynb+json",
})

ALLOWED_RESUME_MIMES: frozenset[str] = frozenset({
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
})


async def validate_upload_mime(
    file: UploadFile,
    *,
    allowed_mimes: frozenset[str],
) -> str:
    """Read first 2048 bytes, detect MIME via libmagic, validate, reset position.

    Returns the detected MIME type (or the claimed Content-Type when python-magic
    is unavailable — degraded mode logged at WARNING so ops can see the gap).
    Raises HTTPException(422) if the detected MIME is not in allowed_mimes.
    """
    preview = await file.read(2048)
    await file.seek(0)

    claimed = file.content_type or "application/octet-stream"
    filename = file.filename or ""

    try:
        import magic as _magic  # libmagic C binding — requires libmagic1 OS package
        detected = _magic.from_buffer(preview, mime=True)
    except ImportError:
        # python-magic / libmagic not installed in this environment.
        # Fail-open: log a warning and fall back to the claimed Content-Type.
        # This preserves existing behaviour in environments that have not yet
        # been rebuilt with the libmagic1 OS package (e.g. CI, local dev).
        # Production images built from the updated Dockerfile will always have it.
        log.warning(
            "upload.mime_check.degraded",
            reason="python-magic not installed; falling back to claimed Content-Type",
            filename=filename,
            claimed_mime=claimed,
        )
        detected = claimed

    log.info(
        "upload.mime_check",
        filename=filename,
        detected_mime=detected,
        claimed_mime=claimed,
        allowed=list(allowed_mimes),
    )

    # application/octet-stream is a generic binary declaration — not a security
    # signal on its own. Pass it through so the service extension-fallback table
    # can normalise the MIME (e.g. nb.ipynb → application/x-ipynb+json).
    # The service applies its own allow-list as the final gate.
    if detected != "application/octet-stream" and detected not in allowed_mimes:
        log.warning(
            "upload.mime_rejected",
            filename=filename,
            detected_mime=detected,
            claimed_mime=claimed,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File type not supported",
        )

    return detected
