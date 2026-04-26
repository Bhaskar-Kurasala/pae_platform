"""JD Decoder orchestrator.

Pipeline (single round-trip from the student's perspective):

  paste JD text
    ├── normalize + hash
    ├── lookup JdAnalysis cache (hash key)
    ├── on miss:
    │     ├── parse_jd        (Haiku, already exists)
    │     ├── JDAnalyst       (Sonnet) — must-have/wishlist/filler/seniority
    │     ├── deterministic culture-signal pre-pass + merge
    │     └── persist JdAnalysis
    ├── build StudentSnapshot (cached, TTL 1h)
    ├── MatchScorer           (Sonnet)
    ├── readiness_evidence_validator — reject + retry once
    ├── persist JdMatchScore
    └── log every LLM call to agent_invocation_log
        + circuit-break at COST_CAP_INR

Standalone use is one ``decode_jd`` call. The diagnostic invokes the
same function in commit 9 to render an inline analysis when the student
mentions a JD.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_factory import estimate_cost_inr
from app.agents.readiness_sub_agents import (
    JDAnalyst,
    MatchScorer,
    SubAgentResult,
)
from app.models.agent_invocation_log import (
    SOURCE_JD_DECODE,
    STATUS_CAP_EXCEEDED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
)
from app.models.jd_decoder import JdAnalysis, JdMatchScore
from app.services.agent_invocation_logger import log_invocation
from app.services.jd_culture_signals import (
    detect_culture_signals,
    merge_culture_signals,
)
from app.services.jd_parser import parse_jd
from app.services.readiness_evidence_validator import validate_claims
from app.services.student_snapshot_service import (
    StudentSnapshot,
    build_student_snapshot,
)

log = structlog.get_logger()

# Hard ₹8 cap per decode.
COST_CAP_INR = 8.0
JD_TRUNCATE_AT = 4000


class CostCapExceededError(RuntimeError):
    """Raised when running another LLM call would exceed COST_CAP_INR."""


@dataclass
class DecodeResult:
    jd_analysis_id: uuid.UUID
    cached: bool
    analysis: dict[str, Any]
    match_score: dict[str, Any]
    cost_inr: float


def _normalize_jd_text(text: str) -> str:
    """Strip whitespace and collapse runs of blank lines so trivial
    formatting differences don't bust the cache."""
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _hash_jd(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cost ledger — local to a single decode session
# ---------------------------------------------------------------------------


@dataclass
class _CostLedger:
    db: AsyncSession
    user_id: uuid.UUID
    source_id: str
    accumulated: float = 0.0

    def remaining_budget(self) -> float:
        return max(0.0, COST_CAP_INR - self.accumulated)

    async def record(
        self,
        *,
        sub_agent: str,
        result: SubAgentResult,
    ) -> float:
        delta = estimate_cost_inr(
            model=result.model,
            input_tokens=result.tokens_in,
            output_tokens=result.tokens_out,
        )
        self.accumulated = round(self.accumulated + delta, 4)
        await log_invocation(
            self.db,
            user_id=self.user_id,
            source=SOURCE_JD_DECODE,
            source_id=self.source_id,
            sub_agent=sub_agent,
            model=result.model,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_inr=delta,
            latency_ms=result.latency_ms,
            status=STATUS_SUCCEEDED if result.succeeded else STATUS_FAILED,
            error_message=result.error,
        )
        if self.accumulated > COST_CAP_INR:
            await log_invocation(
                self.db,
                user_id=self.user_id,
                source=SOURCE_JD_DECODE,
                source_id=self.source_id,
                sub_agent=sub_agent,
                model=result.model,
                tokens_in=0,
                tokens_out=0,
                cost_inr=0.0,
                latency_ms=None,
                status=STATUS_CAP_EXCEEDED,
                error_message=(
                    f"jd_decoder cost cap exceeded: ₹{self.accumulated:.2f}"
                ),
            )
            raise CostCapExceededError(
                f"jd_decoder cost cap exceeded: ₹{self.accumulated:.2f} "
                f"> ₹{COST_CAP_INR}"
            )
        return delta


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def decode_jd(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    jd_text: str,
) -> DecodeResult:
    """Run the full decode pipeline. Cached analysis short-circuits the
    parser + analyst stages."""
    normalized = _normalize_jd_text(jd_text)
    if not normalized:
        raise ValueError("jd_text is empty after normalization")

    jd_hash = _hash_jd(normalized)
    cache_hit = await _lookup_cached_analysis(db, jd_hash=jd_hash)

    snapshot = await build_student_snapshot(db, user_id=user_id)

    # source_id for the cost log: the JdAnalysis id once we have one.
    # Use a placeholder for now and rewrite after the analysis row is
    # persisted (or, on cache hit, immediately).
    placeholder = str(uuid.uuid4())
    ledger = _CostLedger(db=db, user_id=user_id, source_id=placeholder)

    if cache_hit is not None:
        ledger.source_id = str(cache_hit.id)
        analysis_row = cache_hit
        cached = True
    else:
        analysis_row = await _decode_fresh(
            db,
            normalized=normalized,
            jd_hash=jd_hash,
            ledger=ledger,
        )
        cached = False
        ledger.source_id = str(analysis_row.id)

    match_payload = await _score_match(
        db,
        snapshot=snapshot,
        analysis_row=analysis_row,
        ledger=ledger,
        user_id=user_id,
    )

    score_row = JdMatchScore(
        user_id=user_id,
        jd_analysis_id=analysis_row.id,
        snapshot_id=snapshot.id,
        score=match_payload.get("score"),
        headline=match_payload["headline"],
        evidence=match_payload.get("evidence", []),
        next_action_intent=match_payload["next_action"]["intent"],
        next_action_route=match_payload["next_action"]["route"],
        next_action_label=match_payload["next_action"]["label"],
        model=match_payload.get("_model"),
        validation=match_payload.get("_validation"),
    )
    db.add(score_row)
    await db.commit()
    await db.refresh(score_row)

    return DecodeResult(
        jd_analysis_id=analysis_row.id,
        cached=cached,
        analysis=_analysis_payload_for_response(analysis_row),
        match_score=_match_payload_for_response(match_payload),
        cost_inr=round(ledger.accumulated, 4),
    )


async def _lookup_cached_analysis(
    db: AsyncSession, *, jd_hash: str
) -> JdAnalysis | None:
    return (
        await db.execute(
            select(JdAnalysis).where(JdAnalysis.jd_hash == jd_hash)
        )
    ).scalar_one_or_none()


async def _decode_fresh(
    db: AsyncSession,
    *,
    normalized: str,
    jd_hash: str,
    ledger: _CostLedger,
) -> JdAnalysis:
    """Parse + analyze a not-previously-seen JD. Persists the
    JdAnalysis row before returning so subsequent decodes hit the cache."""
    # 1. parse_jd (Haiku) — already cost-aware via its own retry decorator.
    parsed = await parse_jd(normalized)
    parsed_dict = parsed.to_dict()
    if parsed.input_tokens or parsed.output_tokens:
        # parse_jd doesn't go through SubAgentResult so we wrap manually.
        await log_invocation(
            ledger.db,
            user_id=ledger.user_id,
            source=SOURCE_JD_DECODE,
            source_id=ledger.source_id,
            sub_agent="jd_parser",
            model=parsed.model or "unknown",
            tokens_in=parsed.input_tokens,
            tokens_out=parsed.output_tokens,
            cost_inr=estimate_cost_inr(
                model=parsed.model or "",
                input_tokens=parsed.input_tokens,
                output_tokens=parsed.output_tokens,
            ),
            latency_ms=None,
            status=STATUS_SUCCEEDED,
        )
        ledger.accumulated = round(
            ledger.accumulated
            + estimate_cost_inr(
                model=parsed.model or "",
                input_tokens=parsed.input_tokens,
                output_tokens=parsed.output_tokens,
            ),
            4,
        )
        if ledger.accumulated > COST_CAP_INR:
            raise CostCapExceededError(
                f"jd_decoder cost cap exceeded after parser: "
                f"₹{ledger.accumulated:.2f}"
            )

    # 2. JDAnalyst (Sonnet) — adds filler / culture / seniority read.
    analyst = JDAnalyst()
    analyst_result = await analyst.run(
        jd_text=normalized, parsed_jd=parsed_dict
    )
    await ledger.record(sub_agent="jd_analyst", result=analyst_result)

    # 3. Deterministic culture-signal pre-pass merged with LLM output.
    deterministic = detect_culture_signals(normalized)
    llm_signals = analyst_result.parsed.get("culture_signals") or []
    if not isinstance(llm_signals, list):
        llm_signals = []
    merged = merge_culture_signals(deterministic, llm_signals)

    analysis_payload: dict[str, Any] = {
        "role": analyst_result.parsed.get("role")
        or parsed_dict.get("role", ""),
        "company": analyst_result.parsed.get("company")
        or parsed_dict.get("company", ""),
        "seniority_read": analyst_result.parsed.get("seniority_read", ""),
        "must_haves": _coerce_str_list(
            analyst_result.parsed.get("must_haves"), max_len=8
        )
        or parsed_dict.get("must_haves", [])[:8],
        "wishlist": _coerce_str_list(
            analyst_result.parsed.get("wishlist"), max_len=10
        )
        or parsed_dict.get("nice_to_haves", [])[:10],
        "filler_flags": _coerce_filler_flags(
            analyst_result.parsed.get("filler_flags")
        ),
        "culture_signals": merged,
        "wishlist_inflated": bool(
            analyst_result.parsed.get("wishlist_inflated", False)
        ),
    }

    row = JdAnalysis(
        jd_hash=jd_hash,
        jd_text_truncated=normalized[:JD_TRUNCATE_AT],
        parsed=parsed_dict,
        analysis=analysis_payload,
        model=analyst_result.model,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _coerce_str_list(raw: Any, *, max_len: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        if len(out) >= max_len:
            break
    return out


def _coerce_filler_flags(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        phrase = str(item.get("phrase") or "").strip()
        meaning = str(item.get("meaning") or "").strip()
        if phrase and meaning:
            out.append({"phrase": phrase[:120], "meaning": meaning[:240]})
        if len(out) >= 10:
            break
    return out


async def _score_match(
    db: AsyncSession,
    *,
    snapshot: StudentSnapshot,
    analysis_row: JdAnalysis,
    ledger: _CostLedger,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    """Run MatchScorer with one validation-driven retry."""
    scorer = MatchScorer()
    snapshot_summary = snapshot.summary_for_llm()

    last_validation: dict[str, Any] | None = None
    last_payload: dict[str, Any] | None = None
    last_model: str | None = None

    for attempt in range(2):
        result = await scorer.run(
            snapshot_summary=snapshot_summary,
            evidence_allowlist=snapshot.evidence_allowlist,
            jd_analysis=analysis_row.analysis,
        )
        await ledger.record(sub_agent="match_scorer", result=result)
        last_model = result.model
        if not result.parsed:
            continue

        # Validate every chip. Skip the LLM verifier if the cost cap
        # is uncomfortably close — leave headroom for a retry.
        skip_llm = ledger.remaining_budget() < 1.0
        validation = await validate_claims(
            result.parsed.get("evidence", []),
            evidence_allowlist=snapshot.evidence_allowlist,
            snapshot_summary=snapshot_summary,
            skip_llm_check=skip_llm,
            label="match_evidence",
        )
        last_validation = validation.to_dict()
        last_payload = result.parsed

        if validation.passed:
            break
        log.info(
            "match_scorer.validation_failed_retrying",
            attempt=attempt,
            failures=validation.violations[:3],
        )

    if last_payload is None:
        # Both attempts produced no JSON — fall back to a thin-data
        # honest verdict rather than ship something fabricated.
        return {
            "score": None,
            "headline": "Couldn't generate a faithful match score for this JD.",
            "evidence": [],
            "next_action": {
                "intent": "thin_data",
                "route": "/today",
                "label": "Build a week of activity, then come back",
            },
            "_model": last_model,
            "_validation": last_validation
            or {
                "passed": False,
                "violations": ["scorer returned no parseable JSON"],
            },
        }

    return _normalize_match_payload(
        last_payload, model=last_model, validation=last_validation
    )


def _normalize_match_payload(
    raw: dict[str, Any],
    *,
    model: str | None,
    validation: dict[str, Any] | None,
) -> dict[str, Any]:
    score_val = raw.get("score")
    if isinstance(score_val, bool):
        score_val = None
    score_val = (
        max(0, min(100, int(score_val)))
        if isinstance(score_val, (int, float))
        else None
    )

    headline = str(raw.get("headline") or "").strip()[:280] or (
        "Match scored, but the agent didn't write a headline."
    )
    raw_evidence = raw.get("evidence")
    evidence = (
        [
            {
                "text": str(c.get("text") or "")[:240],
                "evidence_id": str(c.get("evidence_id") or ""),
                "kind": (
                    c.get("kind")
                    if c.get("kind") in ("strength", "gap", "neutral")
                    else "neutral"
                ),
            }
            for c in raw_evidence
            if isinstance(c, dict)
        ]
        if isinstance(raw_evidence, list)
        else []
    )
    next_action_raw = raw.get("next_action") or {}
    if not isinstance(next_action_raw, dict):
        next_action_raw = {}
    next_action = {
        "intent": str(
            next_action_raw.get("intent") or "thin_data"
        ),
        "route": str(next_action_raw.get("route") or "/today")[:255],
        "label": str(
            next_action_raw.get("label") or "Pick the next action"
        )[:120],
    }
    return {
        "score": score_val,
        "headline": headline,
        "evidence": evidence,
        "next_action": next_action,
        "_model": model,
        "_validation": validation,
    }


def _analysis_payload_for_response(row: JdAnalysis) -> dict[str, Any]:
    return {
        "role": row.analysis.get("role") or row.parsed.get("role", ""),
        "company": row.analysis.get("company")
        or row.parsed.get("company", "")
        or None,
        "seniority_read": row.analysis.get("seniority_read", ""),
        "must_haves": row.analysis.get("must_haves", []),
        "wishlist": row.analysis.get("wishlist", []),
        "filler_flags": row.analysis.get("filler_flags", []),
        "culture_signals": row.analysis.get("culture_signals", []),
        "wishlist_inflated": bool(row.analysis.get("wishlist_inflated", False)),
    }


def _match_payload_for_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip the underscore-prefixed audit fields before returning to the
    HTTP layer. Validation + model are persisted on the row already."""
    return {
        k: v
        for k, v in payload.items()
        if not k.startswith("_")
    }


__all__ = [
    "COST_CAP_INR",
    "CostCapExceededError",
    "DecodeResult",
    "decode_jd",
]
