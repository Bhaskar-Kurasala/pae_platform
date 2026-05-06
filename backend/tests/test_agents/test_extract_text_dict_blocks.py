"""D12 CP3 Phase 2 (Bug 10a) — _extract_text dict-block handling.

The pre-fix _extract_text in career_coach_v2, study_planner_v2, and
resume_reviewer_v2 used `hasattr(block, "type")`, which silently fails
on dict-shape content blocks (MiniMax Anthropic-compatible endpoint).
The fix adds explicit dict-vs-object branching.

These tests stub LangChain-style responses with both content shapes and
verify _extract_text returns the right text. Critical regression pin —
without these, a future revert to hasattr-only would silently break
every D12 agent under MiniMax again.

Three tests per agent file (one per shape), six agents covered:
  career_coach_v2._extract_text
  study_planner_v2._extract_text
  resume_reviewer_v2._extract_text
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.career_coach_v2 import _extract_text as cc_extract
from app.agents.resume_reviewer_v2 import _extract_text as rr_extract
from app.agents.study_planner_v2 import _extract_text as sp_extract


class _FakeResponse:
    """Minimal LangChain response stand-in."""

    def __init__(self, content: Any) -> None:
        self.content = content


class _FakeBlock:
    """Anthropic-SDK-style content block (object with .type / .text)."""

    def __init__(self, type_: str, text: str) -> None:
        self.type = type_
        self.text = text


# ── career_coach_v2._extract_text ──────────────────────────────────


class TestCareerCoachExtractText:
    def test_handles_dict_blocks(self) -> None:
        """Dict-shape (MiniMax): {'type': 'text', 'text': 'hello'}."""
        response = _FakeResponse(
            [{"type": "text", "text": "career coach output"}]
        )
        assert cc_extract(response) == "career coach output"

    def test_skips_thinking_blocks(self) -> None:
        """Dict-shape with thinking + text: thinking skipped, text returned."""
        response = _FakeResponse(
            [
                {"type": "thinking", "thinking": "reasoning here", "signature": "x"},
                {"type": "text", "text": "the actual answer"},
            ]
        )
        assert cc_extract(response) == "the actual answer"

    def test_handles_object_blocks(self) -> None:
        """Object-shape (Anthropic SDK native) still works for backward compat."""
        response = _FakeResponse([_FakeBlock("text", "sdk-shaped answer")])
        assert cc_extract(response) == "sdk-shaped answer"


# ── study_planner_v2._extract_text ─────────────────────────────────


class TestStudyPlannerExtractText:
    def test_handles_dict_blocks(self) -> None:
        response = _FakeResponse([{"type": "text", "text": "study plan json"}])
        assert sp_extract(response) == "study plan json"

    def test_skips_thinking_blocks(self) -> None:
        response = _FakeResponse(
            [
                {"type": "thinking", "thinking": "...", "signature": "y"},
                {"type": "text", "text": "the plan"},
            ]
        )
        assert sp_extract(response) == "the plan"

    def test_handles_object_blocks(self) -> None:
        response = _FakeResponse([_FakeBlock("text", "object plan")])
        assert sp_extract(response) == "object plan"


# ── resume_reviewer_v2._extract_text ───────────────────────────────


class TestResumeReviewerExtractText:
    def test_handles_dict_blocks(self) -> None:
        response = _FakeResponse(
            [{"type": "text", "text": "resume review output"}]
        )
        assert rr_extract(response) == "resume review output"

    def test_skips_thinking_blocks(self) -> None:
        response = _FakeResponse(
            [
                {"type": "thinking", "thinking": "..."},
                {"type": "text", "text": "the review"},
            ]
        )
        assert rr_extract(response) == "the review"

    def test_handles_object_blocks(self) -> None:
        response = _FakeResponse([_FakeBlock("text", "object review")])
        assert rr_extract(response) == "object review"


# ── shared edge cases ──────────────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.parametrize(
        "fn", [cc_extract, sp_extract, rr_extract], ids=["cc", "sp", "rr"]
    )
    def test_string_content_passes_through(self, fn: Any) -> None:
        """Anthropic Claude (non-MiniMax) returns plain str content."""
        response = _FakeResponse("plain string content")
        assert fn(response) == "plain string content"

    @pytest.mark.parametrize(
        "fn", [cc_extract, sp_extract, rr_extract], ids=["cc", "sp", "rr"]
    )
    def test_empty_content_list_returns_empty_string(self, fn: Any) -> None:
        """An empty list (e.g., model emitted no content) returns ''."""
        response = _FakeResponse([])
        assert fn(response) == ""

    @pytest.mark.parametrize(
        "fn", [cc_extract, sp_extract, rr_extract], ids=["cc", "sp", "rr"]
    )
    def test_only_thinking_blocks_returns_empty_string(self, fn: Any) -> None:
        """All blocks are thinking → no text to return; '' (don't crash)."""
        response = _FakeResponse(
            [
                {"type": "thinking", "thinking": "..."},
                {"type": "thinking", "thinking": "..."},
            ]
        )
        assert fn(response) == ""
