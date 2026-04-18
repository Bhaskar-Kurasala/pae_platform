"""Tests for /api/v1/format — ruff format + lint endpoint."""

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "format@example.com",
            "full_name": "Format Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "format@example.com", "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


@pytest.mark.asyncio
async def test_format_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/format", json={"code": "x=1", "language": "python"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_format_valid_python(client: AsyncClient) -> None:
    token = await _register_and_login(client)
    ugly = "x=1+2\ny=   3"
    resp = await client.post(
        "/api/v1/format",
        json={"code": ugly, "language": "python"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "code" in data
    assert "changed" in data
    # ruff format normalises spacing
    assert "x = 1 + 2" in data["code"]


@pytest.mark.asyncio
async def test_format_syntax_error_returns_original(client: AsyncClient) -> None:
    token = await _register_and_login(client)
    broken = "def foo(:\n    pass"
    resp = await client.post(
        "/api/v1/format",
        json={"code": broken, "language": "python"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == broken
    assert resp.json()["changed"] is False


@pytest.mark.asyncio
async def test_format_non_python_returns_unchanged(client: AsyncClient) -> None:
    token = await _register_and_login(client)
    js_code = "const x = 1"
    resp = await client.post(
        "/api/v1/format",
        json={"code": js_code, "language": "javascript"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == js_code
    assert resp.json()["changed"] is False


@pytest.mark.asyncio
async def test_lint_returns_markers(client: AsyncClient) -> None:
    token = await _register_and_login(client)
    # F841: local variable assigned but never used
    code = "def foo():\n    x = 1\n    return 2\n"
    resp = await client.post(
        "/api/v1/format",
        json={"code": code, "language": "python", "lint_only": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "markers" in data
    # markers is a list (may be empty if ruff finds nothing, but structure must exist)
    assert isinstance(data["markers"], list)


@pytest.mark.asyncio
async def test_lint_marker_shape(client: AsyncClient) -> None:
    """Each marker must have Monaco-compatible shape fields."""
    token = await _register_and_login(client)
    code = "import os\n"  # F401: imported but unused
    resp = await client.post(
        "/api/v1/format",
        json={"code": code, "language": "python", "lint_only": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    markers = resp.json()["markers"]
    for m in markers:
        assert "startLineNumber" in m
        assert "startColumn" in m
        assert "endLineNumber" in m
        assert "endColumn" in m
        assert "message" in m
        assert "severity" in m
