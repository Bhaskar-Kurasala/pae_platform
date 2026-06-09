"""PDF renderer for tailored resumes & cover letters.

Primary backend: WeasyPrint — HTML+CSS → PDF, single-column ATS-safe layout,
embedded fonts, parseable text layer.

Fallback backend: a minimal pure-Python text PDF writer (no third-party deps)
used when WeasyPrint isn't installed (typical on Windows dev boxes that
lack the GTK toolchain). The fallback still produces a parseable PDF with
the same content, just without typography polish — enough to keep the
generation flow working in CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env: Any = None  # lazily built; jinja2 is optional


@dataclass
class StudentInfo:
    full_name: str
    email: str = ""
    location: str = ""


def _get_jinja_env() -> Any:
    """Build the Jinja env on first use. Returns None if jinja2 is unavailable.

    Keeping the import lazy lets the container boot without jinja2 and fall
    through to the pure-Python text-PDF path below.
    """
    global _env
    if _env is not None:
        return _env
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        _env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )
        return _env
    except Exception as exc:
        log.info("pdf_renderer.jinja2_unavailable", error=str(exc))
        return None


def _render_html(template_name: str, **context: Any) -> str | None:
    env = _get_jinja_env()
    if env is None:
        return None
    template = env.get_template(template_name)
    return template.render(**context)


def _render_with_weasyprint(html: str) -> bytes | None:
    try:
        from weasyprint import HTML  # type: ignore[import-not-found]
    except Exception as exc:
        log.info("pdf_renderer.weasyprint_unavailable", error=str(exc))
        return None
    try:
        return HTML(string=html).write_pdf()  # type: ignore[no-any-return]
    except Exception as exc:
        log.warning("pdf_renderer.weasyprint_failed", error=str(exc))
        return None


def _render_fallback_pdf(text_lines: list[str]) -> bytes:
    """Produce a minimal but valid PDF containing *text_lines*.

    Hand-rolled to avoid pulling another binary dep. The output is parseable
    by `pdfplumber` and any ATS, which is the only contract the spec requires
    of the fallback path.
    """
    # Escape characters that break PDF string literals.
    def _escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    # Build the page content stream — Helvetica 10pt, top-down.
    y = 760
    stream_lines = ["BT", "/F1 10 Tf", f"1 0 0 1 72 {y} Tm"]
    for line in text_lines:
        stream_lines.append(f"({_escape(line)}) Tj")
        stream_lines.append("0 -14 Td")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("latin-1", errors="replace")

    objects: list[bytes] = []

    def _obj(content: bytes) -> int:
        objects.append(content)
        return len(objects)

    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    pages = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    page = (
        b"<< /Type /Page /Parent 2 0 R "
        b"/MediaBox [0 0 612 792] "
        b"/Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>"
    )
    contents = (
        f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
        + stream
        + b"\nendstream"
    )
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    _obj(catalog)
    _obj(pages)
    _obj(page)
    _obj(contents)
    _obj(font)

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, content in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("latin-1"))
        out.extend(content)
        out.extend(b"\nendobj\n")

    xref_offset = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets:
        out.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode(
            "latin-1"
        )
    )
    return bytes(out)


def _resume_text_lines(content: dict[str, Any], student: StudentInfo) -> list[str]:
    lines: list[str] = [student.full_name]
    contact = " ".join(filter(None, [student.email, student.location]))
    if contact:
        lines.append(contact)
    lines.append("")
    if content.get("summary"):
        lines.append("SUMMARY")
        lines.append(str(content["summary"]))
        lines.append("")
    bullets = content.get("bullets") or []
    if bullets:
        lines.append("EXPERIENCE & PROJECTS")
        for b in bullets:
            if isinstance(b, dict) and b.get("text"):
                lines.append(f"- {b['text']}")
        lines.append("")
    skills = content.get("skills") or []
    if skills:
        lines.append("SKILLS")
        lines.append(", ".join(str(s) for s in skills))
    return lines


def _cover_letter_text_lines(body: str, student: StudentInfo) -> list[str]:
    lines: list[str] = [student.full_name]
    contact = " ".join(filter(None, [student.email, student.location]))
    if contact:
        lines.append(contact)
    lines.append("")
    for paragraph in body.split("\n\n"):
        for line in paragraph.splitlines():
            if line.strip():
                lines.append(line.strip())
        lines.append("")
    return lines


def render_resume_pdf(
    *,
    content: dict[str, Any],
    student: StudentInfo,
    intake_data: dict[str, Any] | None = None,
) -> bytes:
    html = _render_html(
        "resume_ats.html",
        content=content,
        student=student,
        intake=intake_data or {},
    )
    if html is not None:
        pdf = _render_with_weasyprint(html)
        if pdf is not None:
            return pdf
    log.info("pdf_renderer.using_fallback", artifact="resume")
    return _render_fallback_pdf(_resume_text_lines(content, student))


def render_cover_letter_pdf(
    *,
    body: str,
    student: StudentInfo,
) -> bytes:
    html = _render_html(
        "cover_letter_ats.html",
        body=body,
        student=student,
    )
    if html is not None:
        pdf = _render_with_weasyprint(html)
        if pdf is not None:
            return pdf
    log.info("pdf_renderer.using_fallback", artifact="cover_letter")
    return _render_fallback_pdf(_cover_letter_text_lines(body, student))


def _application_kit_text_lines(manifest: dict[str, Any]) -> list[str]:
    """Flatten an application-kit manifest into a top-down list of text lines.

    Layout:
      - Cover: label, target role, built-at timestamp.
      - Resume block: summary + bullets + skills (truncated).
      - Tailored variant: JD excerpt + tailored summary/bullets if present.
      - JD card: title/company/fit/verdict.
      - Mock interview: headline + verdict + top strengths/weaknesses.
      - Autopsy retro: headline + score + what worked / what to do differently.

    Sections are skipped cleanly when their key is absent — never raises on
    missing data. The fallback PDF backend renders this verbatim.
    """
    lines: list[str] = []

    label = str(manifest.get("label") or "Application Kit")
    lines.append(f"APPLICATION KIT: {label}")
    if manifest.get("target_role"):
        lines.append(f"Target role: {manifest['target_role']}")
    if manifest.get("built_at"):
        lines.append(f"Built at: {manifest['built_at']}")
    lines.append("")

    resume = manifest.get("resume")
    if isinstance(resume, dict):
        lines.append("RESUME")
        if resume.get("title"):
            lines.append(str(resume["title"]))
        if resume.get("summary"):
            lines.append(str(resume["summary"]))
        bullets = resume.get("bullets") or []
        if bullets:
            lines.append("")
            lines.append("Highlights:")
            for b in bullets[:10]:
                if isinstance(b, dict) and b.get("text"):
                    lines.append(f"- {b['text']}")
                elif isinstance(b, str):
                    lines.append(f"- {b}")
        skills = resume.get("skills_snapshot") or []
        if skills:
            lines.append("")
            lines.append("Skills: " + ", ".join(str(s) for s in skills[:20]))
        lines.append("")

    tailored = manifest.get("tailored_resume")
    if isinstance(tailored, dict):
        lines.append("TAILORED VARIANT")
        jd_excerpt = (tailored.get("jd_text") or "")[:240]
        if jd_excerpt:
            lines.append(f"JD: {jd_excerpt}")
        content = tailored.get("content") or {}
        if isinstance(content, dict):
            if content.get("summary"):
                lines.append(str(content["summary"]))
            for b in (content.get("bullets") or [])[:8]:
                if isinstance(b, dict) and b.get("text"):
                    lines.append(f"- {b['text']}")
                elif isinstance(b, str):
                    lines.append(f"- {b}")
        lines.append("")

    jd = manifest.get("jd")
    if isinstance(jd, dict):
        lines.append("JOB DESCRIPTION")
        title = jd.get("title") or "(untitled)"
        company = jd.get("company") or ""
        lines.append(f"{title}{' — ' + company if company else ''}")
        if jd.get("fit_score") is not None:
            lines.append(f"Fit score: {jd['fit_score']}")
        if jd.get("verdict"):
            lines.append(f"Verdict: {jd['verdict']}")
        lines.append("")

    mock = manifest.get("mock_report")
    if isinstance(mock, dict):
        lines.append("MOCK INTERVIEW")
        if mock.get("headline"):
            lines.append(str(mock["headline"]))
        if mock.get("verdict"):
            lines.append(f"Verdict: {mock['verdict']}")
        strengths = mock.get("strengths") or []
        if strengths:
            lines.append("Strengths:")
            for s in strengths[:5]:
                lines.append(f"- {s}")
        weaknesses = mock.get("weaknesses") or []
        if weaknesses:
            lines.append("Weaknesses:")
            for w in weaknesses[:5]:
                lines.append(f"- {w}")
        lines.append("")

    autopsy = manifest.get("autopsy")
    if isinstance(autopsy, dict):
        lines.append("PORTFOLIO AUTOPSY")
        if autopsy.get("headline"):
            lines.append(str(autopsy["headline"]))
        if autopsy.get("overall_score") is not None:
            lines.append(f"Overall score: {autopsy['overall_score']}")
        worked = autopsy.get("what_worked") or []
        if worked:
            lines.append("What worked:")
            for w in worked[:5]:
                lines.append(f"- {w}")
        differently = autopsy.get("what_to_do_differently") or []
        if differently:
            lines.append("What to do differently:")
            for f in differently[:5]:
                if isinstance(f, dict):
                    issue = f.get("issue") or ""
                    todo = f.get("what_to_do_differently") or ""
                    lines.append(f"- {issue}: {todo}".rstrip(": "))
                elif isinstance(f, str):
                    lines.append(f"- {f}")
        lines.append("")

    return lines


def render_application_kit(manifest: dict[str, Any]) -> bytes:
    """Render an Application Kit manifest to a PDF.

    Reuses the WeasyPrint+template pipeline when a Jinja template is
    available (`templates/application_kit.html`), otherwise falls through to
    the pure-Python text PDF backend so kits are still downloadable on dev
    boxes lacking the GTK toolchain. Missing manifest sections are skipped
    cleanly — the renderer must never crash on partial bundles.
    """
    html = _render_html("application_kit.html", manifest=manifest)
    if html is not None:
        pdf = _render_with_weasyprint(html)
        if pdf is not None:
            return pdf
    log.info("pdf_renderer.using_fallback", artifact="application_kit")
    return _render_fallback_pdf(_application_kit_text_lines(manifest))


def extract_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF for ATS-recoverability tests.

    Prefers ``pdfplumber`` (handles WeasyPrint output); falls back to a tiny
    parser that walks ``Tj`` ops in our minimal PDF when pdfplumber is
    unavailable.
    """
    try:
        import io

        import pdfplumber  # type: ignore[import-untyped]

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as doc:
            return "\n".join((page.extract_text() or "") for page in doc.pages)
    except Exception as exc:
        log.info("pdf_renderer.pdfplumber_unavailable", error=str(exc))

    # Fallback parser for our hand-rolled PDF.
    try:
        text = pdf_bytes.decode("latin-1", errors="replace")
        out: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if line.endswith("Tj"):
                start = line.find("(")
                end = line.rfind(")")
                if 0 <= start < end:
                    raw = line[start + 1 : end]
                    raw = raw.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
                    out.append(raw)
        return "\n".join(out)
    except Exception:
        return ""
