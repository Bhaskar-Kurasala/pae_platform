"""Route tests for /api/v1/readiness/kit — Application Kit CRUD surface.

We stub the PDF renderer at the service module level so the test suite never
needs WeasyPrint / GTK on Windows CI boxes — the bytes that come back are a
fake `%PDF-fake` blob that's enough to round-trip through the download route.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.compiler import compiles


# ── SQLite shim ─────────────────────────────────────────────────────────
# `notebook_entries.tags` uses postgres ARRAY, which the in-memory SQLite
# engine in tests/conftest.py can't render. Map it to TEXT for the test
# session — we never touch those rows here.
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
            "full_name": "Kit Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


@pytest.fixture(autouse=True)
def _stub_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the kit PDF renderer with a fake. Auto-applies to every test
    in this module — no test should be hitting WeasyPrint."""
    from app.services import application_kit_service

    monkeypatch.setattr(
        application_kit_service.pdf_renderer,
        "render_application_kit",
        lambda manifest: b"%PDF-fake-kit",
    )


@pytest.mark.asyncio
async def test_create_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/readiness/kit", json={"label": "x"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/readiness/kit")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_kit_returns_201(client: AsyncClient) -> None:
    token = await _register_and_login(client, "kit-create@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/v1/readiness/kit",
        headers=headers,
        json={"label": "first-kit", "target_role": "Python Eng"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["label"] == "first-kit"
    assert body["target_role"] == "Python Eng"
    assert body["status"] == "ready"
    assert body["has_pdf"] is True
    assert body["manifest"]["label"] == "first-kit"


@pytest.mark.asyncio
async def test_list_returns_user_kits(client: AsyncClient) -> None:
    token = await _register_and_login(client, "kit-list@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    for label in ("a", "b"):
        resp = await client.post(
            "/api/v1/readiness/kit",
            headers=headers,
            json={"label": label},
        )
        assert resp.status_code == 201

    list_resp = await client.get("/api/v1/readiness/kit", headers=headers)
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 2
    labels = {item["label"] for item in items}
    assert labels == {"a", "b"}
    # manifest_keys should be present (empty for a kit with no source rows).
    for item in items:
        assert "manifest_keys" in item


@pytest.mark.asyncio
async def test_detail_returns_full_manifest(client: AsyncClient) -> None:
    token = await _register_and_login(client, "kit-detail@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    create = await client.post(
        "/api/v1/readiness/kit",
        headers=headers,
        json={"label": "detail-test", "target_role": "PM"},
    )
    kit_id = create.json()["id"]

    detail = await client.get(
        f"/api/v1/readiness/kit/{kit_id}", headers=headers
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == kit_id
    assert body["label"] == "detail-test"
    assert body["manifest"]["label"] == "detail-test"
    assert body["manifest"]["target_role"] == "PM"
    assert "built_at" in body["manifest"]


@pytest.mark.asyncio
async def test_detail_404_for_other_users_kit(client: AsyncClient) -> None:
    alice_token = await _register_and_login(client, "kit-alice@test.dev")
    bob_token = await _register_and_login(client, "kit-bob@test.dev")

    create = await client.post(
        "/api/v1/readiness/kit",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"label": "alice-kit"},
    )
    kit_id = create.json()["id"]

    resp = await client.get(
        f"/api/v1/readiness/kit/{kit_id}",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_returns_pdf_bytes(client: AsyncClient) -> None:
    token = await _register_and_login(client, "kit-download@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    create = await client.post(
        "/api/v1/readiness/kit",
        headers=headers,
        json={"label": "download-me"},
    )
    kit_id = create.json()["id"]

    resp = await client.get(
        f"/api/v1/readiness/kit/{kit_id}/download", headers=headers
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert "download-me" in resp.headers["content-disposition"]
    assert resp.content == b"%PDF-fake-kit"


@pytest.mark.asyncio
async def test_delete_returns_204(client: AsyncClient) -> None:
    token = await _register_and_login(client, "kit-del@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    create = await client.post(
        "/api/v1/readiness/kit",
        headers=headers,
        json={"label": "to-delete"},
    )
    kit_id = create.json()["id"]

    delete = await client.delete(
        f"/api/v1/readiness/kit/{kit_id}", headers=headers
    )
    assert delete.status_code == 204

    follow = await client.get(
        f"/api/v1/readiness/kit/{kit_id}", headers=headers
    )
    assert follow.status_code == 404


@pytest.mark.asyncio
async def test_delete_unowned_returns_404(client: AsyncClient) -> None:
    alice_token = await _register_and_login(client, "kit-del-a@test.dev")
    bob_token = await _register_and_login(client, "kit-del-b@test.dev")

    create = await client.post(
        "/api/v1/readiness/kit",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"label": "alice-only"},
    )
    kit_id = create.json()["id"]

    resp = await client.delete(
        f"/api/v1/readiness/kit/{kit_id}",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert resp.status_code == 404
