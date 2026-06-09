"""D13 CP3 — real-LLM verification for mock_interview multi-turn.

Drives MockInterviewAgent.run() through call_agent() (the production
dispatch primitive) so memory writes / recalls / tool-call audit / cost
tracking all fire end-to-end.

Reuses the d12_cp3_smoke@example.com test user (already entitled from
D12 CP3); refreshes the entitlement window if expired.

Phases:
  1. First-turn behavioral interview (no session_id) → expect "question"
  2. Follow-up turn (with session_id from Phase 1) → expect "evaluation"
  3. Calibration check from measured P50
  4. Optional: third turn that signals wrap → expect "session_summary"
     plus possibly a handoff_request

Run inside the backend container:
    uv run python scripts/d13_cp3_mock_interview_real_llm.py

Cost cap: ₹1.20 cumulative across phases.
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
COST_CAP_INR = 1.20


# ── Setup ─────────────────────────────────────────────────────────


async def setup_user_and_entitlement(db: Any) -> uuid.UUID:
    """Find or create the test user; refresh entitlement window."""
    result = await db.execute(
        sql_text("SELECT id FROM users WHERE email = :email"),
        {"email": TEST_USER_EMAIL},
    )
    row = result.fetchone()
    if row:
        user_id = row.id
        print(f"... reusing user {user_id}")
    else:
        user_id = uuid.uuid4()
        await db.execute(
            sql_text(
                """
                INSERT INTO users
                    (id, email, hashed_password, full_name, role, is_active,
                     is_deleted, created_at, updated_at)
                VALUES
                    (:id, :email, 'fake-bcrypt-hash', 'D13 CP3 Smoke',
                     'student', true, false, now(), now())
                """
            ),
            {"id": user_id, "email": TEST_USER_EMAIL},
        )
        print(f"... created user {user_id}")

    # Find or create the smoke course.
    cr = await db.execute(
        sql_text("SELECT id FROM courses WHERE slug = 'd12-smoke-course' LIMIT 1")
    )
    cr_row = cr.fetchone()
    if cr_row:
        course_id = cr_row.id
    else:
        course_id = uuid.uuid4()
        await db.execute(
            sql_text(
                "INSERT INTO courses "
                "(id, slug, title, description, difficulty, "
                "price_cents, estimated_hours, created_at, updated_at) "
                "VALUES (:id, 'd12-smoke-course', 'D13 CP3 Smoke Course', "
                "'test', 'beginner', 0, 1, now(), now())"
            ),
            {"id": course_id},
        )

    # Refresh entitlement window.
    await db.execute(
        sql_text(
            "UPDATE course_entitlements SET revoked_at = now() "
            "WHERE user_id = :uid AND revoked_at IS NULL"
        ),
        {"uid": user_id},
    )
    await db.execute(
        sql_text(
            """
            INSERT INTO course_entitlements
                (id, user_id, course_id, source, source_ref, granted_at,
                 expires_at, created_at, updated_at)
            VALUES
                (gen_random_uuid(), :uid, :cid, 'admin_grant', NULL, now(),
                 now() + interval '1 hour', now(), now())
            """
        ),
        {"uid": user_id, "cid": course_id},
    )
    await db.commit()
    print("... refreshed admin_grant course_entitlement (1h)")
    return user_id


async def fetch_tool_calls(
    db: Any, user_id: uuid.UUID, since: datetime
) -> list[dict[str, Any]]:
    result = await db.execute(
        sql_text(
            """
            SELECT agent_name, tool_name, status, duration_ms, args,
                   created_at
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
            "created_at": row.created_at,
        }
        for row in result.fetchall()
    ]


async def fetch_agent_actions(
    db: Any, user_id: uuid.UUID, since: datetime
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


# ── Phase runners ─────────────────────────────────────────────────


async def run_phase(
    *,
    label: str,
    user_id: uuid.UUID,
    db_factory: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Run one mock_interview turn via call_agent and capture telemetry."""
    from app.agents.agentic_base import CallChain
    from app.agents.primitives.communication import call_agent

    print(f"\n{'=' * 70}")
    print(f"PHASE: {label}")
    print(f"{'=' * 70}")
    print(f"Input payload: {json.dumps(payload, default=str, indent=2)}")

    # Use a fresh session for the call so the tool-call audit rows go in
    # cleanly. call_agent commits its own audit work via the session it's
    # given.
    async with db_factory() as session:
        chain = CallChain.start_root(caller="d13_cp3_smoke", user_id=user_id)

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
            return {"error": str(exc), "elapsed": elapsed}
        elapsed = time.monotonic() - start
        await session.commit()

    print(f"\nresult.status:    {result.status}")
    print(f"elapsed:          {elapsed:.2f}s")
    out = result.output if isinstance(result.output, dict) else {}
    print(f"output keys:      {list(out.keys())}")
    print(f"  session_id:     {out.get('session_id')}")
    print(f"  mode:           {out.get('mode')}")
    print(f"  turn_kind:      {out.get('turn_kind')}")
    print(f"  handoff_request: {out.get('handoff_request')}")

    # Surface specific sub-object based on turn_kind.
    tk = out.get("turn_kind")
    if tk == "question" and out.get("question"):
        q = out["question"]
        print(f"  question_text:  {q.get('question_text', '')[:200]!r}")
        print(f"  rubric_summary: {q.get('rubric_summary', '')[:120]!r}")
        print(f"  expected_min:   {q.get('expected_minutes')}")
    elif tk == "evaluation" and out.get("evaluation"):
        e = out["evaluation"]
        print(f"  score_0_to_10:  {e.get('score_0_to_10')}")
        print(f"  strengths:      {e.get('strengths')}")
        print(f"  gaps:           {e.get('gaps')}")
        print(f"  follow_up:      {e.get('follow_up_question')}")
    elif tk == "feedback" and out.get("feedback"):
        f = out["feedback"]
        print(f"  overall:        {f.get('overall_assessment', '')[:200]!r}")
        print(f"  practice:       {f.get('one_thing_to_practice', '')[:150]!r}")
    elif tk == "session_summary" and out.get("session_summary"):
        s = out["session_summary"]
        print(f"  overall_score:  {s.get('overall_score_0_to_100')}")
        print(f"  headline:       {s.get('headline', '')!r}")
        print(f"  strengths:      {s.get('strengths')}")
        print(f"  weaknesses:     {s.get('weaknesses')}")
        print(f"  next_action:    {s.get('suggested_next_action', '')[:150]!r}")

    print(f"\nanswer (first 300 chars):\n  {(out.get('answer') or '')[:300]!r}")

    # Telemetry: tool calls + agent_actions
    async with db_factory() as db:
        tool_calls = await fetch_tool_calls(db, user_id, since)
        actions = await fetch_agent_actions(db, user_id, since)

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
    print(f"\nphase cost: ₹{cost:.4f}")

    return {
        "elapsed": elapsed,
        "output": out,
        "tool_calls": tool_calls,
        "actions": actions,
        "cost": cost,
    }


# ── Main ──────────────────────────────────────────────────────────


async def main() -> int:
    print("=" * 70)
    print("D13 CP3 — mock_interview real-LLM multi-turn verification")
    print("=" * 70)

    engine = create_async_engine(DB_DSN, future=True)
    db_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Load agentic agents so the registry is populated before dispatch.
    from app.agents._agentic_loader import load_agentic_agents
    from app.agents.primitives.tools import ensure_tools_loaded

    load_agentic_agents()
    ensure_tools_loaded()

    # Setup
    async with db_factory() as db:
        user_id = await setup_user_and_entitlement(db)

    cumulative_cost = 0.0
    findings: list[str] = []

    # ── Phase 1: First turn ───────────────────────────────────────
    p1 = await run_phase(
        label="1 — First-turn behavioral interview (no session_id)",
        user_id=user_id,
        db_factory=db_factory,
        payload={
            "mode": "behavioral",
            "user_message": (
                "I'd like to practice for a senior GenAI engineering interview"
            ),
            "target_role": "Senior GenAI Engineer",
        },
    )

    if "error" in p1:
        print("\n!! Phase 1 errored — aborting CP3.")
        return 1

    cumulative_cost += p1["cost"]
    print(f"\nCumulative cost: ₹{cumulative_cost:.4f} / cap ₹{COST_CAP_INR:.2f}")

    # Phase 1 invariant checks
    p1_out = p1["output"]
    if p1_out.get("mode") != "behavioral":
        findings.append(
            f"Phase 1: mode drift — got {p1_out.get('mode')!r}, expected 'behavioral'"
        )
    if p1_out.get("turn_kind") not in ("question", "session_summary"):
        findings.append(
            f"Phase 1: unexpected turn_kind {p1_out.get('turn_kind')!r} on first turn"
        )
    if p1_out.get("turn_kind") != "session_summary" and p1_out.get("handoff_request") is not None:
        findings.append(
            "Phase 1: handoff_request non-null on non-summary turn — D-2 violation"
        )
    if p1["elapsed"] > 36.0:
        findings.append(
            f"Phase 1: elapsed {p1['elapsed']:.2f}s exceeds 36s budget"
        )

    p1_session_id = p1_out.get("session_id")
    if not p1_session_id:
        print("\n!! No session_id in Phase 1 output — cannot run Phase 2.")
        return 1
    try:
        uuid.UUID(p1_session_id)
    except ValueError:
        findings.append(f"Phase 1: session_id {p1_session_id!r} is not a valid UUID")

    # Verify tool-call ordering: at least 2 memory_recall before 1 memory_write.
    p1_recalls = [t for t in p1["tool_calls"] if t["tool_name"] == "memory_recall"]
    p1_writes = [t for t in p1["tool_calls"] if t["tool_name"] == "memory_write"]
    if len(p1_recalls) < 2:
        findings.append(
            f"Phase 1: expected >=2 memory_recall, got {len(p1_recalls)}"
        )
    if len(p1_writes) < 1:
        findings.append(
            f"Phase 1: expected >=1 memory_write, got {len(p1_writes)}"
        )
    if p1_recalls and p1_writes:
        # Recall should precede write in time.
        last_recall = max(t["created_at"] for t in p1_recalls)
        first_write = min(t["created_at"] for t in p1_writes)
        if last_recall > first_write:
            findings.append(
                "Phase 1: tool-call ordering — write fired before recall"
            )

    if cumulative_cost > COST_CAP_INR:
        print(f"\n!! Cost cap hit after Phase 1 (₹{cumulative_cost:.4f}). Aborting.")
        return _summarise(findings, cumulative_cost, [p1])

    # ── Phase 2: Follow-up turn ───────────────────────────────────
    # Construct a representative answer to whatever was asked in Phase 1.
    # Make the answer concrete enough to give the LLM something to evaluate.
    p1_question_text = (
        p1_out.get("question", {}).get("question_text", "")
        if isinstance(p1_out.get("question"), dict)
        else ""
    )
    candidate_answer = (
        "Last quarter at my current company we hit a production incident "
        "where a RAG retrieval pipeline started returning irrelevant "
        "context for medical-domain queries. I was on call. Situation: "
        "we had p99 hallucination complaints from internal QA. Task: I "
        "owned triaging the cause within 4 hours. Action: I bisected "
        "between the embedding model swap two days prior and the index "
        "rebuild that morning, and found that the rebuild had been run "
        "with stale chunk metadata. Result: I rolled back the index, "
        "shipped a checksum gate on the rebuild script, and p99 "
        "hallucination rate dropped from 18% to under 2% within 24h."
    )

    p2 = await run_phase(
        label="2 — Follow-up turn (echoing session_id from Phase 1)",
        user_id=user_id,
        db_factory=db_factory,
        payload={
            "mode": "behavioral",
            "session_id": p1_session_id,
            "user_message": candidate_answer,
        },
    )

    if "error" in p2:
        print("\n!! Phase 2 errored — surfacing partial findings.")
        return _summarise(findings + [f"Phase 2 errored: {p2['error']}"], cumulative_cost, [p1, p2])

    cumulative_cost += p2["cost"]
    print(f"\nCumulative cost: ₹{cumulative_cost:.4f} / cap ₹{COST_CAP_INR:.2f}")

    # Phase 2 invariant checks
    p2_out = p2["output"]
    if p2_out.get("session_id") != p1_session_id:
        findings.append(
            f"Phase 2: D-1 ROUNDTRIP VIOLATION — session_id "
            f"{p2_out.get('session_id')!r} != Phase 1's {p1_session_id!r}"
        )
    if p2_out.get("mode") != "behavioral":
        findings.append(
            f"Phase 2: mode drift — got {p2_out.get('mode')!r}"
        )
    if p2_out.get("turn_kind") not in ("evaluation", "feedback", "question"):
        findings.append(
            f"Phase 2: unexpected turn_kind {p2_out.get('turn_kind')!r} "
            "(expected evaluation, feedback, or follow-up question)"
        )
    if p2_out.get("turn_kind") != "session_summary" and p2_out.get("handoff_request") is not None:
        findings.append(
            "Phase 2: handoff_request non-null on non-summary turn"
        )
    if p2["elapsed"] > 36.0:
        findings.append(f"Phase 2: elapsed {p2['elapsed']:.2f}s exceeds 36s")

    # Multi-turn coherence: did the recall return Phase 1's turn log?
    p2_session_recalls = [
        t for t in p2["tool_calls"]
        if t["tool_name"] == "memory_recall"
        and t["args_query"]
        and t["args_query"].startswith(f"mock_interview:session:{p1_session_id}")
    ]
    if not p2_session_recalls:
        findings.append(
            "Phase 2: no memory_recall query for "
            f"mock_interview:session:{p1_session_id}"
        )

    if cumulative_cost > COST_CAP_INR:
        print(f"\n!! Cost cap hit after Phase 2 (₹{cumulative_cost:.4f}).")
        print("   Skipping optional Phase 4.")
        return _summarise(findings, cumulative_cost, [p1, p2])

    # ── Phase 3: Calibration check ────────────────────────────────
    print("\n" + "=" * 70)
    print("PHASE 3 — Calibration")
    print("=" * 70)
    elapsed_max = max(p1["elapsed"], p2["elapsed"])
    elapsed_p50 = (p1["elapsed"] + p2["elapsed"]) / 2
    print(f"Phase 1 elapsed: {p1['elapsed']:.2f}s")
    print(f"Phase 2 elapsed: {p2['elapsed']:.2f}s")
    print(f"P50 (mean of 2 turns):    {elapsed_p50:.2f}s")
    print(f"Max:                      {elapsed_max:.2f}s")
    print(f"Current capability budget: 36s (typical_latency_ms=12000 × 3)")
    if elapsed_max <= 36.0:
        print("Calibration: WITHIN BUDGET — no recalibration needed.")
    else:
        suggested = int((elapsed_max * 1000) / 3) + 1
        print(f"Calibration: OVER BUDGET — suggest typical_latency_ms={suggested}")
        findings.append(
            f"Calibration: typical_latency_ms recommended bump to {suggested}"
        )

    # ── Phase 4: Optional session_summary turn ────────────────────
    remaining_budget = COST_CAP_INR - cumulative_cost
    if remaining_budget < 0.40:
        print(f"\nPhase 4 skipped — only ₹{remaining_budget:.4f} budget left.")
        return _summarise(findings, cumulative_cost, [p1, p2])

    p4 = await run_phase(
        label="4 — Wrap-up turn (testing session_summary + handoff shape)",
        user_id=user_id,
        db_factory=db_factory,
        payload={
            "mode": "behavioral",
            "session_id": p1_session_id,
            "user_message": (
                "I think we can wrap up here. What's your overall "
                "assessment of where I am, and what should I work on?"
            ),
        },
    )

    if "error" in p4:
        findings.append(f"Phase 4 errored: {p4['error']}")
        return _summarise(findings, cumulative_cost, [p1, p2, p4])

    cumulative_cost += p4["cost"]

    p4_out = p4["output"]
    if p4_out.get("session_id") != p1_session_id:
        findings.append(
            f"Phase 4: session_id mismatch — {p4_out.get('session_id')!r}"
        )
    if p4_out.get("mode") != "behavioral":
        findings.append(f"Phase 4: mode drift — {p4_out.get('mode')!r}")

    # If turn_kind is session_summary AND handoff_request is non-null,
    # validate it against the Supervisor's HandoffRequest schema.
    if p4_out.get("turn_kind") == "session_summary":
        hr = p4_out.get("handoff_request")
        if hr is not None:
            try:
                from app.schemas.supervisor import HandoffRequest

                HandoffRequest.model_validate(hr)
                print(
                    "\nHandoffRequest shape: ✓ validates against "
                    "app.schemas.supervisor.HandoffRequest"
                )
                if hr.get("target_agent") not in ("senior_engineer", "career_coach"):
                    findings.append(
                        f"Phase 4: handoff target {hr.get('target_agent')!r} "
                        "not in {senior_engineer, career_coach}"
                    )
                if hr.get("handoff_type") != "suggested":
                    findings.append(
                        f"Phase 4: handoff_type {hr.get('handoff_type')!r} "
                        "should be 'suggested' (D-2 disallows mandatory in D13)"
                    )
            except Exception as exc:  # noqa: BLE001
                findings.append(
                    f"Phase 4: HandoffRequest shape mismatch — "
                    f"{type(exc).__name__}: {exc}"
                )
        else:
            print("\nNo handoff_request emitted on session_summary turn (allowed).")
    elif p4_out.get("handoff_request") is not None:
        findings.append(
            "Phase 4: handoff_request non-null without session_summary turn_kind"
        )

    return _summarise(findings, cumulative_cost, [p1, p2, p4])


def _summarise(
    findings: list[str], cumulative_cost: float, phases: list[dict[str, Any]]
) -> int:
    print("\n" + "=" * 70)
    print("CP3 SUMMARY")
    print("=" * 70)
    print(f"Phases run:        {len(phases)}")
    print(f"Cumulative cost:   ₹{cumulative_cost:.4f} / cap ₹{COST_CAP_INR:.2f}")
    if findings:
        print(f"\nFindings ({len(findings)}):")
        for f in findings:
            print(f"  - {f}")
        return 1
    print("\nNo findings. CP3 verification clean.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
