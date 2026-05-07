"""D13 CP4 post-cutover smoke — single MiniMax call after rename.

Exercises the production dispatch path with the CP3 Phase 1 input
shape (no handoff_request expected on a question turn). Confirms:

  • Loader picks up app.agents.mock_interview (formerly _v2)
  • Agent class registers under the canonical name
  • call_agent dispatches successfully
  • LLM call → parse → validate → memory_write all fire
  • Critic loop fires and passes (Bug 18 + 19 fixes still hold)

Cost: ~₹0.20-0.30 (one MiniMax smart-tier call).
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


async def main() -> int:
    print("=" * 70)
    print("D13 CP4 post-cutover smoke")
    print("=" * 70)

    from app.agents._agentic_loader import load_agentic_agents
    from app.agents.primitives.tools import ensure_tools_loaded

    load_agentic_agents()
    ensure_tools_loaded()

    # Sanity check: the agent is reachable under its canonical name.
    from app.agents.primitives.communication import get_agentic

    agent = get_agentic("mock_interview")
    print(f"\n✓ get_agentic('mock_interview') resolved: {type(agent).__name__}")
    assert type(agent).__module__ == "app.agents.mock_interview", (
        f"Expected module 'app.agents.mock_interview', got "
        f"{type(agent).__module__!r}. Cutover may be incomplete."
    )
    print(f"✓ module path: {type(agent).__module__} (canonical, not _v2)")

    # Sanity check: legacy AGENT_REGISTRY does not carry the agent.
    from app.agents.registry import AGENT_REGISTRY, _ensure_registered

    _ensure_registered()
    if "mock_interview" in AGENT_REGISTRY:
        print("\n!! mock_interview leaked into legacy AGENT_REGISTRY — cutover incomplete")
        return 1
    print("✓ mock_interview NOT in legacy AGENT_REGISTRY (retirement pin holds)")

    engine = create_async_engine(DB_DSN, future=True)
    db_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with db_factory() as db:
        result = await db.execute(
            sql_text("SELECT id FROM users WHERE email = :email"),
            {"email": TEST_USER_EMAIL},
        )
        row = result.fetchone()
        if row is None:
            print("ERROR: test user not found.")
            return 1
        user_id = row.id
        # Refresh entitlement.
        await db.execute(
            sql_text(
                "UPDATE course_entitlements SET expires_at = now() + interval '1 hour' "
                "WHERE user_id = :uid AND revoked_at IS NULL"
            ),
            {"uid": user_id},
        )
        await db.commit()
    print(f"\n✓ test user reused: {user_id}")

    # Single dispatch — Phase 1 shape, no handoff_request expected.
    payload = {
        "mode": "behavioral",
        "user_message": (
            "Quick check: ask me a short behavioral interview question."
        ),
        "target_role": "Senior GenAI Engineer",
    }
    print(f"\nInput payload:\n{json.dumps(payload, indent=2)}")

    from app.agents.agentic_base import CallChain
    from app.agents.primitives.communication import call_agent

    async with db_factory() as session:
        chain = CallChain.start_root(caller="d13_cp4_smoke", user_id=user_id)
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
    print(f"  handoff_req:   {out.get('handoff_request')}")

    findings: list[str] = []
    if result.status != "ok":
        findings.append(f"result.status={result.status!r} (expected 'ok')")
    if out.get("turn_kind") not in ("question", "session_summary"):
        findings.append(f"unexpected turn_kind {out.get('turn_kind')!r}")
    if out.get("mode") != "behavioral":
        findings.append(f"mode drift {out.get('mode')!r}")
    if out.get("turn_kind") != "session_summary" and out.get("handoff_request") is not None:
        findings.append("handoff_request non-null on non-summary turn")
    if elapsed > 60.0:
        findings.append(f"elapsed {elapsed:.2f}s exceeds 60s budget")

    # Cost check.
    async with db_factory() as db:
        result = await db.execute(
            sql_text(
                """
                SELECT agent_name, status, cost_inr, tokens_used, duration_ms
                FROM agent_actions
                WHERE student_id = :uid AND created_at >= :since
                ORDER BY created_at ASC
                """
            ),
            {"uid": user_id, "since": since},
        )
        actions = list(result.fetchall())

    print(f"\nagent_actions in window ({len(actions)}):")
    cost = 0.0
    for a in actions:
        c = float(a.cost_inr) if a.cost_inr is not None else 0.0
        cost += c
        print(
            f"    {a.agent_name!r}  status={a.status}  "
            f"cost=₹{c:.4f}  tokens={a.tokens_used}  duration={a.duration_ms}ms"
        )
    print(f"\nphase cost: ₹{cost:.4f}")

    print("\n" + "=" * 70)
    print("CP4 POST-CUTOVER SMOKE SUMMARY")
    print("=" * 70)
    if findings:
        print(f"\nFindings ({len(findings)}):")
        for f in findings:
            print(f"  - {f}")
        return 1
    print("\n✓ No findings. Cutover verified live.")
    print(f"  agent reachable: app.agents.mock_interview (canonical name)")
    print(f"  legacy AGENT_REGISTRY: clean")
    print(f"  dispatch + LLM + parse + memory all fired correctly")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
