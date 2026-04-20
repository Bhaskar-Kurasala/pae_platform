"""Tests for the P3-3 quiz-generation surface.

Covers:
  - auth required (401 without token)
  - POST /api/v1/chat/quiz returns 200 with questions array
  - Fallback placeholder is returned when the LLM agent produces no parseable JSON
  - Each question has the expected fields (question, options, correct_index, explanation)
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Per-test FastAPI client against an in-memory SQLite engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db

    with patch("app.core.database.AsyncSessionLocal", session_factory):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Forwarded-For": "127.0.0.1"},
        ) as ac:
            yield ac

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Test User",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


_MOCK_MCQ_JSON = json.dumps([
    {
        "question": "What problem does RAG primarily solve?",
        "options": {
            "A": "Makes LLMs faster",
            "B": "Grounds responses in retrieved context",
            "C": "Reduces API costs",
            "D": "Enables code generation",
        },
        "correct_answer": "B",
        "explanation": "RAG retrieves documents and injects them as context.",
        "difficulty": "beginner",
        "tags": ["RAG"],
    },
    {
        "question": "Which data store is used in a typical RAG pipeline?",
        "options": {
            "A": "SQL database",
            "B": "Vector store",
            "C": "Graph database",
            "D": "Key-value store",
        },
        "correct_answer": "B",
        "explanation": "A vector store enables similarity-based retrieval.",
        "difficulty": "beginner",
        "tags": ["RAG", "vector store"],
    },
])


class _FakeAIMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, content: str) -> None:
        self._content = content

    async def ainvoke(self, messages: list[Any]) -> _FakeAIMessage:
        return _FakeAIMessage(self._content)


@pytest.mark.asyncio
async def test_quiz_requires_auth(client: AsyncClient) -> None:
    """POST /chat/quiz without a JWT returns 401."""
    resp = await client.post(
        "/api/v1/chat/quiz",
        json={"message_id": "msg-1", "content": "some content"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_quiz_returns_200_with_questions(client: AsyncClient) -> None:
    """POST /chat/quiz with valid auth returns 200 and a non-empty questions array."""
    token = await _register_and_login(client, "quiz_student@example.com")

    fake_llm = _FakeLLM(_MOCK_MCQ_JSON)
    with patch("app.agents.mcq_factory.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/chat/quiz",
            json={
                "message_id": "msg-abc",
                "content": "RAG stands for Retrieval Augmented Generation.",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "questions" in body
    questions = body["questions"]
    assert isinstance(questions, list)
    assert len(questions) >= 1

    # Each question has the required fields
    for q in questions:
        assert "question" in q
        assert "options" in q
        assert "correct_index" in q
        assert "explanation" in q
        assert isinstance(q["options"], list)
        assert isinstance(q["correct_index"], int)


@pytest.mark.asyncio
async def test_quiz_fallback_when_llm_returns_garbage(client: AsyncClient) -> None:
    """When the LLM returns unparseable content the endpoint still returns 200
    with the fallback placeholder question rather than 500."""
    token = await _register_and_login(client, "quiz_fallback@example.com")

    fake_llm = _FakeLLM("this is not valid json !!!!")
    with patch("app.agents.mcq_factory.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/chat/quiz",
            json={"message_id": "msg-bad", "content": "topic content"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["questions"]) >= 1


@pytest.mark.asyncio
async def test_quiz_invalid_payload(client: AsyncClient) -> None:
    """Missing required fields returns 422."""
    token = await _register_and_login(client, "quiz_invalid@example.com")

    resp = await client.post(
        "/api/v1/chat/quiz",
        json={"message_id": "x"},  # missing 'content'
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
