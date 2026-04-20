"""P3-2 — backend tests for POST /api/v1/chat/flashcards.

Uses the standard in-memory SQLite test DB and the `client` fixture from
conftest.py. The spaced_repetition agent is monkeypatched so the test
does not require a live Anthropic API key.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.agents.base_agent import AgentState
from app.agents import registry as agent_registry_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_state(base_state: AgentState) -> AgentState:
    """Return a fake result state with a Q/A pair embedded."""
    return base_state.model_copy(
        update={
            "response": (
                '{"next_review_in_days": 1, "ease_factor": 2.5, '
                '"interval_days": 1, "due_cards": [], "cards_reviewed": 0}'
            )
        }
    )


# ---------------------------------------------------------------------------
# JWT helper (matches conftest's pattern from test_api/ tests)
# ---------------------------------------------------------------------------


async def _register_and_login(client: AsyncClient) -> str:
    """Register a throw-away user and return the access token."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "flashtest@example.com",
            "password": "Passw0rd!",
            "full_name": "Flash Test",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "flashtest@example.com", "password": "Passw0rd!"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_extract_flashcards_returns_200(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/v1/chat/flashcards returns 200 and a cards_added count."""
    # Ensure the spaced_repetition agent is registered.
    import app.agents.spaced_repetition  # noqa: F401

    # Monkeypatch execute so we don't need a real LLM key.
    from app.agents.spaced_repetition import SpacedRepetitionAgent

    async def _fake_execute(self: SpacedRepetitionAgent, state: AgentState) -> AgentState:
        return _make_fake_state(state)

    monkeypatch.setattr(SpacedRepetitionAgent, "execute", _fake_execute)

    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/chat/flashcards",
        json={
            "message_id": "msg-abc-123",
            "content": "Q: What is RAG?\nA: Retrieval-Augmented Generation.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "cards_added" in body
    assert isinstance(body["cards_added"], int)
    assert body["cards_added"] >= 1


@pytest.mark.anyio
async def test_extract_flashcards_requires_auth(client: AsyncClient) -> None:
    """POST /api/v1/chat/flashcards returns 401 without a token."""
    resp = await client.post(
        "/api/v1/chat/flashcards",
        json={"message_id": "x", "content": "some content"},
    )
    assert resp.status_code == 401
