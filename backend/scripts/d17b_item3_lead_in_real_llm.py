"""D17b/ITEM 3 (Path E) — 4-phase real-LLM verification.

Replaces the original 7-phase prompt-side verification (which surfaced
tone-competition + timeout drift). Path E is deterministic post-LLM
opener composition; the LLM doesn't see the lead-in section. So
verification simplifies to:

  P1 career_coach + returning_after_absence student
     verify: response begins with returning-after-absence opener
     verify: rest of response is normal career_coach behavior

  P2 career_coach + healthy student (control)
     verify: NO opener prepended
     verify: response identical-shape to pre-D17b career_coach behavior

  P3 study_planner + stalled student
     verify: response begins with stalled opener
     verify: rest of response is normal study_planner behavior
     verify: no timeout drift (prompt unchanged; should not hit 30s)

  P4 study_planner + healthy student (control)
     verify: NO opener prepended
     verify: baseline study_planner behavior

The opener templates are deterministic; we can match them exactly.
The rest of the response is LLM-generated and shouldn't be brittle-
matched, so we just sanity-check it's non-empty + structured.

Run inside the backend container:

    docker compose exec -T -e \\
      DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/platform \\
      backend uv run python scripts/d17b_item3_lead_in_real_llm.py

Cost cap: ₹1.00 (D17b prompt revised budget; expected ₹0.30-0.50).
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
COST_CAP_INR = 1.00


# Verbatim opener fragments (anchor to template content not the LLM output).
RETURNING_CAREER_COACH_FRAGMENT = "Welcome back"
RETURNING_STUDY_PLANNER_FRAGMENT = "Last week's plan"
STALLED_STUDY_PLANNER_FRAGMENT = "exercises haven't been clicking"


async def fetch_agent_actions(
    db: Any, user_id: Any, since: datetime
) -> list[dict[str, Any]]:
    result = await db.execute(
        sql_text(
            """
            SELECT agent_name, status, cost_inr, tokens_used,
                   duration_ms, output_data
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


async def run_phase(
    *,
    label: str,
    agent_name: str,
    user_id: Any,
    db_factory: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from app.agents.agentic_base import CallChain
    from app.agents.primitives.communication import call_agent

    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}")
    print(f"\nAgent: {agent_name}")
    print(f"User:  {user_id}")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    async with db_factory() as session:
        chain = CallChain.start_root(
            caller="d17b_item3_pathE", user_id=user_id
        )
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
    print(f"\n  answer (first 500 chars):\n    {answer[:500]!r}")

    async with db_factory() as db:
        actions = await fetch_agent_actions(db, user_id, since)

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

    return {
        "elapsed": elapsed,
        "result": result,
        "output": out,
        "actions": actions,
        "cost": cost,
        "answer": answer,
    }


# ── Verifiers ─────────────────────────────────────────────────────


def verify_p1_returning_career_coach(phase: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    answer = phase.get("answer") or ""
    if not answer:
        return ["P1: empty answer"]
    # The opener is a deterministic template; it must appear verbatim.
    if RETURNING_CAREER_COACH_FRAGMENT not in answer:
        findings.append(
            "P1: returning-after-absence opener did not prepend — "
            f"'{RETURNING_CAREER_COACH_FRAGMENT}' not in answer head: "
            f"{answer[:200]!r}"
        )
    # The opener should appear at the START (within first 100 chars).
    if (
        RETURNING_CAREER_COACH_FRAGMENT in answer
        and answer.find(RETURNING_CAREER_COACH_FRAGMENT) > 100
    ):
        findings.append(
            "P1: opener fragment present but not at the start of the "
            "answer — prepending may be misordered"
        )
    # The rest of the response should be present and sensible.
    out = phase.get("output") or {}
    if not out.get("headline"):
        findings.append("P1: missing headline (LLM call failed)")
    if not out.get("plan"):
        findings.append("P1: missing plan (structured output incomplete)")
    return findings


def verify_p2_no_opener_career_coach(phase: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    answer = phase.get("answer") or ""
    if not answer:
        return ["P2: empty answer"]
    # No opener fragments should appear.
    forbidden = (
        RETURNING_CAREER_COACH_FRAGMENT,
        "Nice work on that mock",
        "Congratulations on clearing",
    )
    for f in forbidden:
        if f in answer:
            findings.append(
                f"P2: control phase prepended an opener ('{f}') despite "
                "no signal warranting it — composer is incorrectly firing"
            )
    out = phase.get("output") or {}
    if not out.get("headline"):
        findings.append("P2: missing headline (LLM call failed)")
    return findings


def verify_p3_stalled_study_planner(phase: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    answer = phase.get("answer") or ""
    if not answer:
        return ["P3: empty answer"]
    if STALLED_STUDY_PLANNER_FRAGMENT not in answer:
        findings.append(
            "P3: stalled opener did not prepend — "
            f"'{STALLED_STUDY_PLANNER_FRAGMENT}' not in answer head: "
            f"{answer[:200]!r}"
        )
    if (
        STALLED_STUDY_PLANNER_FRAGMENT in answer
        and answer.find(STALLED_STUDY_PLANNER_FRAGMENT) > 100
    ):
        findings.append(
            "P3: opener fragment present but not at start — prepending "
            "may be misordered"
        )
    # No timeout drift expected (prompt is unchanged from pre-D17b).
    elapsed = phase.get("elapsed", 0.0)
    if elapsed >= 28.0:
        findings.append(
            f"P3: elapsed {elapsed:.2f}s is near the 30s study_planner "
            "ceiling — Path E should NOT cause timeout drift since "
            "prompt is unchanged. Investigate."
        )
    return findings


def verify_p4_no_opener_study_planner(phase: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    answer = phase.get("answer") or ""
    if not answer:
        return ["P4: empty answer"]
    forbidden = (
        STALLED_STUDY_PLANNER_FRAGMENT,
        "You've been consistent",
        RETURNING_STUDY_PLANNER_FRAGMENT,
    )
    for f in forbidden:
        if f in answer:
            findings.append(
                f"P4: control phase prepended an opener ('{f}') despite "
                "no signal warranting it"
            )
    return findings


# ── Main ─────────────────────────────────────────────────────────


def _summarise(
    findings: list[str], cost: float, phases_data: list[dict[str, Any]]
) -> int:
    print("\n" + "=" * 72)
    print("D17b ITEM 3 (Path E) SUMMARY")
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
    print("D17b ITEM 3 (Path E) — deterministic lead-in opener real-LLM verification")
    print("=" * 72)

    from app.agents._agentic_loader import load_agentic_agents
    from app.agents.primitives.tools import ensure_tools_loaded

    load_agentic_agents()
    ensure_tools_loaded()

    from tests.fixtures.role_state_fixtures import (  # type: ignore
        seed_healthy_data_analyst,
        seed_returning_after_absence_data_analyst,
        seed_stalled_data_analyst,
    )

    engine = create_async_engine(DB_DSN, future=True)
    db_factory = async_sessionmaker(engine, expire_on_commit=False)

    cumulative_cost = 0.0
    findings: list[str] = []
    phases_data: list[dict[str, Any]] = []

    # Seed all 4 students. Use two healthy fixtures so the two control
    # phases don't share recent agent_actions.
    async with db_factory() as db:
        returning = await seed_returning_after_absence_data_analyst(db)
        stalled = await seed_stalled_data_analyst(db)
        healthy_cc = await seed_healthy_data_analyst(db)
        healthy_sp = await seed_healthy_data_analyst(db)
        await db.commit()
    print(f"\nSeeded:")
    print(f"  returning_after_absence  = {returning.user_id}")
    print(f"  stalled                  = {stalled.user_id}")
    print(f"  healthy_career_coach     = {healthy_cc.user_id}")
    print(f"  healthy_study_planner    = {healthy_sp.user_id}")

    phases_to_run = [
        (
            "P1",
            "PHASE 1 — career_coach + returning-after-absence (opener should fire)",
            "career_coach",
            returning.user_id,
            {"user_message": "How am I doing?"},
            verify_p1_returning_career_coach,
        ),
        (
            "P2",
            "PHASE 2 — career_coach + healthy (control; NO opener)",
            "career_coach",
            healthy_cc.user_id,
            {"user_message": "How am I doing?"},
            verify_p2_no_opener_career_coach,
        ),
        (
            "P3",
            "PHASE 3 — study_planner + stalled (opener should fire)",
            "study_planner",
            stalled.user_id,
            {"user_message": "What should I work on this week?"},
            verify_p3_stalled_study_planner,
        ),
        (
            "P4",
            "PHASE 4 — study_planner + healthy (control; NO opener)",
            "study_planner",
            healthy_sp.user_id,
            {"user_message": "What's this week's plan?"},
            verify_p4_no_opener_study_planner,
        ),
    ]

    for label, banner, agent_name, user_id, payload, verifier in phases_to_run:
        phase = await run_phase(
            label=banner,
            agent_name=agent_name,
            user_id=user_id,
            db_factory=db_factory,
            payload=payload,
        )
        if "error" in phase:
            return _summarise(
                findings + [f"{label} errored: {phase['error']}"],
                cumulative_cost,
                phases_data + [{"label": label, **phase}],
            )
        cumulative_cost += phase["cost"]
        phases_data.append({"label": label, **phase})
        findings.extend(verifier(phase))
        if cumulative_cost > COST_CAP_INR:
            return _summarise(
                findings + [f"cost cap hit after {label}"],
                cumulative_cost,
                phases_data,
            )

    return _summarise(findings, cumulative_cost, phases_data)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
