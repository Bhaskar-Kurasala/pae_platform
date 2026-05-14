
import pytest
from httpx import AsyncClient


async def _admin_token(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "admintest@example.com", "full_name": "Admin", "password": "admin12345678", "role": "admin"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admintest@example.com", "password": "admin12345678"},
    )
    return resp.json()["access_token"]


async def _student_token(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "stutest@example.com", "full_name": "Student", "password": "pass12345678"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "stutest@example.com", "password": "pass12345678"},
    )
    return resp.json()["access_token"]


async def _register_student_get_id(
    client: AsyncClient, email: str, full_name: str = "Target", extra: dict | None = None
) -> str:
    """Register a student and return their user_id via /me (D-B: register returns 202 not user data)."""
    payload: dict = {"email": email, "full_name": full_name, "password": "pass12345678"}
    if extra:
        payload.update(extra)
    await client.post("/api/v1/auth/register", json=payload)
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "pass12345678"}
    )
    token = login.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return str(me.json()["id"])


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
    assert len(agents) >= 17  # Agents registered via @register decorator (agentic agents use separate registry)


@pytest.mark.asyncio
async def test_admin_students_list(client: AsyncClient) -> None:
    token = await _admin_token(client)
    # Register a student first
    await client.post(
        "/api/v1/auth/register",
        json={"email": "teststudent2@example.com", "full_name": "Test Student", "password": "pass12345678"},
    )
    resp = await client.get("/api/v1/admin/students", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    students = resp.json()
    assert isinstance(students, list)


@pytest.mark.asyncio
async def test_admin_log_manual_outreach_writes_outreach_log(
    client: AsyncClient,
) -> None:
    """D16/CP3.2 — POST /students/{id}/outreach writes outreach_log row.

    Channel='whatsapp' (default), triggered_by='admin_manual',
    triggered_by_user_id=<admin>, status='sent'.
    """
    admin_token = await _admin_token(client)
    student_id = await _register_student_get_id(
        client,
        "outreach-target@example.com",
        "Outreach Target",
        extra={"whatsapp_number": "+919999988888"},
    )

    resp = await client.post(
        f"/api/v1/admin/students/{student_id}/outreach",
        json={"channel": "whatsapp", "body_preview": "called via WA, will follow up Wed"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["channel"] == "whatsapp"
    assert body["triggered_by"] == "admin_manual"
    assert body["triggered_by_user_id"] is not None
    assert body["status"] == "sent"
    assert body["body_preview"] == "called via WA, will follow up Wed"


@pytest.mark.asyncio
async def test_admin_log_manual_outreach_phone_channel(client: AsyncClient) -> None:
    """D16/CP3.2 — channel='phone' is also accepted for voice-call records."""
    admin_token = await _admin_token(client)
    student_id = await _register_student_get_id(client, "phone-target@example.com", "Phone Target")

    resp = await client.post(
        f"/api/v1/admin/students/{student_id}/outreach",
        json={"channel": "phone"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["channel"] == "phone"


@pytest.mark.asyncio
async def test_admin_log_manual_outreach_rejects_unknown_channel(
    client: AsyncClient,
) -> None:
    """D16/CP3.2 — only whatsapp + phone allowed; email/in_app go through
    their own service paths and shouldn't be admin-loggable retroactively."""
    admin_token = await _admin_token(client)
    student_id = await _register_student_get_id(client, "reject-target@example.com", "Reject")

    resp = await client.post(
        f"/api/v1/admin/students/{student_id}/outreach",
        json={"channel": "email"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400
    assert "channel" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_log_manual_outreach_surfaces_on_timeline(
    client: AsyncClient,
) -> None:
    """D16/CP3.3 — outreach_log rows surface on /students/{id}/timeline
    with kind='outreach' and channel in the detail dict.

    Verifies the round trip: log a WhatsApp contact via the CP3.2
    endpoint, then fetch the timeline; the new event should be present
    with the correct kind + channel, so the frontend badge renders.
    """
    admin_token = await _admin_token(client)
    student_id = await _register_student_get_id(client, "timeline-target@example.com", "Timeline Target")

    log_resp = await client.post(
        f"/api/v1/admin/students/{student_id}/outreach",
        json={"channel": "whatsapp", "body_preview": "called via WA"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert log_resp.status_code == 201

    timeline_resp = await client.get(
        f"/api/v1/admin/students/{student_id}/timeline",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert timeline_resp.status_code == 200
    events = timeline_resp.json()

    outreach_events = [e for e in events if e["kind"] == "outreach"]
    assert len(outreach_events) >= 1
    out = outreach_events[0]
    assert out["detail"]["channel"] == "whatsapp"
    assert out["detail"]["triggered_by"] == "admin_manual"
    assert "Admin contacted via whatsapp" in out["summary"]


@pytest.mark.asyncio
async def test_admin_log_manual_outreach_requires_admin(
    client: AsyncClient,
) -> None:
    """Non-admin can't log outreach against another student."""
    student_token = await _student_token(client)
    other_id = await _register_student_get_id(client, "other-target@example.com", "Other")

    resp = await client.post(
        f"/api/v1/admin/students/{other_id}/outreach",
        json={"channel": "whatsapp"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 403


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
