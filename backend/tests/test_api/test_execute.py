import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "exec@example.com",
            "full_name": "Exec Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "exec@example.com", "password": "pass1234"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_execute_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/execute", json={"code": "print('x')"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_execute_runs_code(client: AsyncClient) -> None:
    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/execute",
        json={"code": "print('hi')"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stdout"].strip() == "hi"
    assert body["exit_code"] == 0
    assert body["timed_out"] is False
    assert body["error"] is None


@pytest.mark.asyncio
async def test_execute_returns_trace_events(client: AsyncClient) -> None:
    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/execute",
        json={"code": "a = 1\nb = 2\nprint(a + b)"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stdout"].strip() == "3"
    assert len(body["events"]) >= 2
    # Each event: {line, locals}
    for ev in body["events"]:
        assert "line" in ev and "locals" in ev


@pytest.mark.asyncio
async def test_execute_captures_runtime_error(client: AsyncClient) -> None:
    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/execute",
        json={"code": "1/0"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is not None
    assert "ZeroDivisionError" in body["error"]


@pytest.mark.asyncio
async def test_execute_enforces_timeout(client: AsyncClient) -> None:
    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/execute",
        json={"code": "while True: pass", "timeout_seconds": 1.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["timed_out"] is True
