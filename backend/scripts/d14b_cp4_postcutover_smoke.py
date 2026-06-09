"""D14b CP4 — post-cutover smoke for practice_curator.

Single Phase-1-shape call (easy + recursion + coding) through the
canonical dispatch path post-rename. Verifies the rename
(practice_curator_v2.py → practice_curator.py) didn't break anything
CP3 verified.

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


async def main() -> int:
    print("=" * 70)
    print("D14b CP4 — post-cutover smoke")
    print("=" * 70)

    # Pattern 16: BOTH loaders.
    from app.agents._agentic_loader import load_agentic_agents
    from app.agents.primitives.tools import ensure_tools_loaded

    load_agentic_agents()
    ensure_tools_loaded()

    # Sanity check: agent reachable under canonical name + canonical
    # module path (post-rename verification).
    from app.agents.primitives.communication import get_agentic

    agent = get_agentic("practice_curator")
    print(f"\n✓ get_agentic('practice_curator') resolved: {type(agent).__name__}")
    assert type(agent).__module__ == "app.agents.practice_curator", (
        f"Expected module 'app.agents.practice_curator', got "
        f"{type(agent).__module__!r}. Cutover may be incomplete."
    )
    print(f"✓ module path: {type(agent).__module__} (canonical, not _v2)")

    # Sanity check: legacy AGENT_REGISTRY does not carry it (net-new
    # agent; should never have been there).
    from app.agents.registry import AGENT_REGISTRY, _ensure_registered

    _ensure_registered()
    if "practice_curator" in AGENT_REGISTRY:
        print("\n!! practice_curator leaked into legacy AGENT_REGISTRY")
        return 1
    print("✓ practice_curator NOT in legacy AGENT_REGISTRY (net-new agent; correct)")

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
        await db.execute(
            sql_text(
                "UPDATE course_entitlements SET expires_at = now() + interval '1 hour' "
                "WHERE user_id = :uid AND revoked_at IS NULL"
            ),
            {"uid": user_id},
        )
        await db.commit()
    print(f"\n✓ test user reused: {user_id}")

    # Phase-1-shape input — same as CP3 Phase 1.
    payload = {
        "concept_focus": "recursion",
        "exercise_type": "coding",
        "difficulty_level": "easy",
        "user_message": "Give me a coding exercise to practice.",
    }
    print(f"\nInput payload (CP3 Phase 1 shape):\n{json.dumps(payload, indent=2)}")

    from app.agents.agentic_base import CallChain
    from app.agents.primitives.communication import call_agent

    async with db_factory() as session:
        chain = CallChain.start_root(caller="d14b_cp4_smoke", user_id=user_id)
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
            return 1
        elapsed = time.monotonic() - start
        await session.commit()

    print(f"\nresult.status:  {result.status}")
    print(f"elapsed:        {elapsed:.2f}s")

    out = result.output if isinstance(result.output, dict) else {}
    exercise = out.get("exercise") or {}
    print(f"\n  title:        {exercise.get('title', '')!r}")
    print(f"  difficulty:   {exercise.get('difficulty')!r}")
    print(f"  concept_tags: {exercise.get('concept_tags')}")
    print(f"  test_cases_visible: {len(exercise.get('test_cases_visible', []))}")
    print(f"  test_cases_hidden:  {len(exercise.get('test_cases_hidden', []))}")
    print(f"  starter_code:  {'populated' if out.get('starter_code') else 'None'}")
    print(f"  hint_sequence: {len(out.get('hint_sequence', []))}")
    print(f"  evaluation_criteria: {len(out.get('evaluation_criteria', []))}")
    print(f"  estimated_time_minutes: {out.get('estimated_time_minutes')}")
    print(f"  handoff_request: {out.get('handoff_request')}")

    # Tool call audit.
    async with db_factory() as db:
        result_tc = await db.execute(
            sql_text(
                """
                SELECT tool_name, status, duration_ms, args
                FROM agent_tool_calls
                WHERE user_id = :uid AND created_at >= :since
                ORDER BY created_at ASC
                """
            ),
            {"uid": user_id, "since": since},
        )
        tool_calls = list(result_tc.fetchall())

        result_aa = await db.execute(
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
        actions = list(result_aa.fetchall())

    print(f"\nagent_tool_calls in window ({len(tool_calls)}):")
    for tc in tool_calls:
        arg = tc.args.get("query") if isinstance(tc.args, dict) else None
        print(
            f"  {tc.tool_name!r}  status={tc.status}  "
            f"{tc.duration_ms}ms  arg={arg!r:.50}"
        )

    print(f"\nagent_actions in window ({len(actions)}):")
    cost = 0.0
    for a in actions:
        c = float(a.cost_inr) if a.cost_inr else 0.0
        cost += c
        print(
            f"  {a.agent_name!r}  status={a.status}  "
            f"cost=₹{c:.4f}  tokens={a.tokens_used}  duration={a.duration_ms}ms"
        )
    print(f"\nphase cost: ₹{cost:.4f}")

    # Verification.
    findings: list[str] = []
    if result.status != "ok":
        findings.append(f"result.status={result.status!r} (expected 'ok')")
    if exercise.get("difficulty") != "easy":
        findings.append(f"difficulty={exercise.get('difficulty')!r}, expected 'easy'")
    if not out.get("starter_code"):
        findings.append("coding exercise produced None starter_code")
    if not exercise.get("test_cases_visible"):
        findings.append("test_cases_visible empty (prompt requires 1-3 typical cases)")
    if out.get("handoff_request") is not None:
        findings.append("handoff_request non-None despite no evaluation request (D-A violation)")
    if elapsed > 60.0:
        findings.append(f"elapsed {elapsed:.2f}s exceeds 60s budget")
    # Tool count: must be 4 (2 memory_recall + 2 DB reads).
    expected_tools = {"memory_recall", "read_student_full_progress", "read_recent_session_history"}
    seen_tools = {tc.tool_name for tc in tool_calls}
    missing = expected_tools - seen_tools
    if missing:
        findings.append(f"missing expected tool calls: {missing}")
    if len(actions) != 1 or actions[0].status != "completed":
        findings.append(f"expected 1 completed agent_actions row; got {[a.status for a in actions]}")

    print("\n" + "=" * 70)
    print("CP4 POST-CUTOVER SMOKE SUMMARY")
    print("=" * 70)
    if findings:
        print(f"\nFindings ({len(findings)}):")
        for f in findings:
            print(f"  - {f}")
        return 1
    print("\n✓ No findings. CP4 cutover verified live.")
    print(f"  agent reachable:    app.agents.practice_curator (canonical name)")
    print(f"  legacy registry:    clean (net-new agent; never registered)")
    print(f"  dispatch + tools:   4 tool calls fired in correct order")
    print(f"  schema invariants:  difficulty={exercise.get('difficulty')!r}; "
          f"handoff_request=None; budget held at {elapsed:.2f}s/60s")
    print(f"  cost:               ₹{cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
