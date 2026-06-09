# File upload validation — MIME sniffing

> Status: **Placeholder — implementation in CP2 (Batch 3, 2026-05-14).**
> Master list item: D1 (LAUNCH BLOCKER).

---

## What this covers

Server-side MIME type verification for the chat file attachment upload endpoint
(`app/api/v1/routes/chat.py`, file upload handler).

The current implementation accepts the client-declared `content_type` field without
independently verifying it against the actual byte content of the uploaded file.
This is bypassable: a client can upload a `.exe` or `.html` file with
`content_type: "image/png"` and the route accepts it.

---

## Planned implementation (CP2)

- Add `python-magic` (libmagic Python bindings) as a backend dependency.
- Add `libmagic` system library to the `backend` stage of `Dockerfile`.
- In the upload handler, after reading the file bytes, call
  `magic.from_buffer(data, mime=True)` to sniff the actual MIME type.
- Reject uploads whose sniffed MIME type is not in the allowlist
  (expected: `image/*`, `application/pdf`, `text/plain`).
- Return HTTP 415 Unsupported Media Type with a generic error message on rejection.

---

## Files affected

- `backend/app/api/v1/routes/chat.py` — upload endpoint
- `backend/Dockerfile` — add `libmagic1` (Debian) to the apt layer
- `backend/requirements.txt` (or `pyproject.toml`) — add `python-magic`

---

This document will be expanded with implementation notes and test coverage details
when CP2 ships.
