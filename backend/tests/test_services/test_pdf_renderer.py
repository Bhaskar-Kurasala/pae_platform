"""PDF renderer tests — ATS recoverability is the load-bearing assertion.

The CI environment may not have WeasyPrint's GTK toolchain, so the renderer
falls back to a minimal hand-rolled PDF. Both paths must round-trip the
key resume sections through text extraction.
"""

from __future__ import annotations

from app.services.pdf_renderer import (
    StudentInfo,
    extract_text,
    render_cover_letter_pdf,
    render_resume_pdf,
)


_STUDENT = StudentInfo(
    full_name="Asha Verma",
    email="asha@example.com",
    location="Bengaluru, IN",
)

_RESUME_CONTENT = {
    "summary": "Junior Python developer with capstone-level async API experience.",
    "bullets": [
        {"text": "Built a CLI AI tool with retry-aware async API calls.", "evidence_id": "python"},
        {"text": "Authored unit tests covering rate-limit handling.", "evidence_id": "python"},
    ],
    "skills": ["Python", "FastAPI", "asyncio", "pytest"],
}


def _starts_pdf(blob: bytes) -> bool:
    return blob.startswith(b"%PDF-")


def test_render_resume_pdf_returns_valid_pdf_bytes() -> None:
    pdf = render_resume_pdf(content=_RESUME_CONTENT, student=_STUDENT)
    assert _starts_pdf(pdf)
    assert len(pdf) > 200


def test_resume_pdf_roundtrips_key_sections_via_text_extraction() -> None:
    pdf = render_resume_pdf(content=_RESUME_CONTENT, student=_STUDENT)
    text = extract_text(pdf)
    assert "Asha Verma" in text
    assert "asha@example.com" in text
    assert "Junior Python developer" in text
    # Each bullet must be recoverable
    assert "CLI AI tool" in text
    assert "rate-limit handling" in text
    # Skills line
    assert "Python" in text and "FastAPI" in text


def test_render_cover_letter_pdf_roundtrips_body() -> None:
    body = (
        "Dear Hiring Team,\n\n"
        "I am writing to apply for the Junior Python Developer role.\n\n"
        "Most recently I built a CLI AI tool with async API calls.\n\n"
        "I would welcome the chance to discuss further."
    )
    pdf = render_cover_letter_pdf(body=body, student=_STUDENT)
    assert _starts_pdf(pdf)
    text = extract_text(pdf)
    assert "Asha Verma" in text
    assert "Junior Python Developer" in text


def test_resume_pdf_handles_empty_content_gracefully() -> None:
    pdf = render_resume_pdf(content={}, student=_STUDENT)
    assert _starts_pdf(pdf)
    text = extract_text(pdf)
    assert "Asha Verma" in text
