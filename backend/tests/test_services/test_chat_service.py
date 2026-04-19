"""Unit tests for the pure helpers in `app.services.chat_service`.

These live next to the rest of the service tests so a failing helper is
obvious at a glance instead of buried inside the big integration test
file for the chat routes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.chat_service import (
    derive_title,
    estimate_tokens,
    format_conversation_markdown,
)


def test_derive_title_truncates_long_messages() -> None:
    long_msg = "Explain transformer attention in painful detail " * 20
    title = derive_title(long_msg)
    assert len(title) <= 60
    # Ellipsis tail signals truncation.
    assert title.endswith("\u2026")


def test_derive_title_collapses_whitespace() -> None:
    messy = "Hello    there\n\nhow\tare you?"
    assert derive_title(messy) == "Hello there how are you?"


def test_derive_title_falls_back_for_empty_input() -> None:
    assert derive_title("") == "New conversation"
    assert derive_title("   \n\t") == "New conversation"


def test_estimate_tokens_is_roughly_one_per_four_chars() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("short") >= 1
    # 80 chars → ~20 tokens
    assert estimate_tokens("x" * 80) == 20


# ---------------------------------------------------------------------------
# format_conversation_markdown — P1-9
# ---------------------------------------------------------------------------


def _mk_conv(title: str | None = "My thread", agent_name: str | None = None):
    # SimpleNamespace is enough: the formatter only reads attributes.
    return SimpleNamespace(
        id=uuid.UUID("12345678-1234-1234-1234-123456789abc"),
        title=title,
        agent_name=agent_name,
        created_at=datetime(2026, 4, 19, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 4, 19, 11, 0, tzinfo=UTC),
    )


def _mk_msg(role: str, content: str, *, agent_name: str | None = None, at: datetime | None = None):
    return SimpleNamespace(
        role=role,
        content=content,
        agent_name=agent_name,
        created_at=at or datetime(2026, 4, 19, 10, 30, tzinfo=UTC),
    )


def test_format_markdown_is_deterministic_with_fixed_now() -> None:
    conv = _mk_conv(title="RAG basics")
    now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    messages = [
        _mk_msg("user", "What is RAG?", at=datetime(2026, 4, 19, 10, 30, tzinfo=UTC)),
        _mk_msg(
            "assistant",
            "Retrieval-Augmented Generation …",
            agent_name="socratic_tutor",
            at=datetime(2026, 4, 19, 10, 31, tzinfo=UTC),
        ),
    ]
    out = format_conversation_markdown(conv, messages, now=now)

    # Top of file is a stable snapshot.
    assert out.startswith("# RAG basics\n")
    assert "Exported: 2026-04-19T12:00:00+00:00" in out
    assert "Agent: socratic_tutor" in out
    assert "Messages: 2" in out
    assert "## You · 2026-04-19 10:30" in out
    assert "## Tutor (socratic_tutor) · 2026-04-19 10:31" in out
    assert "What is RAG?" in out
    assert "Retrieval-Augmented Generation" in out
    # Ends with a trailing newline, no stray trailing "---".
    assert out.endswith("\n")
    # The *last* divider should have been stripped: the final non-empty line
    # must be the last message body, not '---'.
    non_empty = [line for line in out.splitlines() if line.strip()]
    assert non_empty[-1] != "---"


def test_format_markdown_passes_through_markdown_in_assistant_content() -> None:
    """Assistant replies with their own `##` / code fences are rendered as-is."""
    conv = _mk_conv(title="Passthrough")
    raw_content = "## Inner heading\n\n```python\nprint('hi')\n```"
    messages = [
        _mk_msg("assistant", raw_content, agent_name="coding_assistant"),
    ]
    out = format_conversation_markdown(conv, messages)
    # Content is preserved verbatim (no escaping of '##').
    assert raw_content in out
    # And the outer section header is still the Tutor one.
    assert "## Tutor (coding_assistant)" in out


def test_format_markdown_handles_empty_messages_list() -> None:
    conv = _mk_conv(title="Nothing here")
    out = format_conversation_markdown(conv, [], now=datetime(2026, 4, 19, 12, 0, tzinfo=UTC))
    assert out.startswith("# Nothing here\n")
    assert "Messages: 0" in out
    # No role sections.
    assert "## You" not in out
    assert "## Tutor" not in out


def test_format_markdown_assistant_without_agent_omits_parens() -> None:
    conv = _mk_conv(title="Pre-routing")
    messages = [
        _mk_msg("assistant", "Hi there.", agent_name=None),
    ]
    out = format_conversation_markdown(conv, messages)
    assert "## Tutor · " in out
    assert "## Tutor (" not in out


def test_format_markdown_mixed_agents_uses_mixed_label() -> None:
    conv = _mk_conv(title="Multi-agent")
    messages = [
        _mk_msg("assistant", "A", agent_name="socratic_tutor"),
        _mk_msg("assistant", "B", agent_name="coding_assistant"),
    ]
    out = format_conversation_markdown(conv, messages)
    assert "Agent: Mixed" in out


def test_format_markdown_falls_back_to_untitled() -> None:
    conv = _mk_conv(title=None)
    out = format_conversation_markdown(conv, [])
    assert out.startswith("# Untitled conversation")
