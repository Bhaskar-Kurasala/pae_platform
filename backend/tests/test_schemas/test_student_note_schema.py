"""Schema validation tests for admin student notes (P3 3A-18)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.student_note import StudentNoteCreate


def test_empty_body_rejected() -> None:
    with pytest.raises(ValidationError):
        StudentNoteCreate(body_md="")


def test_whitespace_is_allowed_by_pydantic_but_route_strips() -> None:
    # Pydantic accepts whitespace; the route layer calls .strip() before
    # persisting. We document both here so the contract is explicit.
    payload = StudentNoteCreate(body_md="  hello  ")
    assert payload.body_md == "  hello  "
    assert payload.body_md.strip() == "hello"


def test_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        StudentNoteCreate(body_md="x" * 4001)


def test_max_length_accepted() -> None:
    payload = StudentNoteCreate(body_md="x" * 4000)
    assert len(payload.body_md) == 4000


def test_typical_markdown_body_accepted() -> None:
    body = (
        "Saw Anya stuck on embeddings on 3/14. Reached out in DM — she\n"
        "came back with a clarifying question on cosine vs dot-product.\n\n"
        "- follow up after weekend\n- send her the RAG explainer\n"
    )
    payload = StudentNoteCreate(body_md=body)
    assert payload.body_md == body
