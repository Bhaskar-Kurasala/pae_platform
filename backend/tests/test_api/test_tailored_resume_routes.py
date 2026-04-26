"""Integration tests for the tailored resume routes.

LLM calls are stubbed at the service layer so the test asserts orchestration,
quota enforcement, validation behavior, and PDF round-trip — not LLM output
quality.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import jd_parser, profile_aggregator, tailored_resume_service
from app.services.jd_parser import ParsedJd

REGISTER_PAYLOAD = {
    "email": "tailored@example.com",
    "full_name": "Tailored Tester",
    "password": "testpass123",
}


async def _get_token(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_PAYLOAD["email"],
            "password": REGISTER_PAYLOAD["password"],
        },
    )
    return str(resp.json()["access_token"])


@pytest.fixture(autouse=True)
def _enable_feature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "feature_tailored_resume_agent", True)


@pytest.fixture(autouse=True)
def _stub_regenerate_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    """`build_base_resume_bundle` calls `regenerate_resume`, which makes a
    live LLM call. Replace it with a no-op that returns the cached row."""
    from app.services import career_service, profile_aggregator as pa

    async def fake_regen(db: Any, *, user_id: Any, force: bool = False) -> Any:
        return await career_service.get_or_create_resume(db, user_id=user_id)

    monkeypatch.setattr(career_service, "regenerate_resume", fake_regen)
    monkeypatch.setattr(pa, "regenerate_resume", fake_regen)


@pytest.fixture
def stub_llm_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub every LLM-touching call site used by the orchestrator."""

    async def fake_parse_jd(jd_text: str) -> ParsedJd:
        return ParsedJd(
            role="Junior Python Developer",
            company="Acme",
            seniority="junior",
            company_stage="startup",
            must_haves=["python", "asyncio"],
            nice_to_haves=["fastapi"],
            key_responsibilities=["build internal tooling"],
            tone_signals=["pragmatic", "scrappy"],
            input_tokens=120,
            output_tokens=180,
            model="claude-haiku-4-5",
        )

    monkeypatch.setattr(jd_parser, "parse_jd", fake_parse_jd)
    monkeypatch.setattr(tailored_resume_service, "parse_jd", fake_parse_jd)

    # The tailoring agent: return a content shape that passes the deterministic
    # validator (uses an evidence_id from the allowlist — `exercise_volume` is
    # always allowlisted by the aggregator).
    async def fake_tailoring_generate(self: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "content": {
                "summary": "Junior Python developer with capstone-level proof.",
                "bullets": [
                    {
                        "text": "Built a CLI AI tool with retry-aware async API calls.",
                        "evidence_id": "exercise_volume",
                        "ats_keywords": ["Python", "asyncio"],
                    }
                ],
                "skills": ["Python", "asyncio", "FastAPI"],
                "ats_keywords": ["Python", "asyncio", "FastAPI"],
                "tailoring_notes": ["matched python", "matched asyncio"],
            },
            "input_tokens": 800,
            "output_tokens": 600,
            "model": "claude-sonnet-4-6",
        }

    from app.agents import tailored_resume as ta_mod

    monkeypatch.setattr(ta_mod.TailoredResumeAgent, "generate", fake_tailoring_generate)

    async def fake_cover_letter_generate(self: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "content": {
                "body": (
                    "Dear Acme team,\n\n"
                    "I am applying for the Junior Python Developer role.\n\n"
                    "I built a CLI AI tool with retry-aware async API calls.\n\n"
                    "I would welcome a conversation."
                ),
                "subject_line": "Application — Junior Python Developer",
            },
            "input_tokens": 400,
            "output_tokens": 200,
            "model": "claude-sonnet-4-6",
        }

    from app.agents import cover_letter as cl_mod

    monkeypatch.setattr(cl_mod.CoverLetterAgent, "generate", fake_cover_letter_generate)

    # The validator's LLM pass — keep deterministic by skipping it.
    from app.services import hallucination_validator as hv_mod

    async def fake_llm_check(**_: Any) -> list[str]:
        return []

    monkeypatch.setattr(hv_mod, "_llm_check", fake_llm_check)

    # ProfileAggregator's `regenerate_resume` does its own LLM call. Sidestep
    # by short-circuiting: build a minimal Resume row through get_or_create.
    async def fake_build_bundle(db: Any, *, user_id: Any) -> Any:
        from app.services.career_service import get_or_create_resume

        resume = await get_or_create_resume(db, user_id=user_id)
        return profile_aggregator.BaseResumeBundle(
            resume=resume,
            skill_map={"python": 0.8, "asyncio": 0.6},
            exercise_count=12,
            intake_data=resume.intake_data or {},
            evidence_allowlist={"python", "asyncio", "exercise_volume"},
        )

    monkeypatch.setattr(profile_aggregator, "build_base_resume_bundle", fake_build_bundle)
    monkeypatch.setattr(tailored_resume_service, "build_base_resume_bundle", fake_build_bundle)


_LONG_JD = (
    "Junior Python Developer at Acme. Looking for a developer comfortable "
    "with Python, asyncio, FastAPI, and writing small production-quality "
    "tools. Must know how to handle errors, rate limits, and environment-"
    "based configuration."
)


@pytest.mark.asyncio
async def test_quota_endpoint_returns_first_resume_free(
    client: AsyncClient,
) -> None:
    token = await _get_token(client)
    resp = await client.get(
        "/api/v1/tailored-resume/quota",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["quota"]["allowed"] is True
    assert body["quota"]["reason"] == "first_resume_free"


@pytest.mark.asyncio
async def test_intake_endpoint_returns_questions(client: AsyncClient, stub_llm_pipeline: None) -> None:
    token = await _get_token(client)
    resp = await client.post(
        "/api/v1/tailored-resume/intake",
        json={"jd_text": _LONG_JD},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert 4 <= len(data["questions"]) <= 7
    assert "quota" in data


@pytest.mark.asyncio
async def test_generate_full_pipeline(client: AsyncClient, stub_llm_pipeline: None) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/v1/tailored-resume/generate",
        json={
            "jd_text": _LONG_JD,
            "intake_answers": {
                "target_role": "Junior Python Developer",
                "why_company": "I admire your tooling-first culture.",
            },
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["validation"]["passed"] is True
    assert data["content"]["summary"]
    assert data["cover_letter"]["body"]
    assert "id" in data

    # Download the PDF
    pdf_resp = await client.get(
        f"/api/v1/tailored-resume/{data['id']}/pdf",
        headers=headers,
    )
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_feature_flag_off_returns_404(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "feature_tailored_resume_agent", False)
    token = await _get_token(client)
    resp = await client.get(
        "/api/v1/tailored-resume/quota",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
