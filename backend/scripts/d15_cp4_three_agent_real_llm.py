"""D15 CP4 — practice_curator + project_evaluator + mock_interview real-LLM verification.

Four phases per the saved D15 prompt's CP4 spec:

  Phase 1 — practice_curator with curated bank available.
  Phase 2 — practice_curator generative fallback (empty bank).
  Phase 3 — project_evaluator gate-context (real capstone submission).
  Phase 4 — mock_interview gate-prep verdict (multi-turn until session_summary).

All phases run the runtime grounding cross-reference verifier from CP3
(reusable utility at tests/fixtures/runtime_grounding_verifier.py).

Pattern 16 honored at boot (load_agentic_agents + ensure_tools_loaded).

Run inside the backend container:

    docker exec -e TEST_PG_DSN=postgresql+asyncpg://postgres:postgres@db:5432/platform \
      pae_platform-backend-1 \
      uv run python scripts/d15_cp4_three_agent_real_llm.py

Cost cap: ₹3.00 cumulative across phases (D15 prompt budgets ~₹2 expected;
ceiling leaves headroom for the multi-turn Phase 4).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
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
COST_CAP_INR = 3.00


async def fetch_tool_calls(
    db: Any, user_id: Any, since: datetime
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
    db: Any, user_id: Any, since: datetime
) -> list[dict[str, Any]]:
    result = await db.execute(
        sql_text(
            """
            SELECT agent_name, status, cost_inr, tokens_used, duration_ms,
                   output_data
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


# ── Phase runner (single dispatch) ────────────────────────────────


async def run_single(
    *,
    label: str,
    agent_name: str,
    user_id: Any,
    role_slug: str | None,
    db_factory: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from app.agents.agentic_base import CallChain
    from app.agents.primitives.communication import call_agent

    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}")
    print(f"\nAgent: {agent_name}")
    print(f"User:  {user_id}")
    print(f"Payload: {json.dumps(payload, indent=2, default=str)}")

    async with db_factory() as session:
        chain = CallChain.start_root(caller="d15_cp4", user_id=user_id)
        since = datetime.now(UTC) - timedelta(seconds=2)
        start = time.monotonic()
        try:
            result = await call_agent(
                agent_name,
                payload=payload,
                session=session,
                chain=chain,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            print(
                f"\n!! call_agent raised after {elapsed:.2f}s: "
                f"{type(exc).__name__}: {exc}"
            )
            return {"error": str(exc), "elapsed": elapsed, "cost": 0.0}
        elapsed = time.monotonic() - start
        await session.commit()

    print(f"\nresult.status:    {result.status}")
    print(f"elapsed:          {elapsed:.2f}s")

    out = result.output if isinstance(result.output, dict) else {}
    print(f"\noutput keys:      {list(out.keys())}")

    answer = out.get("answer") or ""
    print(f"\n  answer:\n    {answer[:400]!r}")

    # Telemetry.
    async with db_factory() as db:
        tool_calls = await fetch_tool_calls(db, user_id, since)
        actions = await fetch_agent_actions(db, user_id, since)

    print(f"\nagent_tool_calls in window ({len(tool_calls)}):")
    for tc in tool_calls:
        print(
            f"  {tc['agent_name']!r}.{tc['tool_name']!r}  "
            f"status={tc['status']}  {tc['duration_ms']}ms"
        )

    cost = 0.0
    print(f"\nagent_actions in window ({len(actions)}):")
    for a in actions:
        c = a["cost_inr"]
        cost += c
        print(
            f"  {a['agent_name']!r}  status={a['status']}  cost=₹{c:.4f}  "
            f"tokens={a['tokens_used']}  duration={a['duration_ms']}ms  "
            f"model={a['model']!r}"
        )

    # Cross-reference grounding verifier.
    from tests.fixtures.runtime_grounding_verifier import verify_runtime_grounding

    grounding_findings: list[str] = []
    async with db_factory() as db:
        verif = await verify_runtime_grounding(
            db,
            agent_output=out,
            student_id=user_id,
            role_slug=role_slug,
        )
    print(f"\n{verif.summary()}")
    if not verif.passed:
        for f in verif.findings:
            print(
                f"  ! grounding violation: {f.extracted_name!r} "
                f"(seen in {f.where_seen}; accessible set has "
                f"{f.accessible_set_size} titles)"
            )
            grounding_findings.append(
                f"{label[:25]}: cross-role content reference "
                f"'{f.extracted_name}' not in accessible set"
            )

    return {
        "elapsed": elapsed,
        "result": result,
        "output": out,
        "tool_calls": tool_calls,
        "actions": actions,
        "cost": cost,
        "grounding": verif,
        "grounding_findings": grounding_findings,
    }


# ── Phase-specific verifiers ─────────────────────────────────────


def verify_phase1_curated_bank(phase: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    out = phase["output"]
    if not out:
        findings.append("P1: empty output")
        return findings

    exercise = out.get("exercise") or {}
    source = exercise.get("source")
    curated_id = exercise.get("curated_exercise_id")
    title = exercise.get("title", "")
    if source != "curated":
        findings.append(
            f"P1: expected exercise.source='curated' (bank available); "
            f"got {source!r}. Title: {title!r}"
        )
    if not curated_id:
        findings.append(
            "P1: exercise.curated_exercise_id missing despite source='curated' "
            "(or expected curated path)"
        )
    return findings


def verify_phase2_generative_fallback(phase: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    out = phase["output"]
    if not out:
        findings.append("P2: empty output")
        return findings

    exercise = out.get("exercise") or {}
    source = exercise.get("source")
    curated_id = exercise.get("curated_exercise_id")
    if source != "generated":
        findings.append(
            f"P2: expected exercise.source='generated' (empty bank fallback); "
            f"got {source!r}"
        )
    if curated_id:
        findings.append(
            f"P2: exercise.curated_exercise_id should be null when generative; "
            f"got {curated_id!r}"
        )
    return findings


def verify_phase3_gate_context(phase: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    out = phase["output"]
    if not out:
        findings.append("P3: empty output")
        return findings

    if not out.get("rubric_available"):
        findings.append(
            "P3: rubric_available=False; expected True (rubric is present "
            "on the python-foundations 'CLI AI tool' capstone)"
        )

    gate = out.get("transition_gate_status")
    if gate is None:
        findings.append(
            "P3: transition_gate_status missing; expected populated for "
            "non-terminal student capstone"
        )
        return findings

    if gate.get("transition_from_role") != "ml_engineer":
        findings.append(
            f"P3: transition_from_role mismatch; expected ml_engineer, "
            f"got {gate.get('transition_from_role')!r}"
        )
    if gate.get("transition_to_role") != "genai_engineer":
        findings.append(
            f"P3: transition_to_role mismatch; expected genai_engineer, "
            f"got {gate.get('transition_to_role')!r}"
        )
    threshold = gate.get("capstone_threshold_required")
    if threshold is None or abs(float(threshold) - 0.75) > 1e-6:
        findings.append(
            f"P3: capstone_threshold_required mismatch; expected 0.75, "
            f"got {threshold!r}"
        )
    achieved = gate.get("capstone_score_achieved")
    overall = out.get("overall_score")
    if achieved is None or overall is None or abs(float(achieved) - float(overall)) > 1e-6:
        findings.append(
            f"P3: capstone_score_achieved {achieved!r} != overall_score "
            f"{overall!r}"
        )
    expected_passes = (
        achieved is not None and threshold is not None
        and float(achieved) >= float(threshold)
    )
    if gate.get("passes_threshold") != expected_passes:
        findings.append(
            f"P3: passes_threshold {gate.get('passes_threshold')} "
            f"inconsistent with score/threshold ({achieved!r} >= "
            f"{threshold!r} = {expected_passes})"
        )

    nf = (out.get("narrative_feedback") or "").lower()
    # Expect narrative to reference threshold or transition.
    if (
        "0.75" not in nf
        and "genai_engineer" not in nf
        and "genai engineer" not in nf
    ):
        findings.append(
            "P3: narrative_feedback does not reference gate threshold or "
            "next role (expected mention of 0.75 or genai_engineer)"
        )
    return findings


def verify_phase4_session_verdict(phase: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    out = phase["output"]
    if not out:
        findings.append("P4: empty output")
        return findings

    if out.get("turn_kind") != "session_summary":
        findings.append(
            f"P4: turn_kind={out.get('turn_kind')!r}; expected session_summary"
        )
        return findings

    sv = out.get("session_verdict")
    if sv is None:
        findings.append(
            "P4: session_verdict missing despite gate-prep intent + "
            "session_summary turn"
        )
        return findings

    expected_dim_names = {
        "clarity_of_questioning",
        "directional_adherence",
        "complexity_adaptation",
        "technical_correctness",
    }
    dim_scores = sv.get("dimension_scores") or []
    actual_names = {d.get("name") for d in dim_scores}
    if actual_names != expected_dim_names:
        findings.append(
            f"P4: dimension_scores names mismatch. expected "
            f"{sorted(expected_dim_names)}, got {sorted(actual_names)}"
        )

    weights_sum = sum(float(d.get("weight", 0)) for d in dim_scores)
    if abs(weights_sum - 1.0) > 1e-6:
        findings.append(
            f"P4: dimension weights sum to {weights_sum:.6f}, expected 1.0"
        )

    weighted = sv.get("weighted_score")
    if weighted is None:
        findings.append("P4: weighted_score missing")
    else:
        recomputed = sum(
            float(d.get("weight", 0)) * float(d.get("score", 0))
            for d in dim_scores
        )
        if abs(float(weighted) - recomputed) > 1e-6:
            findings.append(
                f"P4: weighted_score {weighted!r} != recomputed {recomputed:.6f}"
            )

    target = sv.get("transition_target") or {}
    if target.get("from_role_slug") != "ml_engineer":
        findings.append(
            f"P4: transition_target.from_role_slug={target.get('from_role_slug')!r}; "
            f"expected ml_engineer"
        )
    if target.get("to_role_slug") != "genai_engineer":
        findings.append(
            f"P4: transition_target.to_role_slug={target.get('to_role_slug')!r}; "
            f"expected genai_engineer"
        )

    return findings


# ── Multi-turn driver for Phase 4 ─────────────────────────────────


async def run_multi_turn_session(
    *,
    label: str,
    user_id: Any,
    role_slug: str | None,
    db_factory: Any,
    initial_payload: dict[str, Any],
    max_turns: int = 6,
) -> dict[str, Any]:
    """Drive a mock_interview session until session_summary OR max_turns.

    The candidate's "answers" between turns are synthetic-but-substantive
    texts that exercise each dimension: a clarifying question (clarity),
    a focused on-topic answer (directional_adherence), an adaptation
    when constraints shift (complexity_adaptation), and concrete
    technical content (technical_correctness). The synthetic answers
    are deterministic so the verdict is reproducible.

    Returns the FINAL turn's phase dict (run_single output) plus
    accumulated cost across all turns.
    """
    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}\n")
    print(f"Multi-turn driver: up to {max_turns} turns\n")

    # The synthetic candidate replies — one per follow-up turn. The
    # FIRST turn's payload is the user's gate-prep intent message.
    candidate_replies = [
        # After question 1 — clarifying question (clarity)
        "Before I design, two clarifying questions: what's the latency "
        "budget per query, and roughly how many documents are we indexing? "
        "Both shape the retrieval architecture choice.",
        # After question 2 — focused on-topic answer with technical content
        "I'd start with hybrid retrieval: BM25 for lexical recall plus a "
        "dense embedding index (e.g., OpenAI text-embedding-3-large with "
        "1024 dims). Reciprocal rank fusion to combine. Hot path serves "
        "from in-memory FAISS HNSW for sub-100ms; warm tier on a managed "
        "vector DB. Cache embeddings of frequent queries with a 24h TTL.",
        # After question 3 (constraint added) — adaptation
        "If we suddenly need 10x scale, the FAISS in-memory tier breaks. "
        "I'd shard by document collection across multiple replicas, "
        "introduce a request-level cache (Redis with TTL), and switch the "
        "warm tier to a managed service that handles replication. Query "
        "fan-out and result merging adds ~20-40ms but absorbs the load.",
        # After question 4 — request close
        "I think that covers the core architecture. Ready for feedback "
        "and a session summary.",
        # Wrap-up reinforcement
        "Yes, please give me the session summary now.",
    ]

    cumulative_cost = 0.0
    final_phase: dict[str, Any] | None = None
    session_id: str | None = None
    payload = dict(initial_payload)
    last_turn_kind: str | None = None

    for turn_idx in range(max_turns):
        turn_label = f"{label} — Turn {turn_idx + 1}"
        phase = await run_single(
            label=turn_label,
            agent_name="mock_interview",
            user_id=user_id,
            role_slug=role_slug,
            db_factory=db_factory,
            payload=payload,
        )
        if "error" in phase:
            return {**phase, "cost": cumulative_cost, "error_at_turn": turn_idx + 1}
        cumulative_cost += phase["cost"]
        out = phase["output"] or {}
        if session_id is None:
            session_id = out.get("session_id")
        last_turn_kind = out.get("turn_kind")
        final_phase = phase

        if last_turn_kind == "session_summary":
            break
        # Build next-turn payload: same mode + session_id + the next
        # synthetic candidate reply. If we've exhausted replies before
        # session_summary, the last reply is reused (which signals
        # readiness for wrap-up).
        if turn_idx < len(candidate_replies):
            next_msg = candidate_replies[turn_idx]
        else:
            next_msg = candidate_replies[-1]
        payload = {
            "mode": initial_payload.get("mode", "system_design"),
            "session_id": session_id,
            "user_message": next_msg,
        }

    if final_phase is None:
        return {"error": "no turns ran", "cost": cumulative_cost, "elapsed": 0.0}

    final_phase["cost"] = cumulative_cost
    return final_phase


# ── Main ──────────────────────────────────────────────────────────


def _summarise(
    findings: list[str], cost: float, phases_data: list[dict[str, Any]]
) -> int:
    print("\n" + "=" * 72)
    print("D15 CP4 SUMMARY")
    print("=" * 72)
    print(f"\nCumulative cost: ₹{cost:.4f}  (cap: ₹{COST_CAP_INR:.2f})")
    print(f"\nPhases run: {len(phases_data)}")
    for p in phases_data:
        print(
            f"  {p.get('label', '?')}: elapsed={p.get('elapsed', 0):.2f}s  "
            f"cost=₹{p.get('cost', 0):.4f}"
        )
    print(f"\nFindings ({len(findings)}):")
    if not findings:
        print("  (none — all verification rules passed)")
    else:
        for f in findings:
            print(f"  • {f}")
    return 0 if not findings else 1


async def main() -> int:
    print("=" * 72)
    print("D15 CP4 — practice_curator + project_evaluator + mock_interview")
    print("=" * 72)

    from app.agents._agentic_loader import load_agentic_agents
    from app.agents.primitives.tools import ensure_tools_loaded

    load_agentic_agents()
    ensure_tools_loaded()

    from tests.fixtures.role_state_fixtures import (  # type: ignore
        seed_data_analyst_with_entitlement,  # P2: 0 curated problems for data_analyst on dev DB
        seed_ml_engineer_for_gate_prep,
        seed_ml_engineer_with_capstone_submission,
        seed_python_developer_with_curated_bank,
    )

    engine = create_async_engine(DB_DSN, future=True)
    db_factory = async_sessionmaker(engine, expire_on_commit=False)

    cumulative_cost = 0.0
    findings: list[str] = []
    phases_data: list[dict[str, Any]] = []

    # Seed all four students up-front; commit so the agents see them.
    async with db_factory() as db:
        py_dev_bank = await seed_python_developer_with_curated_bank(db)
        # P2 student — data_analyst with empty curated bank for that role.
        # Reuses the CP3 fixture; data-analyst course has 0 exercises so
        # accessible_curated_problems is empty.
        da_empty = await seed_data_analyst_with_entitlement(db)
        # P3: ml_engineer who submitted the rubric-bearing genai_engineer-
        # tagged D12 CP3 RAG Capstone. Aligns student role with capstone
        # course-tag so transition_gate_status can populate
        # cleanly (ml_engineer→genai_engineer, threshold 0.75).
        ml_cap, submission_id = (
            await seed_ml_engineer_with_capstone_submission(db, capstone_score=82)
        )
        ml = await seed_ml_engineer_for_gate_prep(db)
        await db.commit()
    print(f"\nSeeded:")
    print(f"  P1 python_developer (with bank)            = {py_dev_bank.user_id}")
    print(f"  P2 data_analyst (empty bank)                = {da_empty.user_id}")
    print(f"  P3 ml_engineer (with rubric-bearing capstone)= {ml_cap.user_id}")
    print(f"     submission_id                            = {submission_id}")
    print(f"  P4 ml_engineer (gate-prep)                  = {ml.user_id}")

    # ── Phase 1: practice_curator with curated bank ───────────────
    p1 = await run_single(
        label="PHASE 1 — practice_curator with curated bank (python_developer)",
        agent_name="practice_curator",
        user_id=py_dev_bank.user_id,
        role_slug=py_dev_bank.current_role_slug,
        db_factory=db_factory,
        payload={
            "user_message": "Give me a python practice exercise.",
            "exercise_type": "coding",
            "difficulty_level": "easy",
        },
    )
    if "error" in p1:
        return _summarise(
            findings + [f"P1 errored: {p1['error']}"],
            cumulative_cost,
            phases_data + [{"label": "P1", **p1}],
        )
    cumulative_cost += p1["cost"]
    phases_data.append({"label": "P1", **p1})
    findings.extend(verify_phase1_curated_bank(p1))
    findings.extend(p1.get("grounding_findings", []))
    if cumulative_cost > COST_CAP_INR:
        return _summarise(
            findings + ["cost cap hit after P1"], cumulative_cost, phases_data
        )

    # ── Phase 2: practice_curator generative fallback ─────────────
    p2 = await run_single(
        label="PHASE 2 — practice_curator generative fallback (data_analyst, empty bank)",
        agent_name="practice_curator",
        user_id=da_empty.user_id,
        role_slug=da_empty.current_role_slug,
        db_factory=db_factory,
        payload={
            "user_message": "Give me a data_analyst practice exercise.",
            "exercise_type": "coding",
            "difficulty_level": "medium",
        },
    )
    if "error" in p2:
        return _summarise(
            findings + [f"P2 errored: {p2['error']}"],
            cumulative_cost,
            phases_data + [{"label": "P2", **p2}],
        )
    cumulative_cost += p2["cost"]
    phases_data.append({"label": "P2", **p2})
    findings.extend(verify_phase2_generative_fallback(p2))
    findings.extend(p2.get("grounding_findings", []))
    if cumulative_cost > COST_CAP_INR:
        return _summarise(
            findings + ["cost cap hit after P2"], cumulative_cost, phases_data
        )

    # ── Phase 3: project_evaluator gate-context ───────────────────
    p3 = await run_single(
        label="PHASE 3 — project_evaluator gate-context (ml_engineer capstone)",
        agent_name="project_evaluator",
        user_id=ml_cap.user_id,
        role_slug=ml_cap.current_role_slug,
        db_factory=db_factory,
        payload={
            "project_submission_id": submission_id,
            "user_message": "Please evaluate my D12 CP3 RAG Capstone.",
        },
    )
    if "error" in p3:
        return _summarise(
            findings + [f"P3 errored: {p3['error']}"],
            cumulative_cost,
            phases_data + [{"label": "P3", **p3}],
        )
    cumulative_cost += p3["cost"]
    phases_data.append({"label": "P3", **p3})
    findings.extend(verify_phase3_gate_context(p3))
    findings.extend(p3.get("grounding_findings", []))
    if cumulative_cost > COST_CAP_INR:
        return _summarise(
            findings + ["cost cap hit after P3"], cumulative_cost, phases_data
        )

    # ── Phase 4: mock_interview gate-prep verdict (multi-turn) ────
    p4 = await run_multi_turn_session(
        label="PHASE 4 — mock_interview gate-prep verdict (ml_engineer→genai_engineer)",
        user_id=ml.user_id,
        role_slug=ml.current_role_slug,
        db_factory=db_factory,
        initial_payload={
            "mode": "system_design",
            "user_message": (
                "I'm preparing for the gate to genai_engineer; let's do a "
                "mock on RAG architecture."
            ),
        },
        max_turns=6,
    )
    if "error" in p4:
        return _summarise(
            findings + [f"P4 errored: {p4['error']}"],
            cumulative_cost,
            phases_data + [{"label": "P4", **p4}],
        )
    cumulative_cost += p4["cost"]
    phases_data.append({"label": "P4", **p4})
    findings.extend(verify_phase4_session_verdict(p4))
    findings.extend(p4.get("grounding_findings", []))

    return _summarise(findings, cumulative_cost, phases_data)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
