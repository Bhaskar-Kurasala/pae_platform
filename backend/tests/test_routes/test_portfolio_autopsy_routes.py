"""Route tests for /api/v1/receipts/autopsy persistence + listing.

The autopsy LLM is monkeypatched so these stay hermetic and fast. Auth flow
follows `tests/test_routes/test_today_summary_route.py` (register + login).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes import portfolio_autopsy as autopsy_route
from app.models.portfolio_autopsy_result import PortfolioAutopsyResult
from app.services import (
    portfolio_autopsy_persistence_service as persistence_service,
)
from app.services.portfolio_autopsy_service import (
    AutopsyAxis,
    AutopsyFinding,
    PortfolioAutopsy,
)


def _fake_autopsy(headline: str = "Ships, but missing prod rails.") -> PortfolioAutopsy:
    return PortfolioAutopsy(
        headline=headline,
        overall_score=72,
        architecture=AutopsyAxis(score=3, assessment="Single-file Flask app."),
        failure_handling=AutopsyAxis(score=3, assessment="Some retries."),
        observability=AutopsyAxis(score=2, assessment="No structured logging."),
        scope_discipline=AutopsyAxis(score=4, assessment="Tight scope."),
        what_worked=["Tight scope", "Smoke-test notebook"],
        what_to_do_differently=[
            AutopsyFinding(
                issue="Embeddings recomputed per request.",
                why_it_matters="Each query is a paid round-trip.",
                what_to_do_differently="Precompute at ingest.",
            ),
            AutopsyFinding(
                issue="No rate-limit handling.",
                why_it_matters="429s crash the request.",
                what_to_do_differently="Wrap with exponential backoff.",
            ),
        ],
        production_gaps=["No auth"],
        next_project_seed="Multi-tenant RAG with row-level access control.",
    )


def _payload() -> dict:
    return {
        "project_title": "Tiny RAG demo",
        "project_description": (
            "A small RAG over my notes; Flask + OpenAI + FAISS. "
            "Used as a learning project for retrieval pipelines."
        ),
        "code": "def search(q): ...",
    }


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Autopsy Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


# ---------------------------------------------------------------------------
# POST persists + returns 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_autopsy_persists_row_and_returns_200(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _stub(**kwargs: object) -> PortfolioAutopsy:
        return _fake_autopsy()

    monkeypatch.setattr(autopsy_route, "run_autopsy", _stub)

    token = await _register_and_login(client, "post-persist@test.dev")
    resp = await client.post(
        "/api/v1/receipts/autopsy",
        json=_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_score"] == 72
    assert body["architecture"]["score"] == 3
    assert len(body["what_to_do_differently"]) == 2

    rows = (
        (await db_session.execute(select(PortfolioAutopsyResult)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.project_title == "Tiny RAG demo"
    assert row.overall_score == 72
    assert row.axes["scope_discipline"]["score"] == 4


# ---------------------------------------------------------------------------
# GET list — auth required + returns own autopsies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_autopsy_list_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/receipts/autopsy")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_autopsy_list_returns_users_autopsies(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _stub(**kwargs: object) -> PortfolioAutopsy:
        return _fake_autopsy(headline=f"Run for {kwargs.get('project_title')}")

    monkeypatch.setattr(autopsy_route, "run_autopsy", _stub)

    token = await _register_and_login(client, "list@test.dev")
    headers = {"Authorization": f"Bearer {token}"}

    # Seed two rows via POST so we exercise the full persistence path.
    p1 = _payload() | {"project_title": "First"}
    p2 = _payload() | {"project_title": "Second"}
    r1 = await client.post("/api/v1/receipts/autopsy", json=p1, headers=headers)
    r2 = await client.post("/api/v1/receipts/autopsy", json=p2, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200

    listing = await client.get("/api/v1/receipts/autopsy", headers=headers)
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 2
    titles = {item["project_title"] for item in items}
    assert titles == {"First", "Second"}
    for item in items:
        assert "id" in item
        assert "headline" in item
        assert "overall_score" in item
        assert "created_at" in item


# ---------------------------------------------------------------------------
# GET detail — 404 for foreign user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_autopsy_detail_404_for_foreign_user(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _stub(**kwargs: object) -> PortfolioAutopsy:
        return _fake_autopsy()

    monkeypatch.setattr(autopsy_route, "run_autopsy", _stub)

    owner_token = await _register_and_login(client, "owner@test.dev")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    create = await client.post(
        "/api/v1/receipts/autopsy", json=_payload(), headers=owner_headers
    )
    assert create.status_code == 200
    listing = await client.get("/api/v1/receipts/autopsy", headers=owner_headers)
    autopsy_id = listing.json()[0]["id"]

    # Owner positive control.
    own_detail = await client.get(
        f"/api/v1/receipts/autopsy/{autopsy_id}", headers=owner_headers
    )
    assert own_detail.status_code == 200
    assert own_detail.json()["id"] == autopsy_id

    # Foreign user — 404, not 403, so we don't leak existence.
    other_token = await _register_and_login(client, "stranger@test.dev")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    foreign = await client.get(
        f"/api/v1/receipts/autopsy/{autopsy_id}", headers=other_headers
    )
    assert foreign.status_code == 404

    # And an unknown UUID — also 404.
    missing = await client.get(
        f"/api/v1/receipts/autopsy/{uuid.uuid4()}", headers=owner_headers
    )
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# POST still 200 when persistence fails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_autopsy_returns_200_even_when_persistence_raises(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _stub(**kwargs: object) -> PortfolioAutopsy:
        return _fake_autopsy()

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("DB on fire")

    monkeypatch.setattr(autopsy_route, "run_autopsy", _stub)
    # Patch the symbol the route imported (route did `from ... import persist_...`).
    monkeypatch.setattr(autopsy_route, "persist_autopsy_result", _boom)
    # Also patch the source module — defensive, so the test passes regardless of
    # whether the route uses the local-imported binding or re-imports.
    monkeypatch.setattr(persistence_service, "persist_autopsy_result", _boom)

    token = await _register_and_login(client, "noisy-db@test.dev")
    resp = await client.post(
        "/api/v1/receipts/autopsy",
        json=_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_score"] == 72
    assert body["headline"] == "Ships, but missing prod rails."
