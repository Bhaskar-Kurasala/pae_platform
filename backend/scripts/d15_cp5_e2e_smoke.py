"""D15 CP5 — end-to-end smoke for the role-aware student journey.

Drives one seeded python_developer student through five sequential
steps that exercise every CP1-CP4 deliverable end-to-end:

  Step 1 — read_student_role_state: confirms python_developer +
           sequence_order=1 + days_in_role + next_transition.
  Step 2 — read_student_accessible_content (filtered to current role):
           confirms accessible_courses present, completeness flag is
           "partial" (course present, notebooks empty).
  Step 3 — evaluate_student_against_gate(target=data_analyst):
           confirms gate_passable=False with capstone + mock interview
           gaps articulated.
  Step 4 — career_coach with "am I ready to move to data_analyst?":
           confirms response references gap clearly + role identity;
           runtime grounding verifier passes.
  Step 5 — study_planner with "what should I work on this week?":
           confirms plan grounds in accessible content + role identity;
           runtime grounding verifier passes.

Pattern 16 honored at boot (load_agentic_agents + ensure_tools_loaded).
Cumulative cost cap ₹0.50 (D15 prompt budgets ~₹0.30; ceiling leaves
headroom for Critic-retry on either agent path).

Run inside the backend container:

    docker exec -e TEST_PG_DSN=postgresql+asyncpg://postgres:postgres@db:5432/platform \
      pae_platform-backend-1 \
      uv run python scripts/d15_cp5_e2e_smoke.py
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
COST_CAP_INR = 0.50


# ── Step runners ──────────────────────────────────────────────────


async def step1_read_role_state(
    db_factory: Any, student_id: Any
) -> tuple[dict[str, Any], list[str]]:
    """Step 1 — direct tool call (no LLM)."""
    print("\n" + "=" * 72)
    print("STEP 1 — read_student_role_state")
    print("=" * 72)

    from app.agents.primitives import communication as comm_mod
    from app.agents.tools.universal.read_student_role_state import (
        ReadStudentRoleStateInput,
        read_student_role_state,
    )

    findings: list[str] = []
    async with db_factory() as session:
        token = comm_mod._active_session.set(session)
        try:
            out = await read_student_role_state(
                ReadStudentRoleStateInput(student_id=student_id)
            )
        finally:
            comm_mod._active_session.reset(token)

    payload = out.model_dump(mode="json")
    print(json.dumps(payload, indent=2, default=str))

    if not out.found:
        findings.append("S1: found=False; expected True for seeded student")
        return payload, findings

    if out.current_role is None or out.current_role.slug != "python_developer":
        findings.append(
            f"S1: current_role.slug={out.current_role.slug if out.current_role else None!r}; "
            "expected python_developer"
        )
    if out.current_role and out.current_role.sequence_order != 1:
        findings.append(
            f"S1: sequence_order={out.current_role.sequence_order}; expected 1"
        )
    if out.current_role and out.current_role.is_terminal:
        findings.append("S1: is_terminal=True; expected False for python_developer")
    if out.transitions_completed:
        findings.append(
            f"S1: transitions_completed has {len(out.transitions_completed)} "
            "entries; expected 0 for fresh student"
        )
    if out.next_transition is None:
        findings.append("S1: next_transition is None; expected populated")
    else:
        if out.next_transition.target_role_slug != "data_analyst":
            findings.append(
                f"S1: next_transition.target={out.next_transition.target_role_slug!r}; "
                "expected data_analyst"
            )
        if "0.65" not in out.next_transition.gate_summary:
            findings.append(
                f"S1: gate_summary missing 0.65 threshold: "
                f"{out.next_transition.gate_summary!r}"
            )
    if out.days_in_role is None or out.days_in_role < 0:
        findings.append(f"S1: days_in_role={out.days_in_role!r}; expected >= 0")

    return payload, findings


async def step2_read_accessible_content(
    db_factory: Any, student_id: Any
) -> tuple[dict[str, Any], list[str]]:
    print("\n" + "=" * 72)
    print("STEP 2 — read_student_accessible_content (role=python_developer)")
    print("=" * 72)

    from app.agents.primitives import communication as comm_mod
    from app.agents.tools.universal.read_student_accessible_content import (
        ReadStudentAccessibleContentInput,
        read_student_accessible_content,
    )

    findings: list[str] = []
    async with db_factory() as session:
        token = comm_mod._active_session.set(session)
        try:
            out = await read_student_accessible_content(
                ReadStudentAccessibleContentInput(
                    student_id=student_id,
                    role_slug="python_developer",
                )
            )
        finally:
            comm_mod._active_session.reset(token)

    payload = out.model_dump(mode="json")
    print(json.dumps(payload, indent=2, default=str))

    if not out.found:
        findings.append("S2: found=False; expected True (student has entitlement)")
        return payload, findings
    course_slugs = {c.course_slug for c in out.accessible_courses}
    if "python-developer" not in course_slugs:
        findings.append(
            f"S2: accessible_courses lacks python-developer; got {sorted(course_slugs)}"
        )
    if out.accessible_notebooks:
        findings.append(
            f"S2: accessible_notebooks should be empty (lesson_resources empty on dev DB); "
            f"got {len(out.accessible_notebooks)} entries"
        )
    if out.content_schema_completeness not in ("partial", "minimal"):
        findings.append(
            f"S2: content_schema_completeness={out.content_schema_completeness!r}; "
            "expected partial or minimal (no notebooks authored)"
        )

    return payload, findings


async def step3_evaluate_gate(
    db_factory: Any, student_id: Any
) -> tuple[dict[str, Any], list[str]]:
    print("\n" + "=" * 72)
    print("STEP 3 — evaluate_student_against_gate(target=data_analyst)")
    print("=" * 72)

    from app.agents.primitives import communication as comm_mod
    from app.agents.tools.universal.evaluate_student_against_gate import (
        EvaluateStudentAgainstGateInput,
        evaluate_student_against_gate,
    )

    findings: list[str] = []
    async with db_factory() as session:
        token = comm_mod._active_session.set(session)
        try:
            out = await evaluate_student_against_gate(
                EvaluateStudentAgainstGateInput(
                    student_id=student_id,
                    target_role_slug="data_analyst",
                )
            )
        finally:
            comm_mod._active_session.reset(token)

    payload = out.model_dump(mode="json")
    print(json.dumps(payload, indent=2, default=str))

    if out.gate_passable:
        findings.append("S3: gate_passable=True; expected False for fresh student")
    if out.capstone_status.passed:
        findings.append(
            "S3: capstone_status.passed=True; expected False (no submissions)"
        )
    if out.capstone_status.capstones_meeting_threshold != 0:
        findings.append(
            f"S3: capstones_meeting_threshold="
            f"{out.capstone_status.capstones_meeting_threshold}; expected 0"
        )
    if out.mock_interview_status.passed:
        findings.append(
            "S3: mock_interview_status.passed=True; expected False (0 sessions)"
        )
    if out.mock_interview_status.sessions_passed_in_window != 0:
        findings.append(
            f"S3: mock sessions_passed_in_window="
            f"{out.mock_interview_status.sessions_passed_in_window}; expected 0"
        )
    if not out.gap_summary or "capstone" not in out.gap_summary.lower():
        findings.append(
            f"S3: gap_summary lacks capstone language: {out.gap_summary!r}"
        )
    if "mock interview" not in out.gap_summary.lower():
        findings.append(
            f"S3: gap_summary lacks mock interview language: {out.gap_summary!r}"
        )

    return payload, findings


async def step4_career_coach(
    db_factory: Any,
    student_id: Any,
    role_slug: str | None,
) -> tuple[dict[str, Any], list[str], float]:
    print("\n" + "=" * 72)
    print("STEP 4 — career_coach 'am I ready to move to data_analyst?'")
    print("=" * 72)

    from app.agents.agentic_base import CallChain
    from app.agents.primitives.communication import call_agent

    findings: list[str] = []
    payload = {"user_message": "Am I ready to move to data_analyst?"}
    print(f"Payload: {json.dumps(payload)}")

    async with db_factory() as session:
        chain = CallChain.start_root(caller="d15_cp5", user_id=student_id)
        since = datetime.now(UTC) - timedelta(seconds=2)
        start = time.monotonic()
        try:
            result = await call_agent(
                "career_coach",
                payload=payload,
                session=session,
                chain=chain,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            findings.append(
                f"S4: career_coach raised {type(exc).__name__}: {exc} "
                f"after {elapsed:.2f}s"
            )
            return {}, findings, 0.0
        elapsed = time.monotonic() - start
        await session.commit()
    print(f"\nresult.status={result.status}  elapsed={elapsed:.2f}s")

    out = result.output if isinstance(result.output, dict) else {}
    print(f"\noutput keys: {list(out.keys())}")
    print(f"\nheadline: {out.get('headline', '')!r}")
    print(f"\ncurrent_state_assessment:\n  {out.get('current_state_assessment', '')!r}")
    print(f"\nimmediate_concerns: {out.get('immediate_concerns', [])}")
    print(f"\nsuggested_next_action: {out.get('suggested_next_action', '')!r}")

    # Extract cost from agent_actions
    cost = 0.0
    async with db_factory() as db:
        rows = (
            await db.execute(
                sql_text(
                    "SELECT cost_inr FROM agent_actions "
                    "WHERE student_id=:uid AND created_at>=:since"
                ),
                {"uid": student_id, "since": since},
            )
        ).all()
        for r in rows:
            if r[0] is not None:
                cost += float(r[0])
    print(f"\ncost: ₹{cost:.4f}")

    # Verify content
    combined = json.dumps(out).lower()
    if "python_developer" not in combined and "python developer" not in combined:
        findings.append(
            "S4: response does not reference current role (python_developer); "
            "expected role-grounded framing"
        )
    if "data_analyst" not in combined and "data analyst" not in combined:
        findings.append(
            "S4: response does not reference target role (data_analyst); "
            "expected gate gap framing"
        )
    if "0.65" not in combined and "capstone" not in combined:
        findings.append(
            "S4: response lacks capstone or threshold language; expected gate gap"
        )

    # Runtime grounding verifier
    from tests.fixtures.runtime_grounding_verifier import verify_runtime_grounding

    async with db_factory() as db:
        verif = await verify_runtime_grounding(
            db,
            agent_output=out,
            student_id=student_id,
            role_slug=role_slug,
        )
    print(f"\n{verif.summary()}")
    if not verif.passed:
        for f in verif.findings:
            findings.append(
                f"S4: grounding violation '{f.extracted_name}' "
                f"not in accessible set ({f.accessible_set_size} titles)"
            )

    return out, findings, cost


async def step5_study_planner(
    db_factory: Any,
    student_id: Any,
    role_slug: str | None,
) -> tuple[dict[str, Any], list[str], float]:
    print("\n" + "=" * 72)
    print("STEP 5 — study_planner 'what should I work on this week?'")
    print("=" * 72)

    from app.agents.agentic_base import CallChain
    from app.agents.primitives.communication import call_agent

    findings: list[str] = []
    payload = {"user_message": "What should I work on this week?"}

    async with db_factory() as session:
        chain = CallChain.start_root(caller="d15_cp5", user_id=student_id)
        since = datetime.now(UTC) - timedelta(seconds=2)
        start = time.monotonic()
        try:
            result = await call_agent(
                "study_planner",
                payload=payload,
                session=session,
                chain=chain,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            findings.append(
                f"S5: study_planner raised {type(exc).__name__}: {exc} "
                f"after {elapsed:.2f}s"
            )
            return {}, findings, 0.0
        elapsed = time.monotonic() - start
        await session.commit()
    print(f"\nresult.status={result.status}  elapsed={elapsed:.2f}s")

    out = result.output if isinstance(result.output, dict) else {}
    print(f"\noutput keys: {list(out.keys())}")
    print(f"\nmode: {out.get('mode')}")
    print(f"\nanswer: {out.get('answer', '')!r}")
    if out.get("daily_blocks"):
        print(f"\ndaily_blocks ({len(out['daily_blocks'])}):")
        for b in out["daily_blocks"][:8]:
            print(
                f"  {b.get('day_of_week')} {b.get('duration_minutes')}min  "
                f"{b.get('focus_area', '')!r:40} -> "
                f"{b.get('specific_target', '')!r:80}"
            )

    cost = 0.0
    async with db_factory() as db:
        rows = (
            await db.execute(
                sql_text(
                    "SELECT cost_inr FROM agent_actions "
                    "WHERE student_id=:uid AND created_at>=:since"
                ),
                {"uid": student_id, "since": since},
            )
        ).all()
        for r in rows:
            if r[0] is not None:
                cost += float(r[0])
    print(f"\ncost: ₹{cost:.4f}")

    combined = json.dumps(out).lower()
    if "python" not in combined:
        findings.append(
            "S5: plan lacks python language; expected role-grounded plan for "
            "python_developer"
        )

    from tests.fixtures.runtime_grounding_verifier import verify_runtime_grounding

    async with db_factory() as db:
        verif = await verify_runtime_grounding(
            db,
            agent_output=out,
            student_id=student_id,
            role_slug=role_slug,
        )
    print(f"\n{verif.summary()}")
    if not verif.passed:
        for f in verif.findings:
            findings.append(
                f"S5: grounding violation '{f.extracted_name}' "
                f"not in accessible set ({f.accessible_set_size} titles)"
            )

    return out, findings, cost


# ── Main ──────────────────────────────────────────────────────────


async def main() -> int:
    print("=" * 72)
    print("D15 CP5 — end-to-end role-aware student journey")
    print("=" * 72)

    from app.agents._agentic_loader import load_agentic_agents
    from app.agents.primitives.tools import ensure_tools_loaded

    load_agentic_agents()
    ensure_tools_loaded()

    from tests.fixtures.role_state_fixtures import (  # type: ignore
        seed_python_developer_fresh,
    )

    engine = create_async_engine(DB_DSN, future=True)
    db_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with db_factory() as db:
        student = await seed_python_developer_fresh(db)
        await db.commit()
    print(f"\nSeeded python_developer fresh: {student.user_id}")

    all_findings: list[str] = []
    cumulative_cost = 0.0

    _, f1 = await step1_read_role_state(db_factory, student.user_id)
    all_findings.extend(f1)

    _, f2 = await step2_read_accessible_content(db_factory, student.user_id)
    all_findings.extend(f2)

    _, f3 = await step3_evaluate_gate(db_factory, student.user_id)
    all_findings.extend(f3)

    _, f4, c4 = await step4_career_coach(
        db_factory, student.user_id, student.current_role_slug
    )
    cumulative_cost += c4
    all_findings.extend(f4)
    if cumulative_cost > COST_CAP_INR:
        all_findings.append(f"cost cap hit: ₹{cumulative_cost:.4f} > ₹{COST_CAP_INR}")
        return _summarise(all_findings, cumulative_cost)

    _, f5, c5 = await step5_study_planner(
        db_factory, student.user_id, student.current_role_slug
    )
    cumulative_cost += c5
    all_findings.extend(f5)

    return _summarise(all_findings, cumulative_cost)


def _summarise(findings: list[str], cost: float) -> int:
    print("\n" + "=" * 72)
    print("D15 CP5 SUMMARY")
    print("=" * 72)
    print(f"\nCumulative cost: ₹{cost:.4f}  (cap: ₹{COST_CAP_INR:.2f})")
    print(f"\nFindings ({len(findings)}):")
    if not findings:
        print("  (none — all 5 steps verified)")
    else:
        for f in findings:
            print(f"  • {f}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
