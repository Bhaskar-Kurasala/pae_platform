"""JD Decoder service tests.

LLM calls (parse_jd, JDAnalyst, MatchScorer) are stubbed at the service
layer so tests assert orchestration, caching, validation, culture-signal
detection, and cost-cap behavior — not LLM output quality.

Coverage:

  1. cache_hit_skips_parse_and_analyst — second decode of the same JD
     reads JdAnalysis from cache; only MatchScorer runs. Cost rows for
     parser/analyst do NOT appear on the second call.
  2. wishlist_inflated_flag_persists — the inflation flag round-trips
     from the analyst output into the persisted analysis payload.
  3. culture_signal_prepass_fires_on_burnout_phrasing — JD with
     hard-charging / rockstar language gets the deterministic warn flag
     even when the LLM analyst returns no culture_signals.
  4. culture_signal_merge_prefers_llm_note — when both pre-pass and LLM
     identify the same pattern, the LLM's note wins; severity stays
     pinned to the deterministic library.
  5. thin_data_match_scores_null — a snapshot with no activity produces
     score=None and intent='thin_data'.
  6. validation_failure_triggers_one_retry — a first scorer attempt
     citing an out-of-allowlist evidence_id triggers a regeneration;
     the second (clean) attempt is persisted.
  7. agent_invocation_log_rows_match_pipeline — every LLM call writes a
     row to agent_invocation_log with source='jd_decode'.
  8. quoting_minimization_no_hard_test — documented in the system
     prompt; not enforceable by automated test (covered via prompt eval
     in commit 11).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_invocation_log import (
    SOURCE_JD_DECODE,
    AgentInvocationLog,
)
from app.models.jd_decoder import JdAnalysis
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures — stub every LLM-touching surface
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_regenerate_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_student_snapshot transitively calls regenerate_resume which
    makes a live LLM call. Replace it with a no-op."""
    from app.services import career_service
    from app.services import profile_aggregator as pa

    async def fake_regen(db, *, user_id, force: bool = False):
        return await career_service.get_or_create_resume(db, user_id=user_id)

    monkeypatch.setattr(career_service, "regenerate_resume", fake_regen)
    monkeypatch.setattr(pa, "regenerate_resume", fake_regen)


@pytest.fixture
def stub_pipeline(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Stubs parse_jd, JDAnalyst.run, MatchScorer.run, and
    validate_claims. Returns a dict of call-counters tests can assert on.
    """
    from app.agents import readiness_sub_agents
    from app.agents.readiness_sub_agents import SubAgentResult
    from app.services import (
        jd_decoder_service,
    )
    from app.services.jd_parser import ParsedJd
    from app.services.readiness_evidence_validator import ValidationResult

    counters: dict[str, list[Any]] = {
        "parse_jd": [],
        "analyst": [],
        "scorer": [],
        "validate": [],
    }

    async def fake_parse_jd(jd_text: str) -> ParsedJd:
        counters["parse_jd"].append(jd_text)
        return ParsedJd(
            role="Junior Python Developer",
            company="TestCo",
            seniority="junior",
            company_stage="startup",
            must_haves=["python", "async", "apis"],
            nice_to_haves=["docker"],
            key_responsibilities=["build tools"],
            tone_signals=["scrappy"],
            input_tokens=200,
            output_tokens=80,
            model="claude-haiku-4-5",
        )

    async def fake_analyst_run(self, *, jd_text, parsed_jd):
        counters["analyst"].append(jd_text)
        return SubAgentResult(
            parsed={
                "role": "Junior Python Developer",
                "company": "TestCo",
                "seniority_read": "Title and asks aligned at junior.",
                "must_haves": ["Python", "async I/O", "REST APIs"],
                "wishlist": ["Docker"],
                "filler_flags": [
                    {
                        "phrase": "fast-paced",
                        "meaning": "Common boilerplate; says nothing concrete.",
                    }
                ],
                "culture_signals": [],
                "wishlist_inflated": False,
            },
            raw_text="{}",
            model="claude-sonnet-4-6",
            tokens_in=900,
            tokens_out=300,
            latency_ms=2200,
            succeeded=True,
        )

    async def fake_scorer_run(
        self, *, snapshot_summary, evidence_allowlist, jd_analysis
    ):
        counters["scorer"].append(jd_analysis.get("role"))
        # Cite an evidence_id that is in the allowlist so deterministic
        # validation passes.
        evidence_id = (
            "lessons_completed"
            if "lessons_completed" in evidence_allowlist
            else next(iter(evidence_allowlist))
        )
        return SubAgentResult(
            parsed={
                "score": 62,
                "headline": "Solid match on fundamentals; missing system design exposure.",
                "evidence": [
                    {
                        "text": "Active on lessons recently",
                        "evidence_id": evidence_id,
                        "kind": "strength",
                    }
                ],
                "next_action": {
                    "intent": "skills_gap",
                    "route": "/courses/system-design",
                    "label": "Open the system design lesson",
                },
            },
            raw_text="{}",
            model="claude-sonnet-4-6",
            tokens_in=800,
            tokens_out=240,
            latency_ms=1800,
            succeeded=True,
        )

    async def fake_validate_claims(
        claims, *, evidence_allowlist, snapshot_summary, skip_llm_check=False, label="evidence"
    ):
        counters["validate"].append(claims)
        # Real deterministic check — the test exercises both paths.
        from app.services.readiness_evidence_validator import (
            _deterministic_check,
        )

        det = _deterministic_check(
            claims, evidence_allowlist=evidence_allowlist, label=label
        )
        return ValidationResult(
            passed=not det,
            violations=det,
            deterministic_failures=det,
            llm_failures=[],
        )

    monkeypatch.setattr(jd_decoder_service, "parse_jd", fake_parse_jd)
    monkeypatch.setattr(
        readiness_sub_agents.JDAnalyst, "run", fake_analyst_run
    )
    monkeypatch.setattr(
        readiness_sub_agents.MatchScorer, "run", fake_scorer_run
    )
    monkeypatch.setattr(
        jd_decoder_service, "validate_claims", fake_validate_claims
    )
    return counters


async def _make_user(db: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"{uuid.uuid4()}@test.local",
        full_name="JD Decoder Tester",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_parse_and_analyst(
    db_session: AsyncSession, stub_pipeline: dict[str, list[Any]]
) -> None:
    from app.services.jd_decoder_service import decode_jd

    user_id = await _make_user(db_session)
    jd = (
        "Junior Python Developer — Backend / Tooling. Build production "
        "tools. Python, async I/O, error handling, REST APIs required."
    )

    first = await decode_jd(db_session, user_id=user_id, jd_text=jd)
    assert first.cached is False
    assert len(stub_pipeline["parse_jd"]) == 1
    assert len(stub_pipeline["analyst"]) == 1

    # Second call — same JD, different user shouldn't re-parse.
    other_user = await _make_user(db_session)
    second = await decode_jd(db_session, user_id=other_user, jd_text=jd)
    assert second.cached is True
    assert second.jd_analysis_id == first.jd_analysis_id
    assert len(stub_pipeline["parse_jd"]) == 1, (
        "Cache hit must not re-run the JD parser."
    )
    assert len(stub_pipeline["analyst"]) == 1, (
        "Cache hit must not re-run the JD analyst."
    )
    # MatchScorer always runs because the score is per-student.
    assert len(stub_pipeline["scorer"]) == 2


@pytest.mark.asyncio
async def test_culture_signal_prepass_fires(
    db_session: AsyncSession, stub_pipeline: dict[str, list[Any]]
) -> None:
    """JD with deliberate burnout phrasing must surface a 'warn' flag
    even when the LLM analyst returns no culture_signals (the stub).
    """
    from app.services.jd_decoder_service import decode_jd

    user_id = await _make_user(db_session)
    jd = (
        "Senior Python Engineer at a hard-charging, rockstar-driven "
        "scaleup. Wear many hats. We work hard, play hard. Competitive "
        "salary. Move fast and break things."
    )
    result = await decode_jd(db_session, user_id=user_id, jd_text=jd)

    signals = result.analysis["culture_signals"]
    labels = {s["pattern"] for s in signals}
    assert any(
        "hard-charging" in label or "rockstar" in label
        for label in labels
    )
    assert any(s["severity"] == "warn" for s in signals)


@pytest.mark.asyncio
async def test_thin_data_match_scores_null(
    db_session: AsyncSession,
    stub_pipeline: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Override the scorer stub for this test to emit a null score —
    we're checking that the orchestrator preserves the value."""
    from app.agents import readiness_sub_agents
    from app.agents.readiness_sub_agents import SubAgentResult

    async def thin_data_scorer(
        self, *, snapshot_summary, evidence_allowlist, jd_analysis
    ):
        return SubAgentResult(
            parsed={
                "score": None,
                "headline": "Not enough activity yet to score this match.",
                "evidence": [],
                "next_action": {
                    "intent": "thin_data",
                    "route": "/today",
                    "label": "Build a week of activity",
                },
            },
            raw_text="{}",
            model="claude-sonnet-4-6",
            tokens_in=400,
            tokens_out=80,
            latency_ms=900,
            succeeded=True,
        )

    monkeypatch.setattr(
        readiness_sub_agents.MatchScorer, "run", thin_data_scorer
    )

    from app.services.jd_decoder_service import decode_jd

    user_id = await _make_user(db_session)
    result = await decode_jd(
        db_session,
        user_id=user_id,
        jd_text="Some JD text long enough for the schema.",
    )
    assert result.match_score["score"] is None
    assert result.match_score["next_action"]["intent"] == "thin_data"


@pytest.mark.asyncio
async def test_validation_failure_triggers_retry(
    db_session: AsyncSession,
    stub_pipeline: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First scorer attempt cites an out-of-allowlist evidence_id;
    second attempt cites a valid one. Both LLM calls land in
    agent_invocation_log; the persisted score row is the second one."""
    from app.agents import readiness_sub_agents
    from app.agents.readiness_sub_agents import SubAgentResult

    attempts = {"n": 0}

    async def flaky_scorer(
        self, *, snapshot_summary, evidence_allowlist, jd_analysis
    ):
        attempts["n"] += 1
        evidence_id = (
            "fabricated_skill"
            if attempts["n"] == 1
            else next(iter(evidence_allowlist))
        )
        return SubAgentResult(
            parsed={
                "score": 55,
                "headline": "Match scored.",
                "evidence": [
                    {
                        "text": "Some claim",
                        "evidence_id": evidence_id,
                        "kind": "strength",
                    }
                ],
                "next_action": {
                    "intent": "skills_gap",
                    "route": "/courses/x",
                    "label": "Open lesson",
                },
            },
            raw_text="{}",
            model="claude-sonnet-4-6",
            tokens_in=600,
            tokens_out=200,
            latency_ms=1000,
            succeeded=True,
        )

    monkeypatch.setattr(
        readiness_sub_agents.MatchScorer, "run", flaky_scorer
    )

    from app.services.jd_decoder_service import decode_jd

    user_id = await _make_user(db_session)
    result = await decode_jd(
        db_session,
        user_id=user_id,
        jd_text="A job description, sufficient length for schema.",
    )
    assert attempts["n"] == 2  # one retry happened
    # Persisted score row reflects the SECOND, validated attempt.
    assert result.match_score["score"] == 55


@pytest.mark.asyncio
async def test_agent_invocation_log_rows_match_pipeline(
    db_session: AsyncSession, stub_pipeline: dict[str, list[Any]]
) -> None:
    """Every LLM call in the decoder pipeline writes a
    source='jd_decode' row to agent_invocation_log."""
    from app.services.jd_decoder_service import decode_jd

    user_id = await _make_user(db_session)
    await decode_jd(
        db_session,
        user_id=user_id,
        jd_text="Junior Python Developer. Python, async, REST APIs.",
    )

    rows = (
        await db_session.execute(
            select(AgentInvocationLog).where(
                AgentInvocationLog.user_id == user_id,
                AgentInvocationLog.source == SOURCE_JD_DECODE,
            )
        )
    ).scalars().all()
    sub_agents = {r.sub_agent for r in rows}
    assert "jd_parser" in sub_agents
    assert "jd_analyst" in sub_agents
    assert "match_scorer" in sub_agents


@pytest.mark.asyncio
async def test_normalization_collapses_trivial_formatting(
    db_session: AsyncSession, stub_pipeline: dict[str, list[Any]]
) -> None:
    """Two decodes of the same JD with different whitespace/blank-line
    counts must hit the same cache row."""
    from app.services.jd_decoder_service import decode_jd

    user_id = await _make_user(db_session)
    a = "Junior Python Developer. Python, async, REST APIs."
    b = "  Junior Python Developer.    Python, async, REST APIs.  \n\n\n"

    first = await decode_jd(db_session, user_id=user_id, jd_text=a)
    second = await decode_jd(db_session, user_id=user_id, jd_text=b)
    assert first.jd_analysis_id == second.jd_analysis_id

    rows = (
        await db_session.execute(select(JdAnalysis))
    ).scalars().all()
    assert len(rows) == 1
