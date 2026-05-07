"""D14c CP3 — real-LLM verification for project_evaluator.

Drives ProjectEvaluatorAgentV2.run() through call_agent() so the full
end-to-end path (4 tool reads, refusal-path routing, audit/cost tracking,
agent_actions) fires under real MiniMax. Mirrors the D14b practice_curator
CP3 harness pattern.

Four phases per CP3 spec:
  1. Rubric-bearing capstone: 'D12 CP3 RAG Capstone' (rubric-grounded path)
  2. Different rubric shape: 'D14c CP3 Phase 2: Multi-Agent Eval Harness'
  3. D-E enforcement: 'CLI AI tool' submission (rubric=NULL)
  4. D-4 enforcement: non-capstone submission

Phase 5 is calibration math from measurements. Phase 6 is quality
observation including the load-bearing rubric-grounding check.

Run inside the backend container:
    TEST_PG_DSN=postgresql+asyncpg://postgres:postgres@db:5432/platform \
    uv run python scripts/d14c_cp3_project_evaluator_real_llm.py

Cost cap: ₹3.50 cumulative across phases.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DB_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@db:5432/platform",
)
TEST_USER_EMAIL = "d12_cp3_smoke@example.com"
COST_CAP_INR = 3.50

# Submissions seeded for D14c CP3.
P1_SUBMISSION_ID = "bfca91e8-c652-40bb-b099-3c12bbf6707c"  # rubric-grounded
P2_SUBMISSION_ID = "94958ee0-91de-46fc-b269-21f158d3272e"  # different rubric
P3_SUBMISSION_ID = "e9a6b7fa-5e50-4818-ab9a-8ded04f64497"  # D-E (NULL rubric)
P4_SUBMISSION_ID = "efe255a6-b810-46c7-870e-b6dd8b81c1f0"  # D-4 (non-capstone)


# ── Setup ─────────────────────────────────────────────────────────


async def setup_user_and_entitlement(db: Any) -> uuid.UUID:
    result = await db.execute(
        sql_text("SELECT id FROM users WHERE email = :email"),
        {"email": TEST_USER_EMAIL},
    )
    row = result.fetchone()
    if row is None:
        print("ERROR: test user not found.")
        raise SystemExit(1)
    user_id = row.id
    print(f"... reusing user {user_id}")

    await db.execute(
        sql_text(
            "UPDATE course_entitlements SET expires_at = now() + interval '1 hour' "
            "WHERE user_id = :uid AND revoked_at IS NULL"
        ),
        {"uid": user_id},
    )
    await db.commit()
    print("... refreshed entitlement window")
    return user_id


async def fetch_tool_calls(
    db: Any, user_id: uuid.UUID, since: datetime
) -> list[dict[str, Any]]:
    result = await db.execute(
        sql_text(
            """
            SELECT agent_name, tool_name, status, duration_ms, created_at
            FROM agent_tool_calls
            WHERE user_id = :uid AND created_at >= :since
            ORDER BY created_at ASC
            """
        ),
        {"uid": user_id, "since": since},
    )
    return [
        {
            "agent_name": row.agent_name,
            "tool_name": row.tool_name,
            "status": row.status,
            "duration_ms": row.duration_ms,
        }
        for row in result.fetchall()
    ]


async def fetch_agent_actions(
    db: Any, user_id: uuid.UUID, since: datetime
) -> list[dict[str, Any]]:
    result = await db.execute(
        sql_text(
            """
            SELECT agent_name, status, cost_inr, tokens_used, duration_ms, output_data
            FROM agent_actions
            WHERE student_id = :uid AND created_at >= :since
            ORDER BY created_at ASC
            """
        ),
        {"uid": user_id, "since": since},
    )
    return [
        {
            "agent_name": row.agent_name,
            "status": row.status,
            "cost_inr": float(row.cost_inr) if row.cost_inr is not None else 0.0,
            "tokens_used": row.tokens_used,
            "duration_ms": row.duration_ms,
            "model": (
                row.output_data.get("llm", {}).get("model")
                if isinstance(row.output_data, dict)
                else None
            ),
        }
        for row in result.fetchall()
    ]


async def fetch_evaluations(
    db: Any, user_id: uuid.UUID, since: datetime
) -> list[dict[str, Any]]:
    """Critic evaluation rows. uses_self_eval=False on project_evaluator
    means we expect this list to be empty per phase."""
    result = await db.execute(
        sql_text(
            """
            SELECT agent_name, attempt_number, total_score, passed
            FROM agent_evaluations
            WHERE user_id = :uid AND created_at >= :since
            ORDER BY created_at ASC
            """
        ),
        {"uid": user_id, "since": since},
    )
    return [
        {
            "agent": row.agent_name,
            "attempt": row.attempt_number,
            "score": float(row.total_score) if row.total_score is not None else None,
            "passed": row.passed,
        }
        for row in result.fetchall()
    ]


# ── Phase runner ──────────────────────────────────────────────────


async def run_phase(
    *,
    label: str,
    user_id: uuid.UUID,
    db_factory: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from app.agents.agentic_base import CallChain
    from app.agents.primitives.communication import call_agent

    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print(f"\nInput payload: {json.dumps(payload, indent=2)}")

    async with db_factory() as session:
        chain = CallChain.start_root(caller="d14c_cp3", user_id=user_id)
        since = datetime.now(UTC) - timedelta(seconds=2)
        start = time.monotonic()
        try:
            result = await call_agent(
                "project_evaluator",
                payload=payload,
                session=session,
                chain=chain,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            print(f"\n!! call_agent raised after {elapsed:.2f}s: "
                  f"{type(exc).__name__}: {exc}")
            return {"error": str(exc), "elapsed": elapsed}
        elapsed = time.monotonic() - start
        await session.commit()

    print(f"\nresult.status:    {result.status}")
    print(f"elapsed:          {elapsed:.2f}s")

    out = result.output if isinstance(result.output, dict) else {}
    print(f"\noutput keys:      {list(out.keys())}")

    print(f"\n  rubric_available:        {out.get('rubric_available')!r}")
    print(f"  overall_score:           {out.get('overall_score')!r}")
    print(f"  dimension_scores:        {len(out.get('dimension_scores', []))} items")
    for i, ds in enumerate(out.get("dimension_scores", [])[:8]):
        print(f"    [{i}] dimension_name={ds.get('dimension_name')!r}")
        print(f"        rubric_criterion={ds.get('rubric_criterion', '')[:120]!r}")
        print(f"        score={ds.get('score')!r}")
        print(f"        evidence={ds.get('evidence', '')[:120]!r}")

    nf = out.get("narrative_feedback", "") or ""
    print(f"\n  narrative_feedback ({len(nf)} chars):")
    print(f"    {nf[:600]!r}")

    draft = out.get("portfolio_entry_draft") or {}
    print(f"\n  portfolio_entry_draft:")
    print(f"    title:                 {draft.get('title')!r}")
    print(f"    summary (first 200):   {(draft.get('summary', '') or '')[:200]!r}")
    print(f"    key_strengths:         {draft.get('key_strengths')}")
    print(f"    artifacts_referenced:  {draft.get('artifacts_referenced')}")

    print(f"\n  handoff_request:         {out.get('handoff_request')}")
    print(f"\n  answer (first 200):      {(out.get('answer') or '')[:200]!r}")

    # Telemetry.
    async with db_factory() as db:
        tool_calls = await fetch_tool_calls(db, user_id, since)
        actions = await fetch_agent_actions(db, user_id, since)
        evals = await fetch_evaluations(db, user_id, since)

    print(f"\nagent_tool_calls in window ({len(tool_calls)}):")
    for tc in tool_calls:
        print(
            f"  {tc['agent_name']!r}.{tc['tool_name']!r}  status={tc['status']}  "
            f"{tc['duration_ms']}ms"
        )

    print(f"\nagent_actions in window ({len(actions)}):")
    cost = 0.0
    for a in actions:
        c = a["cost_inr"]
        cost += c
        print(
            f"  {a['agent_name']!r}  status={a['status']}  cost=₹{c:.4f}  "
            f"tokens={a['tokens_used']}  duration={a['duration_ms']}ms  "
            f"model={a['model']!r}"
        )

    print(f"\nagent_evaluations ({len(evals)}) (expected 0; uses_self_eval=False):")
    for ev in evals:
        print(f"  {ev}")

    return {
        "elapsed": elapsed,
        "result": result,
        "output": out,
        "tool_calls": tool_calls,
        "actions": actions,
        "evals": evals,
        "cost": cost,
    }


# ── Verification helpers ──────────────────────────────────────────


def verify_basic_invariants(*, label: str, phase: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    out = phase["output"]

    if not out:
        findings.append(
            f"{label}: output is empty "
            f"(status={phase.get('result').status if phase.get('result') else 'unknown'})"
        )
        return findings

    # Schema invariants — handoff_request shape check (Bug 21 regression).
    hr = out.get("handoff_request")
    if hr is not None and not isinstance(hr.get("suggested_context"), dict):
        findings.append(
            f"{label}: handoff_request.suggested_context is not a dict "
            f"(Bug 21 regression — got {type(hr.get('suggested_context')).__name__})"
        )

    # narrative_feedback non-empty
    if not (out.get("narrative_feedback") or "").strip():
        findings.append(f"{label}: narrative_feedback is empty")

    # portfolio_entry_draft must be present
    if not out.get("portfolio_entry_draft"):
        findings.append(f"{label}: portfolio_entry_draft missing")

    # Critic should NOT fire (uses_self_eval=False).
    if phase["evals"]:
        findings.append(
            f"{label}: Critic fired unexpectedly "
            f"({len(phase['evals'])} eval rows; uses_self_eval=False)"
        )

    return findings


def verify_rubric_grounded(
    *, label: str, phase: dict[str, Any], expected_rubric_keys: set[str]
) -> list[str]:
    """Phase 1/2 rubric-grounded path verification (load-bearing D-E)."""
    findings: list[str] = []
    out = phase["output"]

    if not out:
        return findings

    if not out.get("rubric_available"):
        findings.append(
            f"{label}: rubric_available=False on rubric-grounded phase "
            "(D-E enforcement gap)"
        )

    dim_scores = out.get("dimension_scores", [])
    if not dim_scores:
        findings.append(
            f"{label}: dimension_scores empty on rubric-grounded phase "
            "(load-bearing D-E violation)"
        )

    # Load-bearing rubric-grounding check: dimension_names should
    # correspond to rubric keys. Allow paraphrasing — match if any
    # rubric key word appears in the dimension_name (case-insensitive).
    invented: list[str] = []
    for ds in dim_scores:
        dn = (ds.get("dimension_name") or "").lower().strip()
        if not any(
            any(token in dn for token in key.lower().replace("_", " ").split())
            for key in expected_rubric_keys
        ):
            invented.append(ds.get("dimension_name") or "<empty>")
    if invented:
        findings.append(
            f"{label}: dimension_name(s) appear invented (no overlap with "
            f"rubric keys): {invented} vs rubric keys {sorted(expected_rubric_keys)}"
        )

    # handoff_request should be None on rubric-grounded path.
    if out.get("handoff_request") is not None:
        findings.append(
            f"{label}: handoff_request populated on rubric-grounded path "
            "(should be None — orchestration owns portfolio_builder dispatch)"
        )

    return findings


def verify_de_refusal(*, label: str, phase: dict[str, Any]) -> list[str]:
    """Phase 3 D-E refusal path verification (load-bearing)."""
    findings: list[str] = []
    out = phase["output"]

    if not out:
        return findings

    if out.get("rubric_available") is not False:
        findings.append(
            f"{label}: rubric_available={out.get('rubric_available')!r} "
            "on D-E path (must be False)"
        )

    if out.get("dimension_scores"):
        findings.append(
            f"{label}: dimension_scores populated on D-E refusal path "
            f"({len(out['dimension_scores'])} items — D-E violation)"
        )

    if out.get("overall_score") != 0.0:
        findings.append(
            f"{label}: overall_score={out.get('overall_score')!r} "
            "on D-E path (must be 0.0)"
        )

    nf = (out.get("narrative_feedback") or "").lower()
    if "rubric" not in nf:
        findings.append(
            f"{label}: narrative_feedback does not mention 'rubric' on D-E path "
            "(disclaimer missing)"
        )

    if out.get("handoff_request") is not None:
        findings.append(
            f"{label}: handoff_request populated on D-E refusal "
            "(must be None — only D-4 refusal handoffs)"
        )

    draft = out.get("portfolio_entry_draft") or {}
    title = (draft.get("title") or "").lower()
    if "pending" not in title and "unavailable" not in title:
        findings.append(
            f"{label}: portfolio_entry_draft.title={draft.get('title')!r} "
            "doesn't reflect refusal state"
        )

    return findings


def verify_d4_refusal(*, label: str, phase: dict[str, Any]) -> list[str]:
    """Phase 4 D-4 refusal path verification (load-bearing)."""
    findings: list[str] = []
    out = phase["output"]

    if not out:
        return findings

    if out.get("rubric_available") is not False:
        findings.append(
            f"{label}: rubric_available={out.get('rubric_available')!r} "
            "on D-4 path (must be False)"
        )

    if out.get("dimension_scores"):
        findings.append(
            f"{label}: dimension_scores populated on D-4 refusal "
            "(must be empty)"
        )

    nf = (out.get("narrative_feedback") or "").lower()
    if "capstone" not in nf:
        findings.append(
            f"{label}: narrative_feedback doesn't mention 'capstone' on D-4 path"
        )

    hr = out.get("handoff_request")
    if hr is None:
        findings.append(
            f"{label}: handoff_request is None on D-4 path "
            "(should be senior_engineer per D-4 single legitimate handoff)"
        )
    else:
        if hr.get("target_agent") != "senior_engineer":
            findings.append(
                f"{label}: D-4 handoff target={hr.get('target_agent')!r}, "
                "expected 'senior_engineer'"
            )
        if not isinstance(hr.get("suggested_context"), dict):
            findings.append(
                f"{label}: D-4 handoff suggested_context not a dict "
                "(Bug 21 regression)"
            )

    return findings


# ── Main ──────────────────────────────────────────────────────────


async def main() -> int:
    print("=" * 70)
    print("D14c CP3 — project_evaluator real-LLM verification")
    print("=" * 70)

    # Pattern 16: BOTH loaders.
    from app.agents._agentic_loader import load_agentic_agents
    from app.agents.primitives.tools import ensure_tools_loaded

    load_agentic_agents()
    ensure_tools_loaded()

    engine = create_async_engine(DB_DSN, future=True)
    db_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with db_factory() as db:
        user_id = await setup_user_and_entitlement(db)

    cumulative_cost = 0.0
    findings: list[str] = []
    phases_data: list[dict[str, Any]] = []

    # ── Phase 1 ──────────────────────────────────────────────────
    p1 = await run_phase(
        label="PHASE 1 — Rubric-bearing capstone (RAG)",
        user_id=user_id,
        db_factory=db_factory,
        payload={
            "project_submission_id": P1_SUBMISSION_ID,
            "specific_concerns": ["architecture quality", "evidence of learning"],
            "user_message": "Please evaluate this capstone submission against the rubric.",
        },
    )
    if "error" in p1:
        return _summarise(findings + [f"P1 errored: {p1['error']}"], cumulative_cost, phases_data)
    cumulative_cost += p1["cost"]
    phases_data.append({"label": "P1", **p1})

    findings.extend(verify_basic_invariants(label="P1", phase=p1))
    findings.extend(
        verify_rubric_grounded(
            label="P1",
            phase=p1,
            expected_rubric_keys={
                "architecture", "completeness",
                "evidence_of_learning", "demo_quality",
            },
        )
    )

    if p1["elapsed"] > 90.0:
        findings.append(f"P1: elapsed {p1['elapsed']:.2f}s exceeds 90s budget (D-D)")

    if cumulative_cost > COST_CAP_INR:
        return _summarise(findings + ["cost cap hit after P1"], cumulative_cost, phases_data)

    # ── Phase 2 ──────────────────────────────────────────────────
    p2 = await run_phase(
        label="PHASE 2 — Different rubric shape (Eval Harness)",
        user_id=user_id,
        db_factory=db_factory,
        payload={
            "project_submission_id": P2_SUBMISSION_ID,
            "user_message": "Evaluate my eval harness submission.",
        },
    )
    if "error" in p2:
        return _summarise(findings + [f"P2 errored: {p2['error']}"], cumulative_cost, phases_data)
    cumulative_cost += p2["cost"]
    phases_data.append({"label": "P2", **p2})

    findings.extend(verify_basic_invariants(label="P2", phase=p2))
    findings.extend(
        verify_rubric_grounded(
            label="P2",
            phase=p2,
            expected_rubric_keys={
                "test_design", "scoring_rigor",
                "reproducibility", "result_clarity",
            },
        )
    )

    # Differentiation check: P2 should NOT pattern-match to P1's rubric.
    p1_dims = {(ds.get("dimension_name") or "").lower() for ds in p1["output"].get("dimension_scores", [])}
    p2_dims = {(ds.get("dimension_name") or "").lower() for ds in p2["output"].get("dimension_scores", [])}
    if p1_dims and p2_dims and p1_dims == p2_dims:
        findings.append(
            "P1 and P2 produced identical dimension_names — agent may be "
            "pattern-matching rather than rubric-grounding"
        )

    if p2["elapsed"] > 90.0:
        findings.append(f"P2: elapsed {p2['elapsed']:.2f}s exceeds 90s budget (D-D)")

    if cumulative_cost > COST_CAP_INR:
        return _summarise(findings + ["cost cap hit after P2"], cumulative_cost, phases_data)

    # ── Phase 3 (D-E) ────────────────────────────────────────────
    p3 = await run_phase(
        label="PHASE 3 — D-E enforcement (NULL rubric)",
        user_id=user_id,
        db_factory=db_factory,
        payload={
            "project_submission_id": P3_SUBMISSION_ID,
            "user_message": "Please evaluate this capstone.",
        },
    )
    if "error" in p3:
        return _summarise(findings + [f"P3 errored: {p3['error']}"], cumulative_cost, phases_data)
    cumulative_cost += p3["cost"]
    phases_data.append({"label": "P3", **p3})

    findings.extend(verify_basic_invariants(label="P3", phase=p3))
    findings.extend(verify_de_refusal(label="P3", phase=p3))

    if p3["elapsed"] > 90.0:
        findings.append(f"P3: elapsed {p3['elapsed']:.2f}s exceeds 90s budget (D-D)")

    if cumulative_cost > COST_CAP_INR:
        return _summarise(findings + ["cost cap hit after P3"], cumulative_cost, phases_data)

    # ── Phase 4 (D-4) ────────────────────────────────────────────
    p4 = await run_phase(
        label="PHASE 4 — D-4 enforcement (non-capstone)",
        user_id=user_id,
        db_factory=db_factory,
        payload={
            "project_submission_id": P4_SUBMISSION_ID,
            "user_message": "Evaluate my submission.",
        },
    )
    if "error" in p4:
        return _summarise(findings + [f"P4 errored: {p4['error']}"], cumulative_cost, phases_data)
    cumulative_cost += p4["cost"]
    phases_data.append({"label": "P4", **p4})

    findings.extend(verify_basic_invariants(label="P4", phase=p4))
    findings.extend(verify_d4_refusal(label="P4", phase=p4))

    if p4["elapsed"] > 90.0:
        findings.append(f"P4: elapsed {p4['elapsed']:.2f}s exceeds 90s budget (D-D)")

    # ── Phase 5: calibration ────────────────────────────────────
    print("\n" + "=" * 70)
    print("PHASE 5 — Calibration")
    print("=" * 70)
    elapseds = [p1["elapsed"], p2["elapsed"], p3["elapsed"], p4["elapsed"]]
    elapsed_max = max(elapseds)
    print(f"P1 elapsed: {p1['elapsed']:.2f}s")
    print(f"P2 elapsed: {p2['elapsed']:.2f}s")
    print(f"P3 elapsed: {p3['elapsed']:.2f}s")
    print(f"P4 elapsed: {p4['elapsed']:.2f}s")
    print(f"Max: {elapsed_max:.2f}s")
    print("Current capability budget: 90s "
          "(timeout_override_seconds=90 per D-D Pattern 18b preemptive)")
    if elapsed_max <= 60.0:
        print("Calibration: WELL UNDER BUDGET — consider reducing override to 75s.")
    elif elapsed_max <= 90.0:
        print("Calibration: WITHIN 90s budget — keep override at 90s.")
    else:
        print("Calibration: OVER BUDGET — bump override.")
        findings.append(
            f"Calibration: max elapsed {elapsed_max:.2f}s exceeds 90s override"
        )

    return _summarise(findings, cumulative_cost, phases_data)


def _summarise(
    findings: list[str], cumulative_cost: float, phases: list[dict[str, Any]]
) -> int:
    print("\n" + "=" * 70)
    print("CP3 SUMMARY")
    print("=" * 70)
    print(f"Phases run: {len(phases)}")
    print(f"Cumulative cost: ₹{cumulative_cost:.4f} / cap ₹{COST_CAP_INR:.2f}")

    # Phase 6 quality observations.
    print("\n" + "─" * 50)
    print("PHASE 6 — Quality observations (Pattern 21 + D-E)")
    print("─" * 50)
    for p in phases:
        out = p.get("output") or {}
        draft = out.get("portfolio_entry_draft") or {}
        print(f"\n{p['label']}:")
        print(f"  rubric_available: {out.get('rubric_available')!r}")
        print(f"  overall_score: {out.get('overall_score')!r}")
        print(f"  dimension count: {len(out.get('dimension_scores', []))}")
        for ds in out.get("dimension_scores", []):
            print(f"    - {ds.get('dimension_name')!r} score={ds.get('score')!r}")
        print(f"  draft.title: {draft.get('title')!r}")
        print(f"  draft.key_strengths: {draft.get('key_strengths')}")
        print(f"  draft.artifacts_referenced: {draft.get('artifacts_referenced')}")
        print(f"  handoff_request: {out.get('handoff_request')}")

    if findings:
        print(f"\nFindings ({len(findings)}):")
        for f in findings:
            print(f"  - {f}")
        return 1
    print("\n✓ No findings. CP3 verification clean.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
