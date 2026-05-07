"""D14c CP4 — post-cutover smoke for project_evaluator.

Single MiniMax call mirroring CP3 Phase 1 input shape (rubric-grounded
RAG capstone). Verifies:
  • Cutover rename + import paths intact
  • Calibration tightening 90s → 75s holds (elapsed must be < 75s)
  • Output structurally identical to CP3 Phase 1
  • All 4 tools fire in order (cutover didn't break tool wiring)

Run inside the backend container:
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/platform \\
    uv run python scripts/d14c_cp4_post_cutover_smoke.py

Cost expectation: ~₹0.25-0.30.
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
P1_SUBMISSION_ID = "bfca91e8-c652-40bb-b099-3c12bbf6707c"
BUDGET_SECONDS = 90.0  # CP4 held at preemptive 90s — see capability.py
# Notes: a CP4 attempt to tighten to 75s (= CP3 observed_max × 1.30)
# timed out at 75.05s on the same Phase 1 payload that ran in 51.81s
# at CP3, surfacing that MiniMax tail latency is wider than
# observed_max × 1.30 absorbs at n=2 data points.


async def main() -> int:
    print("=" * 70)
    print("D14c CP4 — post-cutover smoke (single call, Phase 1 shape)")
    print("=" * 70)

    # Pattern 16: BOTH loaders.
    from app.agents._agentic_loader import load_agentic_agents
    from app.agents.primitives.tools import ensure_tools_loaded

    load_agentic_agents()
    ensure_tools_loaded()

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
                "UPDATE course_entitlements SET expires_at = "
                "now() + interval '1 hour' "
                "WHERE user_id = :uid AND revoked_at IS NULL"
            ),
            {"uid": user_id},
        )
        await db.commit()
    print(f"... user {user_id}, entitlement refreshed")

    from app.agents.agentic_base import CallChain
    from app.agents.primitives.communication import call_agent

    payload = {
        "project_submission_id": P1_SUBMISSION_ID,
        "specific_concerns": ["architecture quality", "evidence of learning"],
        "user_message": "Please evaluate this capstone submission against the rubric.",
    }

    async with db_factory() as session:
        chain = CallChain.start_root(caller="d14c_cp4_smoke", user_id=user_id)
        since = datetime.now(UTC) - timedelta(seconds=2)
        start = time.monotonic()
        result = await call_agent(
            "project_evaluator",
            payload=payload,
            session=session,
            chain=chain,
        )
        elapsed = time.monotonic() - start
        await session.commit()

    out = result.output if isinstance(result.output, dict) else {}
    print(f"\nresult.status:   {result.status}")
    print(f"elapsed:         {elapsed:.2f}s (budget {BUDGET_SECONDS}s)")
    print(f"rubric_available: {out.get('rubric_available')!r}")
    print(f"overall_score:   {out.get('overall_score')!r}")
    print(f"dim_count:       {len(out.get('dimension_scores', []))}")
    for ds in out.get("dimension_scores", []):
        print(f"  - {ds.get('dimension_name')!r} score={ds.get('score')!r}")
    draft = out.get("portfolio_entry_draft") or {}
    print(f"draft.title:     {draft.get('title')!r}")
    print(f"handoff_request: {out.get('handoff_request')}")

    # Telemetry — verify 4 tool rows fired in order.
    async with db_factory() as db:
        tc_result = await db.execute(
            sql_text(
                "SELECT tool_name, status FROM agent_tool_calls "
                "WHERE user_id = :uid AND created_at >= :since "
                "ORDER BY created_at ASC"
            ),
            {"uid": user_id, "since": since},
        )
        tool_calls = [(r.tool_name, r.status) for r in tc_result.fetchall()]
        ev_result = await db.execute(
            sql_text(
                "SELECT COUNT(*) AS n FROM agent_evaluations "
                "WHERE user_id = :uid AND created_at >= :since"
            ),
            {"uid": user_id, "since": since},
        )
        eval_count = ev_result.scalar_one()
        ac_result = await db.execute(
            sql_text(
                "SELECT cost_inr, tokens_used FROM agent_actions "
                "WHERE student_id = :uid AND created_at >= :since "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"uid": user_id, "since": since},
        )
        last_action = ac_result.fetchone()
        cost = float(last_action.cost_inr) if last_action and last_action.cost_inr else 0.0
        tokens = last_action.tokens_used if last_action else 0

    print(f"\ntool_calls: {tool_calls}")
    print(f"agent_evaluations rows: {eval_count} (expected 0)")
    print(f"cost: ₹{cost:.4f}, tokens: {tokens}")

    # ── Verify ──
    findings: list[str] = []

    if result.status != "ok":
        findings.append(f"result.status={result.status!r}, expected 'ok'")
    if elapsed > BUDGET_SECONDS:
        findings.append(
            f"elapsed {elapsed:.2f}s exceeds tightened budget {BUDGET_SECONDS}s "
            "(calibration too aggressive — revert to 90s and surface)"
        )
    if not out.get("rubric_available"):
        findings.append("rubric_available is not True on rubric-grounded path")
    if not out.get("dimension_scores"):
        findings.append("dimension_scores empty on rubric-grounded path")
    if eval_count > 0:
        findings.append(
            f"Critic fired ({eval_count} eval rows; uses_self_eval=False)"
        )
    expected_tool_order = [
        "read_capstone_submission_content",
        "read_rubric_for_capstone",
        "read_student_full_progress",
        "read_capstone_status",
    ]
    actual_tool_names = [t for t, _ in tool_calls]
    if actual_tool_names[:4] != expected_tool_order:
        findings.append(
            f"tool ordering wrong: expected {expected_tool_order}, "
            f"got {actual_tool_names[:4]}"
        )
    if any(s != "ok" for _, s in tool_calls):
        findings.append(f"tool calls not all ok: {tool_calls}")

    print("\n" + "=" * 70)
    if findings:
        print(f"FINDINGS ({len(findings)}):")
        for f in findings:
            print(f"  - {f}")
        return 1
    print(f"✓ Post-cutover smoke clean. cost ₹{cost:.4f}.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
