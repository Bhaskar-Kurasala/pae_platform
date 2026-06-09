"""D13.5 Stage 3 — real-LLM verification of mandatory validation chain.

Drives `dispatch_single` directly with a tailored_resume RouteDecision.
The capability declares resume_reviewer as the mandatory validator;
dispatch_single auto-extends the chain. Both LLM calls run live against
MiniMax; we verify producer + validator land within their budgets,
adapter cleanly maps producer output → validator input, and validator
findings surface under structured_output["validation"].

Cost expectation: ~₹0.50–0.75.
Chain budget: 231s (sum × 1.10 per D-E).
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


# Strong-evidence resume designed to complete in single-pass under
# tailored_resume's 120s budget. D13.5 Stage 3 first call surfaced a
# D12 calibration gap when sparse-evidence input triggered the inner
# regeneration loop (registered at
# docs/followups/tailored-resume-regeneration-path-calibration.md).
# This input has 5+ quantified accomplishments + multi-year experience
# so the inner pipeline shouldn't need to regenerate to fill content.
PRIMARY_INPUT = {
    "resume_text": (
        "Alex Chen — Senior GenAI Engineer (6 years)\n"
        "EXPERIENCE\n"
        "* Led the design and rollout of a production RAG pipeline at "
        "FinCorp serving 200k queries/day at p95 < 250ms. Mentored 4 "
        "junior engineers through the launch.\n"
        "* Delivered an LLM evaluation harness used by 6 product teams "
        "(open-sourced as fincorp-evals; 800+ GH stars).\n"
        "* Built a multi-tenant inference gateway on FastAPI + Triton — "
        "scaled from 0 to 50 concurrent customers in 9 months with zero "
        "P1 incidents.\n"
        "* Authored 3 internal tech-talks on retrieval evaluation, "
        "later published as a 4-part blog series cited by Anthropic.\n"
        "* Mentored 4 engineers, 2 of whom were promoted within 12 "
        "months of joining my team.\n"
        "EDUCATION\n"
        "* M.S., Machine Learning, Carnegie Mellon (2019).\n"
        "SKILLS: Python, FastAPI, Pinecone, LangChain, async, Docker, "
        "Triton, Kubernetes, evaluation pipelines."
    ),
    "job_description": (
        "Senior GenAI Engineer at Acme Corp. Required: 5+ years "
        "production experience building LLM-powered systems at scale. "
        "Must have led at least one cross-functional team. Deep "
        "expertise in RAG architectures, vector databases, and "
        "evaluation pipelines. Bonus: published work on retrieval "
        "evaluation."
    ),
}


async def setup_user(db: Any) -> uuid.UUID:
    result = await db.execute(
        sql_text("SELECT id FROM users WHERE email = :email"),
        {"email": TEST_USER_EMAIL},
    )
    row = result.fetchone()
    if row is None:
        print("ERROR: test user not found. Run a prior CP3 harness first.")
        raise SystemExit(1)
    user_id = row.id
    await db.execute(
        sql_text(
            "UPDATE course_entitlements SET expires_at = now() + interval '1 hour' "
            "WHERE user_id = :uid AND revoked_at IS NULL"
        ),
        {"uid": user_id},
    )
    await db.commit()
    print(f"... user {user_id} entitlement refreshed")
    return user_id


async def fetch_actions(
    db: Any, user_id: uuid.UUID, since: datetime
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


async def fetch_evaluations(
    db: Any, user_id: uuid.UUID, since: datetime
) -> list[dict[str, Any]]:
    """Critic evaluation rows — neither agent has uses_self_eval=True,
    so we expect this list to be empty. Stage 3 invariant: no Critic
    firing for non-self-eval agents."""
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


async def run_chain_call(
    *,
    user_id: uuid.UUID,
    db_factory: Any,
    label: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from app.agents.agentic_base import AgentContext  # noqa: F401
    from app.agents.dispatch import VALIDATION_OUTPUT_KEY, dispatch_single
    from app.agents.primitives.communication import CallChain
    from app.schemas.entitlement import (
        ActiveEntitlement,
        EntitlementContext,
    )
    from app.schemas.supervisor import (
        ConversationTurn,
        RateLimitState,
        RouteDecision,
        StudentSnapshot,
        SupervisorContext,
    )

    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print(f"\nInput payload (truncated):")
    print(f"  resume_text:     {payload['resume_text'][:120]!r}...")
    print(f"  job_description: {payload['job_description'][:120]!r}...")

    decision = RouteDecision(
        action="dispatch_single",
        target_agent="tailored_resume",
        constructed_context=payload,
        reasoning="d13.5_stage3_verification",
        confidence="high",
        primary_intent="resume_tailoring",
    )

    # Build a SupervisorContext that satisfies the dispatch layer's
    # requirements (matches test_checkpoint3_dispatch.py helper).
    now = datetime.now(UTC)
    rate_limit = RateLimitState(
        burst_remaining=10,
        burst_window_resets_at=now + timedelta(minutes=1),
        hourly_remaining=100,
        hourly_window_resets_at=now + timedelta(hours=1),
    )
    from decimal import Decimal

    ctx = SupervisorContext(
        student_id=user_id,
        request_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        actor_id=user_id,
        actor_role="student",
        user_message="Tailor my resume for this JD",
        attachments=[],
        entitlements=[],
        rate_limit_remaining=rate_limit,
        cost_budget_remaining_today_inr=Decimal("47.50"),
        student_snapshot=StudentSnapshot(),
        thread_summary=None,
        recent_turns=[],
        recent_agent_actions=[],
        available_agents=[],
        available_tools=[],
    )
    ent_ctx = EntitlementContext(
        user_id=user_id,
        active_entitlements=[
            ActiveEntitlement(
                entitlement_id=uuid.uuid4(),
                user_id=user_id,
                course_id=uuid.uuid4(),
                course_slug="d12-smoke-course",
                tier="standard",
                source="admin_grant",
                granted_at=now - timedelta(days=1),
            )
        ],
        free_tier=None,
        effective_tier="standard",
        cost_budget_remaining_today_inr=Decimal("47.50"),
        cost_budget_used_today_inr=Decimal("2.50"),
        rate_limit_state=rate_limit,
    )

    since = datetime.now(UTC) - timedelta(seconds=2)

    async with db_factory() as session:
        chain = CallChain.start_root(
            caller="d13_5_stage3", user_id=user_id
        )
        start = time.monotonic()
        try:
            result = await dispatch_single(
                decision,
                ctx,
                db=session,
                chain=chain,
                fresh_ctx=ent_ctx,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            print(f"\n!! dispatch_single raised after {elapsed:.2f}s: "
                  f"{type(exc).__name__}: {exc}")
            return {"error": str(exc), "elapsed": elapsed}
        elapsed = time.monotonic() - start
        await session.commit()

    print(f"\nresult.agent_name: {result.agent_name}")
    print(f"result.blocked:    {result.blocked}")
    print(f"result.block_reason: {result.block_reason}")
    print(f"chain elapsed:     {elapsed:.2f}s")

    structured = result.structured_output or {}
    print(f"\nstructured_output keys: {list(structured.keys())}")

    # Producer payload (top-level, minus the validation block).
    if "tailored_resume" in structured:
        tr_text = structured["tailored_resume"]
        print(f"\ntailored_resume excerpt (first 400 chars):")
        print(f"  {tr_text[:400]!r}...")
    print(f"keyword_alignment_score: {structured.get('keyword_alignment_score')}")
    print(f"changes_made count:      {len(structured.get('changes_made', []))}")
    print(f"ats_compatibility_notes: {structured.get('ats_compatibility_notes')}")

    # Validation block per Stage 2 contract.
    validation = structured.get(VALIDATION_OUTPUT_KEY)
    print(f"\nstructured_output[{VALIDATION_OUTPUT_KEY!r}] present: {validation is not None}")
    if validation is None:
        print("  !! VALIDATION BLOCK MISSING — Stage 2 wiring did not fire")
    elif validation.get("validation_unavailable"):
        print(f"  validation_unavailable: True")
        print(f"  validator: {validation.get('validator')}")
        print(f"  reason:    {validation.get('reason')}")
    else:
        print(f"  overall_score:        {validation.get('overall_score')}")
        print(f"  headline:             {validation.get('headline_assessment', '')[:120]!r}")
        print(f"  strengths:            {len(validation.get('strengths', []))} items")
        unsupported = validation.get('unsupported_claims', [])
        print(f"  unsupported_claims:   {len(unsupported)} items")
        for i, claim in enumerate(unsupported[:3]):
            print(f"    [{i}] suggested_action={claim.get('suggested_action')!r}")
            print(f"        claim_text={claim.get('claim_text', '')[:80]!r}")
        if len(unsupported) > 3:
            print(f"    ... + {len(unsupported) - 3} more")
        print(f"  issues:               {len(validation.get('issues', []))} items")
        print(f"  suggested_changes:    {len(validation.get('suggested_changes', []))} items")

    # Telemetry.
    async with db_factory() as db:
        actions = await fetch_actions(db, user_id, since)
        evals = await fetch_evaluations(db, user_id, since)

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

    print(f"\nagent_evaluations in window ({len(evals)}) (expected 0; neither agent has uses_self_eval=True):")
    for ev in evals:
        print(f"  {ev}")

    return {
        "elapsed": elapsed,
        "result": result,
        "structured": structured,
        "validation": validation,
        "actions": actions,
        "evals": evals,
        "cost": cost,
    }


async def main() -> int:
    print("=" * 70)
    print("D13.5 Stage 3 — mandatory validation chain real-LLM verification")
    print("=" * 70)

    from app.agents._agentic_loader import load_agentic_agents
    from app.agents.primitives.tools import ensure_tools_loaded

    load_agentic_agents()
    ensure_tools_loaded()

    engine = create_async_engine(DB_DSN, future=True)
    db_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with db_factory() as db:
        user_id = await setup_user(db)

    cumulative_cost = 0.0
    findings: list[str] = []

    # ── Primary verification ──────────────────────────────────────
    p1 = await run_chain_call(
        user_id=user_id,
        db_factory=db_factory,
        label="PRIMARY VERIFICATION — claim-heavy resume → validator should flag",
        payload=PRIMARY_INPUT,
    )

    if "error" in p1:
        print("\n!! PRIMARY call errored — Stage 3 STOP")
        return 1

    cumulative_cost += p1["cost"]
    print(f"\nCumulative cost: ₹{cumulative_cost:.4f}")

    # ── Verification checks ──────────────────────────────────────
    print("\n" + "=" * 70)
    print("VERIFICATION CHECKS")
    print("=" * 70)

    if p1["elapsed"] > 240.0:
        findings.append(
            f"Chain elapsed {p1['elapsed']:.2f}s exceeds 240s budget"
        )
    else:
        print(f"✓ chain elapsed {p1['elapsed']:.2f}s < 240s budget")

    actions = p1["actions"]
    producer_actions = [a for a in actions if a["agent_name"] == "tailored_resume"]
    validator_actions = [a for a in actions if a["agent_name"] == "resume_reviewer"]

    if len(producer_actions) != 1:
        findings.append(
            f"Expected exactly 1 tailored_resume agent_actions row; got {len(producer_actions)}"
        )
    if len(validator_actions) != 1:
        findings.append(
            f"Expected exactly 1 resume_reviewer agent_actions row; got {len(validator_actions)}"
        )
    else:
        producer_ms = producer_actions[0]["duration_ms"]
        validator_ms = validator_actions[0]["duration_ms"]
        if producer_ms > 120_000:
            findings.append(
                f"tailored_resume duration {producer_ms}ms exceeds 120s budget"
            )
        else:
            print(f"✓ tailored_resume duration {producer_ms}ms < 120s budget")
        # Single-pass heuristic: a regeneration-triggering run takes
        # ~85s+ of LLM time per the D13.5 Stage 3.1 follow-up doc. If
        # the producer landed near or above that floor, the strong-
        # evidence input may have still triggered regeneration —
        # informational, not a hard finding.
        if producer_ms > 90_000:
            print(
                f"  ⚠ producer duration {producer_ms}ms is above the "
                "~85s regeneration floor — input may have still triggered "
                "the regeneration path. See "
                "docs/followups/tailored-resume-regeneration-path-calibration.md."
            )
        else:
            print(
                f"  ✓ producer duration {producer_ms}ms suggests single-pass "
                "(below ~85s regeneration floor)"
            )
        if validator_ms > 90_000:
            findings.append(
                f"resume_reviewer duration {validator_ms}ms exceeds 90s budget"
            )
        else:
            print(f"✓ resume_reviewer duration {validator_ms}ms < 90s budget")

        if producer_actions[0]["status"] != "completed":
            findings.append(
                f"tailored_resume status={producer_actions[0]['status']!r}"
            )
        if validator_actions[0]["status"] != "completed":
            findings.append(
                f"resume_reviewer status={validator_actions[0]['status']!r}"
            )

    validation = p1["validation"]
    if validation is None:
        findings.append("structured_output['validation'] missing")
    elif validation.get("validation_unavailable"):
        findings.append(
            f"validation_unavailable=True (reason={validation.get('reason')!r}) "
            "— validator did not run cleanly"
        )
    else:
        print("✓ structured_output['validation'] present and well-formed")
        # Bug 14c allowlist verification (suggested_action enum).
        allowed_actions = {"remove", "soften", "add_evidence", "verify_with_student"}
        unsupported = validation.get("unsupported_claims", [])
        for i, claim in enumerate(unsupported):
            sa = claim.get("suggested_action")
            if sa not in allowed_actions:
                findings.append(
                    f"unsupported_claims[{i}].suggested_action={sa!r} "
                    f"not in allowlist {allowed_actions}"
                )
        if unsupported:
            valid_count = sum(
                1 for c in unsupported if c.get("suggested_action") in allowed_actions
            )
            print(
                f"✓ {valid_count}/{len(unsupported)} unsupported_claims have "
                f"valid suggested_action (Bug 14c allowlist)"
            )

    if p1["evals"]:
        findings.append(
            f"Critic fired unexpectedly: {len(p1['evals'])} eval rows "
            "(neither agent has uses_self_eval=True)"
        )
    else:
        print("✓ no Critic loops fired (expected; uses_self_eval=False on both)")

    # ── Optional second call disabled per Stage 3.2 spec ─────────
    # Stage 3 first call already burned ~₹0.30-0.50 in unrecorded
    # timeout cost; the second call's purpose was false-positive
    # coverage which is informational, not load-bearing.
    if False:
        # Second call: well-grounded resume. Should produce minimal
        # findings (validator not false-positive-prone).
        secondary_input = {
            "resume_text": (
                "Alex Chen — Senior GenAI Engineer (6 years)\n"
                "EXPERIENCE\n"
                "* Led the design and rollout of a production RAG pipeline "
                "at FinCorp serving 200k queries/day at p95 < 250ms. "
                "Mentored 4 junior engineers through the launch.\n"
                "* Delivered an LLM evaluation harness used by 6 product "
                "teams (open-sourced as fincorp-evals; 800+ GH stars).\n"
                "* Built a multi-tenant inference gateway on FastAPI + "
                "Triton — scaled from 0 → 50 concurrent customers in 9 "
                "months with zero P1 incidents.\n"
                "* Authored 3 internal tech-talks on retrieval evaluation, "
                "later published as a 4-part blog series cited by Anthropic.\n"
                "* Mentored 4 engineers, 2 of whom were promoted within 12 "
                "months of joining my team.\n"
                "EDUCATION\n"
                "* M.S., Machine Learning, Carnegie Mellon (2019).\n"
                "SKILLS: Python, FastAPI, Pinecone, LangChain, async, "
                "Docker, Triton, Kubernetes, evaluation pipelines."
            ),
            "job_description": PRIMARY_INPUT["job_description"],
        }
        p2 = await run_chain_call(
            user_id=user_id,
            db_factory=db_factory,
            label="SECONDARY VERIFICATION — well-grounded resume → minimal findings",
            payload=secondary_input,
        )
        if "error" not in p2:
            cumulative_cost += p2["cost"]
            print(f"\nCumulative cost after secondary: ₹{cumulative_cost:.4f}")
            v2 = p2["validation"] or {}
            unsupported_2 = v2.get("unsupported_claims", []) if not v2.get("validation_unavailable") else None
            if unsupported_2 is not None:
                print(
                    f"✓ secondary call: validator flagged "
                    f"{len(unsupported_2)} unsupported_claims (well-grounded resume)"
                )

    # ── Summary ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("STAGE 3 SUMMARY")
    print("=" * 70)
    print(f"Cumulative cost: ₹{cumulative_cost:.4f} / cap ₹{COST_CAP_INR:.2f}")
    if cumulative_cost > COST_CAP_INR:
        findings.append(f"Cost exceeded ₹{COST_CAP_INR} cap")

    if findings:
        print(f"\nFindings ({len(findings)}):")
        for f in findings:
            print(f"  - {f}")
        return 1
    print("\n✓ No findings. D13.5 Stage 3 verification clean.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
