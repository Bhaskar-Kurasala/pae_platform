"""D13 CP4 post-cutover smoke OR CP3 Phase 4 — handoff_request shape verification.

After the CP4 rename (mock_interview_v2.py → mock_interview.py), this
same harness exercises the production dispatch path to confirm
nothing broke in the cutover. Single MiniMax call; same input shape
as CP3 Phase 4.


Drives one wrap-up turn using the Phase 1 session_id from the prior
CP3 attempt. Verifies Bug 21 (handoff suggested_context dict shape)
and Bug 22 (eval-row writer None-handling) both fire clean live.

Cost: ~₹0.20-0.30.
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
COST_CAP_INR = 0.50

# Reuse the session_id from the prior CP3 attempt that landed Phase 1
# successfully. The session log + weakness rows under this session_id
# remain in agent_memory and will be recalled by mock_interview's
# memory_recall.
PRIOR_SESSION_ID = "7b466123-00a8-4196-87fd-9a2d9c9abd63"


async def setup_user_and_entitlement(db: Any) -> uuid.UUID:
    result = await db.execute(
        sql_text("SELECT id FROM users WHERE email = :email"),
        {"email": TEST_USER_EMAIL},
    )
    row = result.fetchone()
    if row is None:
        print("ERROR: test user not found. Run the full CP3 harness first.")
        raise SystemExit(1)
    user_id = row.id
    print(f"... reusing user {user_id}")

    # Refresh entitlement window.
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
            "args_key": row.args.get("key") if isinstance(row.args, dict) else None,
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
    result = await db.execute(
        sql_text(
            """
            SELECT agent_name, attempt_number, total_score, passed,
                   critic_reasoning
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
            "reason_excerpt": (row.critic_reasoning or "")[:200],
        }
        for row in result.fetchall()
    ]


async def main() -> int:
    print("=" * 70)
    print("D13 CP3 Phase 4 (re-run only) — handoff shape verification")
    print(f"Reusing session_id: {PRIOR_SESSION_ID}")
    print("=" * 70)

    from app.agents._agentic_loader import load_agentic_agents
    from app.agents.primitives.tools import ensure_tools_loaded

    load_agentic_agents()
    ensure_tools_loaded()

    engine = create_async_engine(DB_DSN, future=True)
    db_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with db_factory() as db:
        user_id = await setup_user_and_entitlement(db)

    from app.agents.agentic_base import CallChain
    from app.agents.primitives.communication import call_agent

    payload = {
        "mode": "behavioral",
        "session_id": PRIOR_SESSION_ID,
        "user_message": (
            "Thanks, I think we can wrap up here. What's your assessment "
            "of how I did?"
        ),
    }
    print(f"\nInput payload:\n{json.dumps(payload, indent=2)}")

    findings: list[str] = []

    async with db_factory() as session:
        chain = CallChain.start_root(caller="d13_cp3_phase4", user_id=user_id)
        since = datetime.now(UTC) - timedelta(seconds=2)
        start = time.monotonic()
        try:
            result = await call_agent(
                "mock_interview",
                payload=payload,
                session=session,
                chain=chain,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            print(f"\n!! call_agent raised after {elapsed:.2f}s: "
                  f"{type(exc).__name__}: {exc}")
            return 1
        elapsed = time.monotonic() - start
        await session.commit()

    print(f"\nresult.status:  {result.status}")
    print(f"elapsed:        {elapsed:.2f}s")

    out = result.output if isinstance(result.output, dict) else {}
    print(f"\noutput keys:    {list(out.keys())}")
    print(f"  session_id:    {out.get('session_id')}")
    print(f"  mode:          {out.get('mode')}")
    print(f"  turn_kind:     {out.get('turn_kind')}")

    # Hard checks per CP3 Phase 4 spec.
    if out.get("session_id") != PRIOR_SESSION_ID:
        findings.append(
            f"D-1 violation: session_id {out.get('session_id')!r} "
            f"!= {PRIOR_SESSION_ID!r}"
        )
    if out.get("mode") != "behavioral":
        findings.append(f"mode drift: {out.get('mode')!r}")

    summary = out.get("session_summary")
    if out.get("turn_kind") == "session_summary":
        print("\nsession_summary populated:")
        if summary:
            print(f"  overall_score:   {summary.get('overall_score_0_to_100')}")
            print(f"  headline:        {summary.get('headline')!r}")
            print(f"  strengths:       {summary.get('strengths')}")
            print(f"  weaknesses:      {summary.get('weaknesses')}")
            print(f"  next_action:     {summary.get('suggested_next_action', '')[:150]!r}")
        else:
            findings.append("turn_kind=session_summary but session_summary sub-object missing")
    else:
        findings.append(
            f"turn_kind {out.get('turn_kind')!r} — expected 'session_summary'"
        )

    hr = out.get("handoff_request")
    print("\nhandoff_request:")
    if hr is None:
        print("  None (allowed on session_summary if no handoff warranted)")
    else:
        print(f"  target_agent:        {hr.get('target_agent')!r}")
        print(f"  reason:              {hr.get('reason', '')[:150]!r}")
        print(f"  handoff_type:        {hr.get('handoff_type')!r}")
        sc = hr.get("suggested_context")
        print(f"  suggested_context:   type={type(sc).__name__} value={sc!r}")

        # Bug 21 verification: suggested_context must be a dict.
        if not isinstance(sc, dict):
            findings.append(
                f"BUG 21 REGRESSION: suggested_context is "
                f"{type(sc).__name__}, expected dict"
            )

        # Schema validation against Supervisor's HandoffRequest.
        try:
            from app.schemas.supervisor import HandoffRequest

            HandoffRequest.model_validate(hr)
            print(
                "\n  ✓ validates against app.schemas.supervisor.HandoffRequest"
            )
        except Exception as exc:  # noqa: BLE001
            findings.append(
                f"HandoffRequest schema validation failed: "
                f"{type(exc).__name__}: {exc}"
            )

        if hr.get("target_agent") not in ("senior_engineer", "career_coach"):
            findings.append(
                f"target_agent {hr.get('target_agent')!r} not in "
                "{senior_engineer, career_coach}"
            )
        if hr.get("handoff_type") != "suggested":
            findings.append(
                f"handoff_type {hr.get('handoff_type')!r} should be 'suggested' "
                "(D-2 disallows mandatory in D13)"
            )

    print(f"\nanswer (first 250 chars):\n  {(out.get('answer') or '')[:250]!r}")

    # Pull telemetry.
    async with db_factory() as db:
        tool_calls = await fetch_tool_calls(db, user_id, since)
        actions = await fetch_agent_actions(db, user_id, since)
        evals = await fetch_evaluations(db, user_id, since)

    print(f"\nagent_tool_calls in window ({len(tool_calls)}):")
    for tc in tool_calls:
        identifier = tc["args_query"] or tc["args_key"] or "-"
        print(
            f"    {tc['agent_name']!r}.{tc['tool_name']!r}  status={tc['status']}  "
            f"{tc['duration_ms']}ms  arg={identifier!r:.60}"
        )

    print(f"\nagent_actions in window ({len(actions)}):")
    cost = 0.0
    for a in actions:
        cost += a["cost_inr"]
        print(
            f"    {a['agent_name']!r}  status={a['status']}  "
            f"cost=₹{a['cost_inr']:.4f}  tokens={a['tokens_used']}  "
            f"duration={a['duration_ms']}ms  model={a['model']!r}"
        )

    print(f"\nagent_evaluations in window ({len(evals)}):")
    for ev in evals:
        score_str = f"{ev['score']:.4f}" if ev['score'] is not None else "None"
        print(
            f"    {ev['agent']!r}  attempt={ev['attempt']}  "
            f"score={score_str}  passed={ev['passed']}  "
            f"reason={ev['reason_excerpt']!r:.120}"
        )

    # Bug 22 check: if any eval row was written with the agent-call-failed
    # path (where total_score=None pre-fix), it should now be 0.0.
    bug22_clean = all(
        ev["score"] is not None for ev in evals
    )
    if bug22_clean:
        print("\n✓ Bug 22 verified: all eval rows have non-None total_score")
    else:
        findings.append(
            "BUG 22 REGRESSION: eval row written with None total_score"
        )

    print(f"\nphase cost: ₹{cost:.4f}")

    print("\n" + "=" * 70)
    print("PHASE 4 SUMMARY")
    print("=" * 70)
    if findings:
        print(f"\nFindings ({len(findings)}):")
        for f in findings:
            print(f"  - {f}")
        return 1
    print("\nNo findings. Phase 4 verification clean.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
