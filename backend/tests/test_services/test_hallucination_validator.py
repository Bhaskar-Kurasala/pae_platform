"""Hallucination validator tests — deterministic pass behavior + LLM stub."""

from __future__ import annotations

from typing import Any

import pytest

from app.services import hallucination_validator
from app.services.hallucination_validator import validate


def _evidence() -> dict[str, Any]:
    return {
        "skills": [{"name": "python", "confidence": 0.9}],
        "self_attested": {"non_platform_experience": [], "education": []},
    }


@pytest.mark.asyncio
async def test_passes_when_every_bullet_cites_known_evidence() -> None:
    content = {
        "summary": "Python developer.",
        "bullets": [
            {"text": "Built a CLI tool.", "evidence_id": "python", "ats_keywords": ["python"]},
        ],
    }
    result = await validate(
        content,
        evidence=_evidence(),
        evidence_allowlist={"python", "exercise_volume"},
        skip_llm_check=True,
    )
    assert result.passed is True
    assert result.violations == []


@pytest.mark.asyncio
async def test_fails_when_bullet_cites_unknown_evidence() -> None:
    content = {
        "bullets": [
            {"text": "Built a Kubernetes operator.", "evidence_id": "kubernetes", "ats_keywords": []},
        ],
    }
    result = await validate(
        content,
        evidence=_evidence(),
        evidence_allowlist={"python", "exercise_volume"},
        skip_llm_check=True,
    )
    assert result.passed is False
    assert any("kubernetes" in v for v in result.deterministic_failures)


@pytest.mark.asyncio
async def test_fails_when_bullet_missing_evidence_id() -> None:
    content = {
        "bullets": [
            {"text": "Did things.", "evidence_id": "", "ats_keywords": []},
        ],
    }
    result = await validate(
        content,
        evidence=_evidence(),
        evidence_allowlist={"python"},
        skip_llm_check=True,
    )
    assert result.passed is False
    assert any("missing evidence_id" in v for v in result.deterministic_failures)


@pytest.mark.asyncio
async def test_fails_when_bullets_field_not_a_list() -> None:
    content = {"bullets": "this is not a list"}
    result = await validate(
        content,
        evidence=_evidence(),
        evidence_allowlist={"python"},
        skip_llm_check=True,
    )
    assert result.passed is False
    assert "not a list" in result.deterministic_failures[0]


@pytest.mark.asyncio
async def test_evidence_id_is_compared_case_insensitively() -> None:
    content = {
        "bullets": [
            {"text": "...", "evidence_id": "PYTHON", "ats_keywords": []},
        ],
    }
    result = await validate(
        content,
        evidence=_evidence(),
        evidence_allowlist={"python"},
        skip_llm_check=True,
    )
    assert result.passed is True


@pytest.mark.asyncio
async def test_llm_check_runs_only_after_deterministic_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    async def fake_llm_check(**_: Any) -> list[str]:
        calls.append(True)
        return []

    monkeypatch.setattr(hallucination_validator, "_llm_check", fake_llm_check)

    # Deterministic pass clears → LLM pass should run
    good_content = {
        "bullets": [{"text": "...", "evidence_id": "python", "ats_keywords": []}],
    }
    await validate(
        good_content,
        evidence=_evidence(),
        evidence_allowlist={"python"},
    )
    assert calls == [True]

    # Deterministic pass fails → LLM pass should be skipped
    calls.clear()
    bad_content = {
        "bullets": [{"text": "...", "evidence_id": "java", "ats_keywords": []}],
    }
    await validate(
        bad_content,
        evidence=_evidence(),
        evidence_allowlist={"python"},
    )
    assert calls == []
