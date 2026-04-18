"""Unit tests for interview service (P2-10).

No LLM calls, no Redis — a tiny in-memory fake lets us pin the session store's
invariants (TTL, append-turn ordering, user isolation) without infra.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.services.interview_service import (
    INTERVIEWER_SYSTEM_PROMPT,
    InterviewSessionStore,
    PROBLEM_BANK,
    debrief_system_prompt,
    pick_problem,
)


class FakeRedis:
    """Minimal async Redis clone for set/get/delete. Ignores TTL for tests."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


def test_problem_bank_non_empty_and_unique_slugs() -> None:
    slugs = [p.slug for p in PROBLEM_BANK]
    assert len(slugs) >= 5
    assert len(set(slugs)) == len(slugs)


def test_pick_problem_is_deterministic_per_user() -> None:
    uid = uuid.uuid4()
    assert pick_problem(uid).slug == pick_problem(uid).slug


def test_pick_problem_rotates_with_offset() -> None:
    uid = uuid.uuid4()
    a = pick_problem(uid, offset=0).slug
    b = pick_problem(uid, offset=1).slug
    # With >=2 problems and offset 1 we must land on a different slug.
    assert a != b


def test_interviewer_prompt_names_hard_rules() -> None:
    # These are the rules that actually make the simulation feel like an interview.
    assert "ONE question at a time" in INTERVIEWER_SYSTEM_PROMPT
    assert "Never give the answer" in INTERVIEWER_SYSTEM_PROMPT
    assert "do NOT" in INTERVIEWER_SYSTEM_PROMPT or "do not" in INTERVIEWER_SYSTEM_PROMPT.lower()


def test_debrief_prompt_requires_json_shape() -> None:
    prompt = debrief_system_prompt(PROBLEM_BANK[0])
    for key in (
        "overall_verdict",
        "headline",
        "axes",
        "technical_depth",
        "tradeoff_reasoning",
        "production_awareness",
        "communication",
        "strongest_moment",
        "biggest_gap",
        "next_focus",
    ):
        assert key in prompt


@pytest.mark.asyncio
async def test_session_create_get_roundtrip() -> None:
    store = InterviewSessionStore(FakeRedis())  # type: ignore[arg-type]
    uid = uuid.uuid4()
    problem = PROBLEM_BANK[0]
    session = await store.create(uid, problem)
    fetched = await store.get(session.session_id)
    assert fetched is not None
    assert fetched.user_id == str(uid)
    assert fetched.problem_slug == problem.slug
    assert fetched.turns == []


@pytest.mark.asyncio
async def test_append_turn_preserves_order() -> None:
    store = InterviewSessionStore(FakeRedis())  # type: ignore[arg-type]
    session = await store.create(uuid.uuid4(), PROBLEM_BANK[0])
    await store.append_turn(session.session_id, "user", "I'd use Pinecone.")
    await store.append_turn(session.session_id, "assistant", "Why Pinecone over pgvector?")
    await store.append_turn(session.session_id, "user", "Managed, proven at scale.")
    fetched = await store.get(session.session_id)
    assert fetched is not None
    assert [t["role"] for t in fetched.turns] == ["user", "assistant", "user"]
    assert [t["content"] for t in fetched.turns] == [
        "I'd use Pinecone.",
        "Why Pinecone over pgvector?",
        "Managed, proven at scale.",
    ]


@pytest.mark.asyncio
async def test_append_to_missing_session_returns_none() -> None:
    store = InterviewSessionStore(FakeRedis())  # type: ignore[arg-type]
    result = await store.append_turn("nonexistent", "user", "hi")
    assert result is None


@pytest.mark.asyncio
async def test_delete_session_makes_get_none() -> None:
    store = InterviewSessionStore(FakeRedis())  # type: ignore[arg-type]
    session = await store.create(uuid.uuid4(), PROBLEM_BANK[0])
    await store.delete(session.session_id)
    assert await store.get(session.session_id) is None


@pytest.mark.asyncio
async def test_two_users_isolated_sessions() -> None:
    store = InterviewSessionStore(FakeRedis())  # type: ignore[arg-type]
    u1 = uuid.uuid4()
    u2 = uuid.uuid4()
    s1 = await store.create(u1, PROBLEM_BANK[0])
    s2 = await store.create(u2, PROBLEM_BANK[1])
    assert s1.session_id != s2.session_id
    got1 = await store.get(s1.session_id)
    got2 = await store.get(s2.session_id)
    assert got1 is not None and got2 is not None
    assert got1.user_id == str(u1)
    assert got2.user_id == str(u2)
