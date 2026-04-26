"""Route tests for /api/v1/readiness/overview and /api/v1/readiness/proof."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.compiler import compiles


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(_type, _compiler, **_kw) -> str:  # type: ignore[no-untyped-def]
    return "TEXT"


def _visit_array(self, _type, **_kw):  # type: ignore[no-untyped-def]
    return "TEXT"


SQLiteTypeCompiler.visit_ARRAY = _visit_array  # type: ignore[attr-defined]


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Overview Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


@pytest.mark.asyncio
async def test_overview_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/readiness/overview")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_proof_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/readiness/proof")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_overview_returns_full_schema_for_blank_user(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "ovw-blank@test.dev")
    resp = await client.get(
        "/api/v1/readiness/overview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {
        "user_first_name",
        "target_role",
        "overall_readiness",
        "sub_scores",
        "north_star",
        "top_actions",
        "latest_verdict",
        "trend_8w",
    }.issubset(body.keys())
    assert body["user_first_name"] == "Overview"
    assert body["overall_readiness"] == 0
    assert body["sub_scores"]["skill"] == 0
    assert body["latest_verdict"] is None
    assert isinstance(body["top_actions"], list)
    assert isinstance(body["trend_8w"], list)
    assert len(body["trend_8w"]) == 8


@pytest.mark.asyncio
async def test_proof_returns_empty_arrays_for_blank_user(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "proof-blank@test.dev")
    resp = await client.get(
        "/api/v1/readiness/proof",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["capstone_artifacts"] == []
    assert body["mock_reports"] == []
    assert body["autopsies"] == []
    assert body["ai_reviews"]["count"] == 0
    assert body["ai_reviews"]["last_three"] == []
    assert body["peer_reviews"]["count_received"] == 0
    assert body["peer_reviews"]["count_given"] == 0
    assert body["last_capstone_summary"] is None
