"""Evidence validator tests.

Coverage:

  1. clean_claims_pass — valid evidence_ids in allowlist, no LLM check
     run, validator passes.
  2. unknown_evidence_id_fails — claim cites a signal not in allowlist,
     validator rejects with a deterministic failure naming the offending
     evidence_id.
  3. missing_evidence_id_fails — a claim missing evidence_id is
     rejected.
  4. case_insensitive_allowlist — allowlist matching is case-insensitive
     so prompts that accidentally upper-case an id still work.
  5. skip_llm_check_short_circuits — when the cost cap has been hit, the
     LLM verifier is skipped and only the deterministic pass runs.
  6. malformed_claims_list — non-list input is rejected with a clear
     failure message rather than crashing.
"""

from __future__ import annotations

import pytest

from app.services.readiness_evidence_validator import (
    ValidationResult,
    validate_claims,
)


@pytest.mark.asyncio
async def test_clean_claims_pass() -> None:
    claims = [
        {
            "text": "Shipped 4 capstones in the last 60 days",
            "evidence_id": "capstones_shipped",
            "kind": "strength",
        },
        {
            "text": "Mock interview score up 31% over last 3 sessions",
            "evidence_id": "recent_mock_scores",
            "kind": "strength",
        },
    ]
    result = await validate_claims(
        claims,
        evidence_allowlist={"capstones_shipped", "recent_mock_scores"},
        snapshot_summary={"capstones_shipped": 4},
        skip_llm_check=True,
    )
    assert isinstance(result, ValidationResult)
    assert result.passed is True
    assert result.violations == []


@pytest.mark.asyncio
async def test_unknown_evidence_id_fails() -> None:
    claims = [
        {
            "text": "Has deep system design experience",
            "evidence_id": "system_design_mastery",
            "kind": "strength",
        }
    ]
    result = await validate_claims(
        claims,
        evidence_allowlist={"capstones_shipped", "lessons_completed"},
        snapshot_summary={},
        skip_llm_check=True,
    )
    assert result.passed is False
    assert len(result.deterministic_failures) == 1
    # The failure message names the offending evidence_id.
    assert "system_design_mastery" in result.deterministic_failures[0]


@pytest.mark.asyncio
async def test_missing_evidence_id_fails() -> None:
    claims = [
        {"text": "User has been doing things", "kind": "neutral"}
    ]
    result = await validate_claims(
        claims,
        evidence_allowlist={"capstones_shipped"},
        snapshot_summary={},
        skip_llm_check=True,
    )
    assert result.passed is False
    assert any(
        "missing evidence_id" in f
        for f in result.deterministic_failures
    )


@pytest.mark.asyncio
async def test_case_insensitive_allowlist() -> None:
    """LLM might emit Title-Case ids; allowlist match is case-insensitive."""
    claims = [
        {
            "text": "User has shipped capstones",
            "evidence_id": "Capstones_Shipped",
            "kind": "strength",
        }
    ]
    result = await validate_claims(
        claims,
        evidence_allowlist={"capstones_shipped"},
        snapshot_summary={},
        skip_llm_check=True,
    )
    assert result.passed is True


@pytest.mark.asyncio
async def test_skip_llm_check_short_circuits() -> None:
    """When the cost cap has been hit the orchestrator passes
    skip_llm_check=True; deterministic-only pass must still produce a
    coherent ValidationResult."""
    claims = [
        {
            "text": "Has Python experience",
            "evidence_id": "python",
            "kind": "strength",
        }
    ]
    result = await validate_claims(
        claims,
        evidence_allowlist={"python"},
        snapshot_summary={"python": 0.7},
        skip_llm_check=True,
    )
    assert result.passed is True
    assert result.llm_failures == []


@pytest.mark.asyncio
async def test_malformed_claims_list_fails_cleanly() -> None:
    result = await validate_claims(
        "not a list at all",  # type: ignore[arg-type]
        evidence_allowlist={"python"},
        snapshot_summary={},
        skip_llm_check=True,
    )
    assert result.passed is False
    assert "not a list" in result.deterministic_failures[0]
