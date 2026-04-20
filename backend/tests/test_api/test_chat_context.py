"""Tests for the P1-7 chat context-attach surface.

Covers:
  - GET /api/v1/chat/context-suggestions requires auth
  - Suggestions returns user's own submissions + current-lesson heuristic
  - Explicit lesson_id override scopes the picker to that lesson
  - POST /api/v1/agents/stream with context_refs prepends a resolved prefix
  - Submission ownership: cross-user refs collapse to 404
  - Pydantic rejects > 3 refs with 422
  - Lesson / exercise refs work without ownership check
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base, get_db
from app.main import app
from app.models.course import Course
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.lesson import Lesson
from app.models.student_progress import StudentProgress
from app.models.user import User

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def client_and_factory() -> AsyncGenerator[
    tuple[AsyncClient, async_sessionmaker[AsyncSession]], None
]:
    """Per-test client paired with a session factory the test can use directly
    to seed rows the HTTP surface doesn't expose (lessons / progress / etc.)."""
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

    with (
        patch("app.core.database.AsyncSessionLocal", session_factory),
        patch("app.api.v1.routes.stream.AsyncSessionLocal", session_factory),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Forwarded-For": "127.0.0.1"},
        ) as ac:
            yield ac, session_factory

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


class _CapturingLLM:
    """Fake LLM that records the messages passed in so we can assert on the
    structured content blocks / prefix the stream route sent to Claude."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self.captured_messages: list[Any] | None = None

    async def astream(self, messages: list[Any]) -> AsyncIterator[Any]:
        self.captured_messages = messages

        class _Chunk:
            def __init__(self, text: str) -> None:
                self.content = text

        for t in self._tokens:
            yield _Chunk(t)


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


async def _user_id_for(
    factory: async_sessionmaker[AsyncSession], email: str
) -> uuid.UUID:
    from sqlalchemy import select

    async with factory() as session:
        row = await session.execute(select(User).where(User.email == email))
        user = row.scalar_one()
        return user.id


async def _seed_course_lesson_exercise(
    factory: async_sessionmaker[AsyncSession],
    *,
    lesson_title: str = "Intro Lesson",
    exercise_title: str = "Warm-up Exercise",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Insert a Course → Lesson → Exercise chain and return their ids."""
    async with factory() as session:
        course = Course(
            title="Test Course",
            slug=f"test-course-{uuid.uuid4().hex[:8]}",
            description="Seed",
        )
        session.add(course)
        await session.flush()
        lesson = Lesson(
            course_id=course.id,
            title=lesson_title,
            slug=f"intro-{uuid.uuid4().hex[:8]}",
            description="A gentle introduction to the topic.",
            order=1,
        )
        session.add(lesson)
        await session.flush()
        exercise = Exercise(
            lesson_id=lesson.id,
            title=exercise_title,
            description="Implement add(a, b).",
            order=1,
        )
        session.add(exercise)
        await session.flush()
        await session.commit()
        return course.id, lesson.id, exercise.id


# ---------------------------------------------------------------------------
# GET /context-suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_requires_auth(
    client_and_factory: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = client_and_factory
    resp = await client.get("/api/v1/chat/context-suggestions")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_suggestions_returns_own_submissions(
    client_and_factory: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = client_and_factory
    token = await _register_and_login(client, "ctx_subs@example.com")
    user_id = await _user_id_for(factory, "ctx_subs@example.com")

    _, lesson_id, exercise_id = await _seed_course_lesson_exercise(
        factory, exercise_title="Fibonacci"
    )

    async with factory() as session:
        session.add(
            ExerciseSubmission(
                student_id=user_id,
                exercise_id=exercise_id,
                code="def fib(n): ...",
            )
        )
        await session.commit()

    resp = await client.get(
        "/api/v1/chat/context-suggestions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["submissions"]) == 1
    assert body["submissions"][0]["exercise_title"] == "Fibonacci"
    # No lesson/exercise surfaced because the user has no progress on any
    # lesson yet — the picker correctly returns empty sections in that case.
    assert body["lessons"] == []
    assert body["exercises"] == []
    # Sanity — keep lesson in the DB for later tests in the same file.
    assert lesson_id


@pytest.mark.asyncio
async def test_suggestions_current_lesson_heuristic(
    client_and_factory: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """When the user has a StudentProgress row, the most-recently-updated
    lesson surfaces as the 'current' lesson and its exercises tag along."""
    client, factory = client_and_factory
    token = await _register_and_login(client, "ctx_lesson@example.com")
    user_id = await _user_id_for(factory, "ctx_lesson@example.com")

    _, lesson_id, exercise_id = await _seed_course_lesson_exercise(
        factory, lesson_title="RAG 101", exercise_title="Embeddings Lab"
    )

    async with factory() as session:
        session.add(
            StudentProgress(
                student_id=user_id, lesson_id=lesson_id, status="in_progress"
            )
        )
        await session.commit()

    resp = await client.get(
        "/api/v1/chat/context-suggestions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [l["title"] for l in body["lessons"]] == ["RAG 101"]
    assert [e["title"] for e in body["exercises"]] == ["Embeddings Lab"]
    assert body["lessons"][0]["id"] == str(lesson_id)
    assert body["exercises"][0]["id"] == str(exercise_id)


@pytest.mark.asyncio
async def test_suggestions_explicit_lesson_id_override(
    client_and_factory: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """`lesson_id` query arg beats the 'most recently visited' heuristic."""
    client, factory = client_and_factory
    token = await _register_and_login(client, "ctx_override@example.com")
    user_id = await _user_id_for(factory, "ctx_override@example.com")

    # Two lessons. Progress row points at A; override explicitly asks for B.
    _, lesson_a_id, _ = await _seed_course_lesson_exercise(
        factory, lesson_title="Lesson A"
    )
    _, lesson_b_id, _ = await _seed_course_lesson_exercise(
        factory, lesson_title="Lesson B", exercise_title="B1"
    )

    async with factory() as session:
        session.add(
            StudentProgress(
                student_id=user_id, lesson_id=lesson_a_id, status="in_progress"
            )
        )
        await session.commit()

    resp = await client.get(
        f"/api/v1/chat/context-suggestions?lesson_id={lesson_b_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["lessons"][0]["id"] == str(lesson_b_id)
    assert body["lessons"][0]["title"] == "Lesson B"


# ---------------------------------------------------------------------------
# Stream + context_refs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_with_submission_ref_prepends_prefix(
    client_and_factory: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = client_and_factory
    token = await _register_and_login(client, "ctx_stream_sub@example.com")
    user_id = await _user_id_for(factory, "ctx_stream_sub@example.com")

    _, _, exercise_id = await _seed_course_lesson_exercise(
        factory, exercise_title="Palindrome Check"
    )
    async with factory() as session:
        sub = ExerciseSubmission(
            student_id=user_id,
            exercise_id=exercise_id,
            code="def is_palindrome(s):\n    return s == s[::-1]\n",
        )
        session.add(sub)
        await session.commit()
        sub_id = sub.id

    fake_llm = _CapturingLLM(["ok"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={
                "message": "Review my code",
                "context_refs": [
                    {"kind": "submission", "id": str(sub_id)},
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        async for _ in resp.aiter_bytes():
            pass

    assert fake_llm.captured_messages is not None
    human = fake_llm.captured_messages[-1]
    # No attachments → content is still a string with the prefix prepended.
    assert isinstance(human.content, str)
    assert "### Submission: Palindrome Check" in human.content
    assert "is_palindrome" in human.content
    # Original user text must be preserved after the prefix.
    assert "Review my code" in human.content
    # Prefix precedes user text.
    assert human.content.index("### Submission") < human.content.index(
        "Review my code"
    )


@pytest.mark.asyncio
async def test_stream_submission_ownership_404(
    client_and_factory: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """A user can't attach another user's submission as context."""
    client, factory = client_and_factory
    alice_token = await _register_and_login(client, "ctx_alice@example.com")
    bob_token = await _register_and_login(client, "ctx_bob@example.com")
    alice_id = await _user_id_for(factory, "ctx_alice@example.com")

    _, _, exercise_id = await _seed_course_lesson_exercise(factory)
    async with factory() as session:
        sub = ExerciseSubmission(
            student_id=alice_id, exercise_id=exercise_id, code="alice's"
        )
        session.add(sub)
        await session.commit()
        alice_sub_id = sub.id

    fake_llm = _CapturingLLM(["nope"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={
                "message": "Sneaky",
                "context_refs": [
                    {"kind": "submission", "id": str(alice_sub_id)},
                ],
            },
            headers={"Authorization": f"Bearer {bob_token}"},
        )
    assert resp.status_code == 404
    # Sanity — alice_token still valid after the denied request.
    assert alice_token


@pytest.mark.asyncio
async def test_stream_rejects_over_three_refs_with_422(
    client_and_factory: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = client_and_factory
    token = await _register_and_login(client, "ctx_over@example.com")
    refs = [
        {"kind": "lesson", "id": str(uuid.uuid4())} for _ in range(4)
    ]
    resp = await client.post(
        "/api/v1/agents/stream",
        json={"message": "hi", "context_refs": refs},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_stream_with_lesson_and_exercise_refs(
    client_and_factory: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Lesson + exercise refs are platform content — no ownership gate,
    both titled blocks should land in the prompt."""
    client, factory = client_and_factory
    token = await _register_and_login(client, "ctx_le@example.com")

    _, lesson_id, exercise_id = await _seed_course_lesson_exercise(
        factory, lesson_title="Vectors", exercise_title="Cosine Similarity"
    )

    fake_llm = _CapturingLLM(["thanks"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={
                "message": "Give me a hint",
                "context_refs": [
                    {"kind": "lesson", "id": str(lesson_id)},
                    {"kind": "exercise", "id": str(exercise_id)},
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        async for _ in resp.aiter_bytes():
            pass

    human = fake_llm.captured_messages[-1]  # type: ignore[index]
    assert isinstance(human.content, str)
    assert "### Lesson: Vectors" in human.content
    assert "### Exercise: Cosine Similarity" in human.content
    assert "Give me a hint" in human.content


@pytest.mark.asyncio
async def test_stream_unknown_lesson_ref_404(
    client_and_factory: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = client_and_factory
    token = await _register_and_login(client, "ctx_missing@example.com")
    fake_llm = _CapturingLLM(["nope"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={
                "message": "hi",
                "context_refs": [
                    {"kind": "lesson", "id": str(uuid.uuid4())},
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 404
