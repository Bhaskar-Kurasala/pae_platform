"""D14b CP3 — real-LLM verification for practice_curator.

Drives PracticeCuratorAgent.run() through call_agent() (the production
dispatch primitive) so memory/tool audit + cost tracking + agent_actions
all fire end-to-end. Mirrors the D13 mock_interview CP3 harness pattern.

Three phases per CP3 spec:
  1. Explicit constraints: easy + recursion + coding
  2. Different constraints: hard + system_design (concept_focus None)
  3. All inputs empty: agent picks based on student state

Phase 4 is calibration math from measurements. Phase 5 is informational
quality observation captured in the printout.

Run inside the backend container:
    uv run python scripts/d14b_cp3_practice_curator_real_llm.py

Cost cap: ₹2.00 cumulative across phases.
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
COST_CAP_INR = 2.00


# ── Setup ─────────────────────────────────────────────────────────


async def setup_user_and_entitlement(db: Any) -> uuid.UUID:
    result = await db.execute(
        sql_text("SELECT id FROM users WHERE email = :email"),
        {"email": TEST_USER_EMAIL},
    )
    row = result.fetchone()
    if row is None:
        print("ERROR: test user not found. Run a prior CP3 harness first.")
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
            SELECT agent_name, tool_name, status, duration_ms, args, created_at
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
            "args_query": row.args.get("query") if isinstance(row.args, dict) else None,
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
    """Critic evaluation rows. uses_self_eval=False on practice_curator
    means we expect this list to be empty per phase. Stage invariant:
    Critic should NOT fire."""
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
        chain = CallChain.start_root(caller="d14b_cp3", user_id=user_id)
        since = datetime.now(UTC) - timedelta(seconds=2)
        start = time.monotonic()
        try:
            result = await call_agent(
                "practice_curator",
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

    exercise = out.get("exercise") or {}
    print(f"\n  title:                 {exercise.get('title', '')!r}")
    print(f"  concept_tags:          {exercise.get('concept_tags')}")
    print(f"  difficulty:            {exercise.get('difficulty')!r}")
    print(f"  description (first 300): {(exercise.get('description', '')[:300])!r}")
    print(f"  constraints:           {exercise.get('constraints')}")
    print(f"  test_cases_visible: {len(exercise.get('test_cases_visible', []))} items")
    for i, tc in enumerate(exercise.get("test_cases_visible", [])[:3]):
        print(f"    [{i}] in: {tc.get('input_description', '')[:80]!r}")
        print(f"        out: {tc.get('expected_output_description', '')[:80]!r}")
    print(f"  test_cases_hidden:  {len(exercise.get('test_cases_hidden', []))} items")

    print(f"\n  starter_code (first 300):")
    sc = out.get("starter_code")
    if sc:
        print(f"    {sc[:300]!r}")
    else:
        print(f"    None")

    print(f"  expected_solution_shape: {(out.get('expected_solution_shape', '') or '')[:200]!r}")
    print(f"  evaluation_criteria: {len(out.get('evaluation_criteria', []))} items")
    for i, c in enumerate(out.get("evaluation_criteria", [])[:5]):
        print(f"    [{i}] {c[:120]!r}")
    print(f"  hint_sequence:       {len(out.get('hint_sequence', []))} items")
    for i, h in enumerate(out.get("hint_sequence", [])[:3]):
        print(f"    order={h.get('order')}: {h.get('text', '')[:100]!r}")
    print(f"  estimated_time_minutes: {out.get('estimated_time_minutes')}")
    print(f"  handoff_request:        {out.get('handoff_request')}")

    print(f"\n  answer (first 200): {(out.get('answer') or '')[:200]!r}")

    # Telemetry.
    async with db_factory() as db:
        tool_calls = await fetch_tool_calls(db, user_id, since)
        actions = await fetch_agent_actions(db, user_id, since)
        evals = await fetch_evaluations(db, user_id, since)

    print(f"\nagent_tool_calls in window ({len(tool_calls)}):")
    for tc in tool_calls:
        identifier = tc["args_query"] or "-"
        print(
            f"  {tc['agent_name']!r}.{tc['tool_name']!r}  status={tc['status']}  "
            f"{tc['duration_ms']}ms  arg={identifier!r:.50}"
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


def verify_basic_invariants(
    *, label: str, phase: dict[str, Any]
) -> list[str]:
    """Common invariant checks across all phases."""
    findings: list[str] = []
    out = phase["output"]

    if not out:
        findings.append(f"{label}: output is empty (status={phase.get('result').status if phase.get('result') else 'unknown'})")
        return findings

    exercise = out.get("exercise") or {}

    # Schema invariants.
    if not exercise.get("title"):
        findings.append(f"{label}: exercise.title is empty")
    if not exercise.get("description"):
        findings.append(f"{label}: exercise.description is empty")
    if not exercise.get("concept_tags"):
        findings.append(f"{label}: exercise.concept_tags is empty")

    # estimated_time_minutes within schema bounds.
    etm = out.get("estimated_time_minutes")
    if etm is None or etm < 5 or etm > 180:
        findings.append(f"{label}: estimated_time_minutes={etm} outside schema range 5-180")

    # evaluation_criteria has at least 1 specific element.
    crit = out.get("evaluation_criteria", [])
    if not crit:
        findings.append(f"{label}: evaluation_criteria is empty (prompt requires 'specific, observable criterion')")

    # handoff_request gating: phases 1-3 don't request evaluation, so should be None.
    if out.get("handoff_request") is not None:
        findings.append(
            f"{label}: handoff_request is non-None despite no evaluation request "
            "(D-A defense-in-depth runtime gating violated)"
        )

    # Critic should NOT fire (uses_self_eval=False).
    if phase["evals"]:
        findings.append(
            f"{label}: Critic fired unexpectedly ({len(phase['evals'])} eval rows; uses_self_eval=False)"
        )

    return findings


# ── Main ──────────────────────────────────────────────────────────


async def main() -> int:
    print("=" * 70)
    print("D14b CP3 — practice_curator real-LLM verification")
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
        label="PHASE 1 — Explicit constraints (easy + recursion + coding)",
        user_id=user_id,
        db_factory=db_factory,
        payload={
            "concept_focus": "recursion",
            "exercise_type": "coding",
            "difficulty_level": "easy",
            "user_message": "Give me a coding exercise to practice.",
        },
    )
    if "error" in p1:
        print("\n!! Phase 1 errored — aborting CP3.")
        return 1
    cumulative_cost += p1["cost"]
    phases_data.append({"label": "P1", **p1})

    findings.extend(verify_basic_invariants(label="P1", phase=p1))
    p1_out = p1["output"]
    p1_exercise = p1_out.get("exercise") or {}
    if p1_exercise.get("difficulty") != "easy":
        findings.append(
            f"P1: difficulty={p1_exercise.get('difficulty')!r}, expected 'easy'"
        )
    # exercise_type=coding ⇒ starter_code populated per prompt guidance.
    if not p1_out.get("starter_code"):
        findings.append("P1: coding exercise produced None starter_code (prompt says coding type should populate)")
    # test_cases_visible at least 1 element.
    if not p1_exercise.get("test_cases_visible"):
        findings.append("P1: test_cases_visible is empty (prompt requires 1-3 typical cases)")
    # estimated_time_minutes within easy quality range (informational).
    etm = p1_out.get("estimated_time_minutes")
    if etm and (etm < 15 or etm > 30):
        print(f"  ⚠ P1 quality observation: estimated_time_minutes={etm} outside easy quality range (15-30)")

    # Cost gate.
    if cumulative_cost > COST_CAP_INR:
        return _summarise(findings, cumulative_cost, phases_data)

    if p1["elapsed"] > 60.0:
        findings.append(f"P1: elapsed {p1['elapsed']:.2f}s exceeds 60s budget")

    # ── Phase 2 ──────────────────────────────────────────────────
    p2 = await run_phase(
        label="PHASE 2 — Hard + system_design + concept_focus None",
        user_id=user_id,
        db_factory=db_factory,
        payload={
            "exercise_type": "system_design",
            "difficulty_level": "hard",
            "user_message": "Give me a system design exercise.",
        },
    )
    if "error" in p2:
        print("\n!! Phase 2 errored.")
        return _summarise(findings + [f"P2 errored: {p2['error']}"], cumulative_cost, phases_data)
    cumulative_cost += p2["cost"]
    phases_data.append({"label": "P2", **p2})

    findings.extend(verify_basic_invariants(label="P2", phase=p2))
    p2_out = p2["output"]
    p2_exercise = p2_out.get("exercise") or {}
    if p2_exercise.get("difficulty") != "hard":
        findings.append(
            f"P2: difficulty={p2_exercise.get('difficulty')!r}, expected 'hard'"
        )
    # description should be substantive for system design.
    desc_len = len(p2_exercise.get("description", "") or "")
    if desc_len < 300:
        print(f"  ⚠ P2 quality observation: description length {desc_len} chars (expected >500 for hard system_design)")
    elif desc_len < 500:
        print(f"  ⚠ P2 description {desc_len} chars (acceptable but on the short side for hard system_design)")
    etm = p2_out.get("estimated_time_minutes")
    if etm and (etm < 60 or etm > 180):
        print(f"  ⚠ P2 quality observation: estimated_time_minutes={etm} outside hard quality range (60-180)")

    if cumulative_cost > COST_CAP_INR:
        return _summarise(findings, cumulative_cost, phases_data)

    if p2["elapsed"] > 60.0:
        findings.append(f"P2: elapsed {p2['elapsed']:.2f}s exceeds 60s budget")

    # ── Phase 3 — all empty ──────────────────────────────────────
    p3 = await run_phase(
        label="PHASE 3 — All inputs None (agent picks based on student state)",
        user_id=user_id,
        db_factory=db_factory,
        payload={
            "user_message": "I want to practice something.",
        },
    )
    if "error" in p3:
        print("\n!! Phase 3 errored.")
        return _summarise(findings + [f"P3 errored: {p3['error']}"], cumulative_cost, phases_data)
    cumulative_cost += p3["cost"]
    phases_data.append({"label": "P3", **p3})

    findings.extend(verify_basic_invariants(label="P3", phase=p3))
    p3_out = p3["output"]
    p3_exercise = p3_out.get("exercise") or {}
    p3_difficulty = p3_exercise.get("difficulty")
    if p3_difficulty not in ("easy", "medium", "hard"):
        findings.append(
            f"P3: difficulty={p3_difficulty!r} not in allowlist (Literal validation)"
        )

    if cumulative_cost > COST_CAP_INR:
        return _summarise(findings, cumulative_cost, phases_data)

    if p3["elapsed"] > 60.0:
        findings.append(f"P3: elapsed {p3['elapsed']:.2f}s exceeds 60s budget")

    # ── Phase 3 differentiation check ───────────────────────────
    # CP3 hard stop: phases produce identical or near-identical exercises.
    p1_title = (p1_exercise.get("title") or "").strip()
    p2_title = (p2_exercise.get("title") or "").strip()
    p3_title = (p3_exercise.get("title") or "").strip()
    if p1_title and p2_title and p1_title.lower() == p2_title.lower():
        findings.append("P1 and P2 produced identical titles — inputs not driving differentiation")
    if p1_title and p3_title and p1_title.lower() == p3_title.lower():
        findings.append("P1 and P3 produced identical titles")
    if p2_title and p3_title and p2_title.lower() == p3_title.lower():
        findings.append("P2 and P3 produced identical titles")

    # ── Phase 4 calibration ──────────────────────────────────────
    print("\n" + "=" * 70)
    print("PHASE 4 — Calibration")
    print("=" * 70)
    elapsed_max = max(p1["elapsed"], p2["elapsed"], p3["elapsed"])
    elapsed_p50 = sorted([p1["elapsed"], p2["elapsed"], p3["elapsed"]])[1]
    print(f"P1 elapsed: {p1['elapsed']:.2f}s")
    print(f"P2 elapsed: {p2['elapsed']:.2f}s")
    print(f"P3 elapsed: {p3['elapsed']:.2f}s")
    print(f"P50 (median of 3): {elapsed_p50:.2f}s")
    print(f"Max: {elapsed_max:.2f}s")
    print(f"Current capability budget: 60s (timeout_override_seconds=60 per D14b CP3 calibration)")
    if elapsed_max <= 60.0:
        print("Calibration: WITHIN BUDGET — no recalibration needed.")
    else:
        suggested = int((elapsed_max * 1000) / 3) + 1
        print(f"Calibration: OVER BUDGET — suggest timeout_override_seconds bump")
        findings.append(
            f"Calibration: max elapsed {elapsed_max:.2f}s exceeds 60s override; suggest higher override"
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

    # Phase 5 quality observations (informational).
    print("\n" + "─" * 50)
    print("PHASE 5 — Quality observations (informational)")
    print("─" * 50)
    for p in phases:
        out = p.get("output") or {}
        ex = out.get("exercise") or {}
        print(f"\n{p['label']}: '{ex.get('title', '')[:80]!r}'")
        print(f"  concept_tags: {ex.get('concept_tags')}")
        print(f"  difficulty: {ex.get('difficulty')}")
        print(f"  estimated_time_minutes: {out.get('estimated_time_minutes')}")
        print(f"  evaluation_criteria count: {len(out.get('evaluation_criteria', []))}")
        print(f"  hints count: {len(out.get('hint_sequence', []))}")
        print(f"  test_cases_visible count: {len(ex.get('test_cases_visible', []))}")
        print(f"  test_cases_hidden count: {len(ex.get('test_cases_hidden', []))}")
        print(f"  starter_code: {'populated' if out.get('starter_code') else 'None'}")

    if findings:
        print(f"\nFindings ({len(findings)}):")
        for f in findings:
            print(f"  - {f}")
        return 1
    print("\n✓ No findings. CP3 verification clean.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
