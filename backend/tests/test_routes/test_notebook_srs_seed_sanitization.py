"""P-Bugfix1: notebook auto-seed must produce SRS cards with plain-text
prompts/answers, not raw markdown. The Today warm-up tile renders these
strings as-is in a small card — code fences, bold markers, multi-paragraph
blocks all wrecked the visual.
"""

from __future__ import annotations

from app.api.v1.routes.notebook import (
    SRS_ANSWER_MAX,
    SRS_PROMPT_MAX,
    _strip_markdown_to_text,
    _truncate_with_ellipsis,
)


def test_strip_strips_fenced_code_blocks() -> None:
    md = "Here is my note.\n\n```python\ndef f():\n    return 1\n```\n\nDone."
    out = _strip_markdown_to_text(md)
    assert "def f" not in out
    assert "Here is my note" in out
    assert "Done" in out


def test_strip_keeps_inline_code_text() -> None:
    md = "Use `asyncio.gather` for concurrency."
    out = _strip_markdown_to_text(md)
    assert out == "Use asyncio.gather for concurrency."


def test_strip_removes_bold_italic_markers() -> None:
    md = "This is **bold** and _italic_ and *also italic* and __underbold__."
    out = _strip_markdown_to_text(md)
    assert "**" not in out
    assert "__" not in out
    assert "bold" in out and "italic" in out and "underbold" in out


def test_strip_removes_list_bullets_and_numbered_lists() -> None:
    md = "- First item\n- Second item\n\n1. Numbered\n2. Two"
    out = _strip_markdown_to_text(md)
    assert "First item" in out
    assert "Numbered" in out
    assert "- " not in out
    assert "1." not in out


def test_strip_removes_headings_and_quotes() -> None:
    md = "## Heading\n\n> a quote line\n\nbody"
    out = _strip_markdown_to_text(md)
    assert "Heading" in out
    assert "a quote line" in out
    assert "body" in out
    assert "##" not in out
    assert ">" not in out


def test_strip_collapses_blank_lines_to_single_space() -> None:
    md = "First.\n\n\n\nSecond.\n\nThird."
    out = _strip_markdown_to_text(md)
    assert out.count("\n") == 0
    assert "First." in out and "Second." in out and "Third." in out


def test_truncate_respects_word_boundary() -> None:
    s = "This is a fairly long sentence we want to clip cleanly."
    out = _truncate_with_ellipsis(s, 30)
    assert out.endswith("…")
    assert len(out) <= 31  # 30 chars of content + ellipsis
    # No trailing partial word.
    assert "cleanly" not in out


def test_truncate_short_input_unchanged() -> None:
    s = "short"
    assert _truncate_with_ellipsis(s, 30) == "short"


def test_full_pipeline_on_realistic_chat_markdown() -> None:
    """The exact failure mode from the bug report — assistant-generated
    markdown with code fences, headings, and lists. Output must be a
    single readable line under SRS_ANSWER_MAX."""
    md = (
        "## RAG: Retrieval-Augmented Generation\n\n"
        "**RAG** stands for **Retrieval-Augmented Generation**.\n\n"
        "It works in three steps:\n"
        "1. Indexing: split docs into chunks.\n"
        "2. Retrieval: fetch the most similar chunks.\n"
        "3. Generation: feed chunks into the LLM.\n\n"
        "```python\n"
        "def retrieve(query):\n"
        "    return vector_db.query(query)\n"
        "```\n"
    )
    out = _truncate_with_ellipsis(_strip_markdown_to_text(md), SRS_ANSWER_MAX)
    assert "**" not in out
    assert "##" not in out
    assert "```" not in out
    assert "def retrieve" not in out
    assert "RAG" in out
    assert len(out) <= SRS_ANSWER_MAX + 1


def test_caps_are_sane() -> None:
    """Sanity check: prompt cap is short enough for a single warm-up
    headline; answer cap is short enough that it fits 3 lines on the
    Today tile without scroll."""
    assert SRS_PROMPT_MAX < SRS_ANSWER_MAX
    assert 60 <= SRS_PROMPT_MAX <= 120
    assert 180 <= SRS_ANSWER_MAX <= 320
