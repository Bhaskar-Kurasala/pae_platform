
import pytest
from httpx import AsyncClient


async def _admin_token(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "admintest@example.com", "full_name": "Admin", "password": "admin1234", "role": "admin"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admintest@example.com", "password": "admin1234"},
    )
    return resp.json()["access_token"]


async def _student_token(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "stutest@example.com", "full_name": "Student", "password": "pass1234"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "stutest@example.com", "password": "pass1234"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_admin_stats_requires_admin(client: AsyncClient) -> None:
    token = await _student_token(client)
    resp = await client.get("/api/v1/admin/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_stats_returns_data(client: AsyncClient) -> None:
    token = await _admin_token(client)
    resp = await client.get("/api/v1/admin/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert "total_students" in data
    assert "mrr_usd" in data
    assert "total_agent_actions" in data


@pytest.mark.asyncio
async def test_admin_agents_health(client: AsyncClient) -> None:
    token = await _admin_token(client)
    resp = await client.get("/api/v1/admin/agents/health", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    agents = resp.json()
    assert isinstance(agents, list)
    names = [a["name"] for a in agents]
    assert "socratic_tutor" in names
    assert len(agents) >= 20  # All agents registered


@pytest.mark.asyncio
async def test_admin_students_list(client: AsyncClient) -> None:
    token = await _admin_token(client)
    # Register a student first
    await client.post(
        "/api/v1/auth/register",
        json={"email": "teststudent2@example.com", "full_name": "Test Student", "password": "pass1234"},
    )
    resp = await client.get("/api/v1/admin/students", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    students = resp.json()
    assert isinstance(students, list)


@pytest.mark.asyncio
async def test_admin_pulse_returns_5_metrics(client: AsyncClient) -> None:
    token = await _admin_token(client)
    resp = await client.get("/api/v1/admin/pulse", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert "active_students_24h" in data
    assert "agent_calls_24h" in data
    assert "avg_eval_score_24h" in data
    assert "new_enrollments_7d" in data
    assert "open_feedback" in data
    # All values should be numeric
    assert isinstance(data["active_students_24h"], int)
    assert isinstance(data["agent_calls_24h"], int)
    assert isinstance(data["new_enrollments_7d"], int)
    assert isinstance(data["open_feedback"], int)


@pytest.mark.asyncio
async def test_admin_pulse_requires_admin(client: AsyncClient) -> None:
    token = await _student_token(client)
    resp = await client.get("/api/v1/admin/pulse", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
