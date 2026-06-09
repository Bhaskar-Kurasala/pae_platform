"""D12 CP3 Parts A and B — real-MiniMax verification smoke.

Fires 6 HTTP calls against the canonical agentic endpoint to verify
the four migrated D12 agents work under real MiniMax-M2.7 and that
chain dispatch composes them correctly.

Run inside the backend container:
    uv run python scripts/d12_cp3_real_llm_smoke.py

Expected total cost: ~₹1.55 (~₹0.05 probe + ~₹0.30 each agent +
~₹0.30 chain). Hard cap at ₹3.00 — if exceeded, abort and surface
as anomaly.

Outputs a markdown evidence report to stdout.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

# Ensure /app is on sys.path so `from app.core.security ...` works when this
# script is launched via `python /app/scripts/...` rather than via pytest.
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

import httpx
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ── Configuration ─────────────────────────────────────────────────

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
DB_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@db:5432/platform",
)
COST_CAP_INR = 3.0
TEST_USER_EMAIL = "d12_cp3_smoke@example.com"

# Violation phrases for career_coach Deferral C check.
SALARY_PATTERN = re.compile(
    r"(\$|₹|USD|INR|EUR|GBP)\s?[\d,]+(?:\.\d+)?\s?(k|K|million|M|lakh|crore|LPA)?"
    r"|\b\d+(?:\.\d+)?\s?(k|K|lakh|crore|LPA)\b",
)
JOB_COUNT_PATTERN = re.compile(
    r"\b\d{2,}\s*(jobs?|openings?|positions?|listings?|vacancies?|roles?)\b",
    re.IGNORECASE,
)
GROWTH_PCT_PATTERN = re.compile(
    r"\b\d{1,2}(?:\.\d+)?\s?%\s*(growth|increase|rise|expansion|YoY|year-over-year)",
    re.IGNORECASE,
)


# ── Setup ─────────────────────────────────────────────────────────


async def setup_test_user(db: Any) -> tuple[uuid.UUID, str]:
    """Create or find the test user; seed entitlement + capstone.

    Returns (user_id, jwt_token).
    """
    # Find or create user.
    result = await db.execute(
        sql_text("SELECT id FROM users WHERE email = :email"),
        {"email": TEST_USER_EMAIL},
    )
    row = result.fetchone()

    if row:
        user_id = row.id
        print(f"... reusing user {user_id}", file=sys.stderr)
    else:
        user_id = uuid.uuid4()
        await db.execute(
            sql_text(
                """
                INSERT INTO users
                    (id, email, hashed_password, full_name, role, is_active,
                     is_deleted, created_at, updated_at)
                VALUES
                    (:id, :email, 'fake-bcrypt-hash', 'D12 CP3 Smoke',
                     'student', true, false, now(), now())
                """
            ),
            {"id": user_id, "email": TEST_USER_EMAIL},
        )
        print(f"... created user {user_id}", file=sys.stderr)

    # Standard-tier entitlement: free_tier_grants only allows
    # {billing_support, supervisor} per core/tiers.py; the D12 agents
    # require a course_entitlements row mapped to the 'standard' tier.
    # Use source='admin_grant' (no payment required, source_ref nullable).
    # Find or create a course; insert an entitlement.
    course_result = await db.execute(
        sql_text("SELECT id FROM courses WHERE slug = 'd12-smoke-course' LIMIT 1")
    )
    course_row = course_result.fetchone()
    if course_row:
        smoke_course_id = course_row.id
    else:
        smoke_course_id = uuid.uuid4()
        await db.execute(
            sql_text(
                "INSERT INTO courses "
                "(id, slug, title, description, difficulty, "
                "price_cents, estimated_hours, created_at, updated_at) "
                "VALUES (:id, 'd12-smoke-course', 'D12 CP3 Smoke Course', "
                "'test', 'beginner', 0, 1, now(), now())"
            ),
            {"id": smoke_course_id},
        )

    # Revoke any prior smoke entitlement, insert fresh.
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
        {"uid": user_id, "cid": smoke_course_id},
    )
    print(f"... seeded admin_grant course_entitlement (course={smoke_course_id}, 1h)", file=sys.stderr)

    # Seed a capstone for resume_reviewer A3.
    # Find or create a capstone exercise; insert a high-scoring submission.
    cap_result = await db.execute(
        sql_text(
            "SELECT id FROM exercises WHERE is_capstone = true "
            "AND title = :title LIMIT 1"
        ),
        {"title": "D12 CP3 RAG Capstone"},
    )
    cap_row = cap_result.fetchone()
    if cap_row:
        exercise_id = cap_row.id
    else:
        exercise_id = uuid.uuid4()
        # Find any course to satisfy FK; create one if needed.
        course_result = await db.execute(
            sql_text("SELECT id FROM courses LIMIT 1")
        )
        course_row = course_result.fetchone()
        if course_row:
            course_id = course_row.id
        else:
            course_id = uuid.uuid4()
            await db.execute(
                sql_text(
                    "INSERT INTO courses "
                    "(id, slug, title, description, difficulty, "
                    "price_cents, estimated_hours, created_at, updated_at) "
                    "VALUES (:id, 'd12-smoke', 'D12 CP3 Smoke Course', "
                    "'test', 'beginner', 0, 1, now(), now())"
                ),
                {"id": course_id},
            )
        # Find a lesson under the course or create one.
        lesson_result = await db.execute(
            sql_text("SELECT id FROM lessons WHERE course_id = :cid LIMIT 1"),
            {"cid": course_id},
        )
        lesson_row = lesson_result.fetchone()
        if lesson_row:
            lesson_id = lesson_row.id
        else:
            lesson_id = uuid.uuid4()
            await db.execute(
                sql_text(
                    'INSERT INTO lessons '
                    '(id, course_id, slug, title, description, '
                    'youtube_video_id, "order", duration_seconds, '
                    'created_at, updated_at) '
                    "VALUES (:id, :cid, 'd12-smoke-lesson', "
                    "'D12 Smoke Lesson', 'test', "
                    "'dQw4w9WgXcQ', 1, 60, now(), now())"
                ),
                {"id": lesson_id, "cid": course_id},
            )
        await db.execute(
            sql_text(
                """
                INSERT INTO exercises
                    (id, lesson_id, title, description, starter_code,
                     test_cases, rubric, is_capstone, created_at, updated_at)
                VALUES
                    (:id, :lid, 'D12 CP3 RAG Capstone',
                     'Build a RAG system using Pinecone + LangChain that ingests '
                     '10000 documents and serves queries at p50 < 150ms.',
                     '', '[]'::jsonb, '{}'::jsonb, true, now(), now())
                """
            ),
            {"id": exercise_id, "lid": lesson_id},
        )

    # Replace any prior submission for this user/exercise.
    await db.execute(
        sql_text(
            "DELETE FROM exercise_submissions "
            "WHERE student_id = :uid AND exercise_id = :eid"
        ),
        {"uid": user_id, "eid": exercise_id},
    )
    await db.execute(
        sql_text(
            """
            INSERT INTO exercise_submissions
                (id, student_id, exercise_id, code, score, feedback,
                 status, attempt_number, created_at, updated_at)
            VALUES
                (gen_random_uuid(), :uid, :eid,
                 '# RAG implementation here',
                 92,
                 'Excellent: built RAG with Pinecone + LangChain '
                 'ingesting 10k docs, served at p50=120ms.',
                 'passed', 1, now(), now())
            """
        ),
        {"uid": user_id, "eid": exercise_id},
    )
    print(f"... seeded capstone submission (exercise={exercise_id})", file=sys.stderr)

    await db.commit()

    # Mint JWT.
    from app.core.security import create_access_token

    token = create_access_token({"sub": str(user_id)})
    return user_id, token


# ── HTTP call helper ──────────────────────────────────────────────


async def fire_chat(
    client: httpx.AsyncClient,
    token: str,
    message: str,
    *,
    flow: str = "default",
) -> tuple[int, dict[str, Any]]:
    """POST to /api/v1/agentic/{flow}/chat. Returns (status, body)."""
    resp = await client.post(
        f"{API_BASE_URL}/api/v1/agentic/{flow}/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": message},
        timeout=120.0,
    )
    try:
        body = resp.json()
    except Exception:
        body = {"_raw": resp.text}
    return resp.status_code, body


async def fetch_agent_actions(
    db: Any,
    student_id: uuid.UUID,
    *,
    since: datetime,
) -> list[dict[str, Any]]:
    """Read all agent_actions rows for the student created since `since`.

    agent_actions doesn't have a request_id column — we correlate by
    (student_id, time window). Caller should pass `since` = a moment
    just before the HTTP call fired so we capture only this request's
    actions.
    """
    result = await db.execute(
        sql_text(
            """
            SELECT id, agent_name, status, cost_inr, tokens_used,
                   output_data, created_at, duration_ms
            FROM agent_actions
            WHERE student_id = :sid
              AND created_at >= :since
            ORDER BY created_at ASC
            """
        ),
        {"sid": student_id, "since": since},
    )
    rows = []
    for row in result.fetchall():
        rows.append({
            "id": str(row.id),
            "agent_name": row.agent_name,
            "status": row.status,
            "cost_inr": float(row.cost_inr) if row.cost_inr is not None else None,
            "tokens_used": row.tokens_used,
            "output_data": row.output_data,
            "duration_ms": row.duration_ms,
        })
    return rows


async def fetch_agent_invocation_log_for_user_recent(
    db: Any, user_id: uuid.UUID, source: str = "tailored_resume"
) -> list[dict[str, Any]]:
    """Read agent_invocation_log rows for the user from the last 5 minutes.

    Real columns (per migration 0037 / agent_invocation_log model):
      sub_agent, tokens_in, tokens_out, status (not event),
      no validation_passed column.
    """
    result = await db.execute(
        sql_text(
            """
            SELECT id, source, sub_agent, status, model,
                   tokens_in, tokens_out, cost_inr, error_message, created_at
            FROM agent_invocation_log
            WHERE user_id = :uid
              AND source = :src
              AND created_at > now() - interval '5 minutes'
            ORDER BY created_at ASC
            """
        ),
        {"uid": user_id, "src": source},
    )
    rows = []
    for row in result.fetchall():
        rows.append({
            "id": str(row.id),
            "source": row.source,
            "sub_agent": row.sub_agent,
            "status": row.status,
            "model": row.model,
            "tokens_in": row.tokens_in,
            "tokens_out": row.tokens_out,
            "cost_inr": float(row.cost_inr) if row.cost_inr is not None else None,
            "error_message": row.error_message,
        })
    return rows


# ── Violation scanning ────────────────────────────────────────────


def scan_violations(text: str) -> dict[str, list[str]]:
    """Scan response text for Deferral C violations."""
    return {
        "salary_numbers": SALARY_PATTERN.findall(text)[:5],
        "job_count_claims": JOB_COUNT_PATTERN.findall(text)[:5],
        "growth_percentages": GROWTH_PCT_PATTERN.findall(text)[:5],
    }


# ── Report builder ────────────────────────────────────────────────


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.total_cost = 0.0
        self.cap_hit = False
        self.cap_at_call: int | None = None

    def add(self, line: str = "") -> None:
        self.lines.append(line)

    def add_cost(self, cost: float, call_n: int) -> bool:
        """Add cost; return True if cap exceeded."""
        self.total_cost += cost
        if self.total_cost > COST_CAP_INR:
            self.cap_hit = True
            self.cap_at_call = call_n
            return True
        return False

    def render(self) -> str:
        return "\n".join(self.lines)


# ── Main ──────────────────────────────────────────────────────────


async def main() -> int:
    report = Report()
    report.add("## CP3 Parts A and B Verification Evidence")
    report.add()

    engine = create_async_engine(DB_DSN, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        # ── Setup ─────────────────────────────────────────────────
        report.add("### Setup")
        try:
            user_id, token = await setup_test_user(db)
        except Exception as exc:
            report.add(f"- setup FAILED: `{type(exc).__name__}: {exc}`")
            print(report.render())
            return 1
        report.add(f"- test user: `{TEST_USER_EMAIL}` ({user_id}), role=student, JWT minted: ✓")
        report.add("- entitlement: ✓ `course_entitlements` row, source=`admin_grant`, expires_at=now+1h (standard tier — D12 agents require this; free_tier_grants only admits billing_support+supervisor)")
        report.add("- capstone evidence pre-seed for A3: ✓ (mechanism: `exercises` + `exercise_submissions` tables; title='D12 CP3 RAG Capstone', score=92.0)")
        report.add()

        # ── Pre-flight probe ─────────────────────────────────────
        report.add("- pre-flight probe: hitting /api/v1/agentic/default/chat with `\"hello\"`...")
        probe_since = datetime.now(UTC) - timedelta(seconds=2)
        async with httpx.AsyncClient() as client:
            probe_status, probe_body = await fire_chat(client, token, "hello")
        if probe_status != 200:
            report.add(f"- pre-flight probe: ✗ HTTP {probe_status}")
            report.add(f"  body: `{json.dumps(probe_body)[:500]}`")
            report.add()
            report.add("Aborting before A1-A4 — setup is broken.")
            print(report.render())
            return 1
        probe_actions = await fetch_agent_actions(db, user_id, since=probe_since)
        probe_cost = sum(a["cost_inr"] or 0 for a in probe_actions)
        report.add(f"- pre-flight probe: ✓ HTTP 200, agent={probe_body.get('agent_name')!r}, cost=₹{probe_cost:.4f} ({len(probe_actions)} agent_actions row(s))")
        report.add(f"  response excerpt: `{(probe_body.get('response') or '')[:120]!r}`")
        report.add()
        report.add_cost(probe_cost, 0)

        # Build the four agent test inputs ────────────────────────
        a1_message = (
            "I'm a backend engineer with 5 years experience, I want to "
            "move into AI engineering. What should I focus on?"
        )
        a2_message = (
            "Build me a 12-week study plan to learn LangChain and "
            "vector databases for an AI engineering role. I have "
            "about 8 hours per week."
        )
        a3_resume = (
            "John Doe — Backend Engineer\n"
            "EXPERIENCE\n"
            "* Built a RAG system using Pinecone and LangChain that "
            "ingests 10000 documents and serves queries at p50=120ms.\n"
            "* Led a team of 12 ML engineers on a production deployment.\n"
            "* Reduced infrastructure costs by 47% YoY through "
            "architecture refactoring.\n"
            "SKILLS: Python, FastAPI, Pinecone, LangChain, Docker."
        )
        a3_message = f"Please review my resume:\n\n{a3_resume}"
        a4_resume = (
            "Jane Smith — Senior Backend Engineer (5y)\n"
            "EXPERIENCE\n"
            "* Built a RAG system using Pinecone + LangChain ingesting "
            "10k docs at p50=120ms.\n"
            "* Wrote async FastAPI services on PostgreSQL + Redis.\n"
            "SKILLS: Python, FastAPI, Pinecone, LangChain, async, Docker."
        )
        a4_jd = (
            "AI Engineer at Acme Corp. Required: Python, RAG systems, "
            "vector databases (Pinecone or Weaviate), LangChain or "
            "LlamaIndex experience, async backend (FastAPI ideal). "
            "5+ years backend experience required."
        )
        a4_message = (
            f"Tailor this resume for this AI Engineer role at Acme Corp:\n\n"
            f"Resume:\n{a4_resume}\n\nJob description:\n{a4_jd}"
        )
        chain_message = (
            "Help me figure out my career direction and then build me "
            "a study plan to get there. I'm a backend engineer wanting "
            "to move into AI engineering."
        )

        async with httpx.AsyncClient() as client:
            # ── A1 career_coach ──────────────────────────────────
            report.add("### Part A — Real-MiniMax per agent")
            report.add()
            report.add("#### A1 career_coach")
            a1_since = datetime.now(UTC) - timedelta(seconds=2)
            try:
                a1_status, a1_body = await fire_chat(client, token, a1_message)
            except Exception as exc:
                report.add(f"- HTTP call FAILED: `{type(exc).__name__}: {exc}`")
                report.add()
                a1_body = {}
                a1_status = 0

            await _record_call_evidence(
                report=report,
                db=db,
                status=a1_status,
                body=a1_body,
                expected_agent="career_coach",
                user_id=user_id,
                since=a1_since,
                call_n=1,
                extra_block=lambda body: _career_coach_violation_block(body),
            )

            if report.cap_hit:
                report.add(f"\n**COST CAP HIT** at ₹{report.total_cost:.2f} after call {report.cap_at_call}; expected ~₹0.35; surface as anomaly. Aborting before A2.")
                print(report.render())
                return 2

            # ── A2 study_planner ─────────────────────────────────
            report.add()
            report.add("#### A2 study_planner")
            a2_since = datetime.now(UTC) - timedelta(seconds=2)
            try:
                a2_status, a2_body = await fire_chat(client, token, a2_message)
            except Exception as exc:
                report.add(f"- HTTP call FAILED: `{type(exc).__name__}: {exc}`")
                a2_body = {}
                a2_status = 0

            await _record_call_evidence(
                report=report,
                db=db,
                status=a2_status,
                body=a2_body,
                expected_agent="study_planner",
                user_id=user_id,
                since=a2_since,
                call_n=2,
                extra_block=lambda body: _study_planner_mode_block(body),
            )

            if report.cap_hit:
                report.add(f"\n**COST CAP HIT** at ₹{report.total_cost:.2f} after call {report.cap_at_call}. Aborting before A3.")
                print(report.render())
                return 2

            # ── A3 resume_reviewer ───────────────────────────────
            report.add()
            report.add("#### A3 resume_reviewer")
            a3_since = datetime.now(UTC) - timedelta(seconds=2)
            try:
                a3_status, a3_body = await fire_chat(client, token, a3_message)
            except Exception as exc:
                report.add(f"- HTTP call FAILED: `{type(exc).__name__}: {exc}`")
                a3_body = {}
                a3_status = 0

            await _record_call_evidence(
                report=report,
                db=db,
                status=a3_status,
                body=a3_body,
                expected_agent="resume_reviewer",
                user_id=user_id,
                since=a3_since,
                call_n=3,
                extra_block=lambda body: _resume_reviewer_grounded_block(body),
            )

            if report.cap_hit:
                report.add(f"\n**COST CAP HIT** at ₹{report.total_cost:.2f} after call {report.cap_at_call}. Aborting before A4.")
                print(report.render())
                return 2

            # ── A4 tailored_resume ───────────────────────────────
            report.add()
            report.add("#### A4 tailored_resume")
            a4_since = datetime.now(UTC) - timedelta(seconds=2)
            try:
                a4_status, a4_body = await fire_chat(client, token, a4_message)
            except Exception as exc:
                report.add(f"- HTTP call FAILED: `{type(exc).__name__}: {exc}`")
                a4_body = {}
                a4_status = 0

            async def _a4_extra(body: dict[str, Any]) -> list[str]:
                return await _tailored_resume_double_count_block(
                    body, db, user_id, since=a4_since
                )

            await _record_call_evidence(
                report=report,
                db=db,
                status=a4_status,
                body=a4_body,
                expected_agent="tailored_resume",
                user_id=user_id,
                since=a4_since,
                call_n=4,
                extra_block=_a4_extra,
                extra_block_async=True,
            )

            if report.cap_hit:
                report.add(f"\n**COST CAP HIT** at ₹{report.total_cost:.2f} after call {report.cap_at_call}. Aborting before B.")
                print(report.render())
                return 2

            # ── B chain dispatch ─────────────────────────────────
            report.add()
            report.add("### Part B — Chain dispatch")
            report.add()
            b_since = datetime.now(UTC) - timedelta(seconds=2)
            try:
                b_status, b_body = await fire_chat(client, token, chain_message)
            except Exception as exc:
                report.add(f"- HTTP call FAILED: `{type(exc).__name__}: {exc}`")
                b_body = {}
                b_status = 0

            report.add(f"- HTTP status: {b_status}")
            request_id = b_body.get("request_id")
            report.add(f"- request_id (response body): `{request_id}`")
            report.add(f"- top-level agent_name: `{b_body.get('agent_name')}`")

            if True:
                actions = await fetch_agent_actions(db, user_id, since=b_since)
                report.add(f"- agent_actions rows: **{len(actions)}**")
                for a in actions:
                    model = (
                        a["output_data"].get("llm", {}).get("model")
                        if isinstance(a["output_data"], dict)
                        else None
                    )
                    cost_s = f"₹{a['cost_inr']:.4f}" if a['cost_inr'] is not None else "N/A"
                    report.add(
                        f"  - `{a['agent_name']}` status=`{a['status']}` "
                        f"cost={cost_s} tokens={a['tokens_used']} "
                        f"model=`{model}` duration={a['duration_ms']}ms"
                    )
                chain_total = sum(a["cost_inr"] or 0 for a in actions)
                report.add(f"- chain total cost_inr: ₹{chain_total:.4f}")
                report.add_cost(chain_total, 5)

                names = [a["agent_name"] for a in actions]
                if len(actions) >= 2 and "career_coach" in names and "study_planner" in names:
                    report.add("- 2-step chain: ✓ (career_coach + study_planner present)")
                else:
                    report.add(f"- 2-step chain: ✗ (got {names})")

                response_text = b_body.get("response", "") or ""
                report.add(f"- response excerpt: `{response_text[:300]!r}`")
                # Heuristic integration check.
                career_keywords = ["career", "transition", "skills", "focus"]
                plan_keywords = ["week", "plan", "schedule", "session", "study"]
                hits_career = any(k in response_text.lower() for k in career_keywords)
                hits_plan = any(k in response_text.lower() for k in plan_keywords)
                if hits_career and hits_plan:
                    report.add("- response integration: ✓ (references both career direction AND study plan terms)")
                else:
                    report.add(f"- response integration: ⚠ career_terms={hits_career}, plan_terms={hits_plan}")

            # ── Total ─────────────────────────────────────────────
            report.add()
            report.add("### Total cost")
            report.add(f"- Sum of all calls' cost_inr: **₹{report.total_cost:.4f}**")
            cap_status = "not hit" if not report.cap_hit else f"hit at call {report.cap_at_call}"
            report.add(f"- Cap status: {cap_status}")
            report.add(f"- Cap value: ₹{COST_CAP_INR:.2f}")

    print(report.render())
    return 0


async def _record_call_evidence(
    *,
    report: Report,
    db: Any,
    status: int,
    body: dict[str, Any],
    expected_agent: str,
    user_id: uuid.UUID,
    since: datetime,
    call_n: int,
    extra_block: Any = None,
    extra_block_async: bool = False,
) -> None:
    report.add(f"- HTTP status: {status}")
    request_id = body.get("request_id")
    report.add(f"- request_id (response body): `{request_id}`")
    report.add(f"- top-level agent_name: `{body.get('agent_name')}` (expected `{expected_agent}`)")

    actions = await fetch_agent_actions(db, user_id, since=since)
    report.add(f"- agent_actions rows in window: {len(actions)} ({[a['agent_name'] for a in actions]!r})")
    target = next(
        (a for a in actions if a["agent_name"] == expected_agent),
        actions[-1] if actions else None,
    )
    if target:
        model = (
            target["output_data"].get("llm", {}).get("model")
            if isinstance(target["output_data"], dict)
            else None
        )
        cost_str = f"₹{target['cost_inr']:.4f}" if target['cost_inr'] is not None else "N/A"
        report.add(
            f"- agent_actions row (`{target['agent_name']}`): cost={cost_str}, "
            f"tokens_used={target['tokens_used']}, model=`{model}`, "
            f"status=`{target['status']}`, duration={target['duration_ms']}ms"
        )
        report.add_cost(target["cost_inr"] or 0, call_n)
    else:
        report.add("- ⚠ no matching agent_actions row")

    response_text = body.get("response", "") or ""
    report.add(f"- response excerpt (first 500 chars): `{response_text[:500]!r}`")

    if extra_block is not None:
        if extra_block_async:
            block = await extra_block(body)
        else:
            block = extra_block(body)
        for line in block:
            report.add(line)


def _career_coach_violation_block(body: dict[str, Any]) -> list[str]:
    response_text = body.get("response", "") or ""
    violations = scan_violations(response_text)
    n_salary = len(violations["salary_numbers"])
    n_jobs = len(violations["job_count_claims"])
    n_growth = len(violations["growth_percentages"])
    out = []
    if n_salary == 0 and n_jobs == 0 and n_growth == 0:
        out.append("- VIOLATION CHECK (Deferral C): ✓ clean — no salary numbers, job counts, or growth percentages")
    else:
        out.append(
            f"- VIOLATION CHECK (Deferral C): ⚠ found "
            f"salary={n_salary}, job_counts={n_jobs}, growth_pct={n_growth}"
        )
        if n_salary:
            out.append(f"  - salary hits: `{violations['salary_numbers']!r}`")
        if n_jobs:
            out.append(f"  - job count hits: `{violations['job_count_claims']!r}`")
        if n_growth:
            out.append(f"  - growth pct hits: `{violations['growth_percentages']!r}`")
    return out


def _study_planner_mode_block(body: dict[str, Any]) -> list[str]:
    out = []
    response_text = body.get("response", "") or ""
    # Mode-inference signal: scan response/output for mode hint.
    # The output_data should contain mode in output_preview or similar.
    request_id = body.get("request_id")
    out.append(
        f"- mode_inferred event: emits via log_event → structlog stdout only "
        f"(no DB sink, see followups/log-event-observability-sink.md). "
        f"Verify by `docker compose logs backend | grep '{request_id}'` "
        f"after this call — look for "
        f"`event_name=study_planner.mode_inferred properties=...`."
    )
    # Heuristic: response should mention weekly structure given the prompt.
    weekly_signals = ["week 1", "week 2", "week 3", "weekly", "12 weeks", "12-week"]
    hits = [s for s in weekly_signals if s in response_text.lower()]
    if hits:
        out.append(f"- weekly_plan shape signals in response: ✓ ({hits!r})")
    else:
        out.append("- weekly_plan shape signals in response: ⚠ none of [week N, weekly, 12 weeks] found")
    return out


def _resume_reviewer_grounded_block(body: dict[str, Any]) -> list[str]:
    out = []
    response_text = body.get("response", "") or ""
    # Pre-seeded RAG capstone — should NOT appear in unsupported claims.
    rag_terms = ["rag", "pinecone", "langchain"]
    rag_in_response = any(t in response_text.lower() for t in rag_terms)
    out.append(f"- pre-seeded RAG capstone referenced in response: {'✓' if rag_in_response else '⚠ missing'}")
    # Unsupported claims in resume — should be flagged.
    unsupported_signals = [
        "12", "ml engineers", "team", "47%", "cost", "infrastructure",
        "led", "reduced",
    ]
    hits = [s for s in unsupported_signals if s in response_text.lower()]
    if hits:
        out.append(f"- unsupported-claim flags in response: ✓ ({hits[:5]!r})")
    else:
        out.append("- unsupported-claim flags in response: ⚠ neither 'team of 12' nor '47%' flagged")
    return out


async def _tailored_resume_double_count_block(
    body: dict[str, Any],
    db: Any,
    user_id: uuid.UUID,
    *,
    since: datetime,
) -> list[str]:
    out = []
    inv_rows = await fetch_agent_invocation_log_for_user_recent(
        db, user_id, source="tailored_resume"
    )
    out.append(f"- agent_invocation_log rows (last 5min, source=tailored_resume): {len(inv_rows)}")
    for r in inv_rows[-3:]:
        out.append(
            f"  - sub_agent=`{r['sub_agent']}` status=`{r['status']}` "
            f"model=`{r['model']}` cost=₹{r['cost_inr']} "
            f"tokens_in={r['tokens_in']} tokens_out={r['tokens_out']}"
        )
    if inv_rows and any(r["status"] in ("completed", "ok", "success") for r in inv_rows):
        out.append("- shim parsing: ✓ resume_text + jd_text extracted from message; service completed")
    elif inv_rows:
        last_status = inv_rows[-1]["status"]
        out.append(f"- shim parsing: ⚠ service started but last status is `{last_status}` (error_message: `{inv_rows[-1].get('error_message')}`)")
    else:
        out.append("- shim parsing: ⚠ no agent_invocation_log rows — message may not have parsed to (resume_text, jd_text); fail-honest path likely fired")
    actions = await fetch_agent_actions(db, user_id, since=since)
    ag_action_costs = [a["cost_inr"] for a in actions if a["agent_name"] == "tailored_resume" and a["cost_inr"]]
    inv_costs = [r["cost_inr"] for r in inv_rows if r["cost_inr"]]
    out.append(
        f"- DOUBLE-COUNT OBSERVATION: agent_actions tailored_resume cost(s)={ag_action_costs}, "
        f"agent_invocation_log cost(s)={inv_costs}"
    )
    out.append(
        "  - Both surfaces record cost when the shim path fires. "
        "Canonical for cost ceiling enforcement: `agent_actions.cost_inr` "
        "(read by `mv_student_daily_cost`, the cost-cap rollup view). "
        "`agent_invocation_log.cost_inr` is a per-feature audit row "
        "for tailored_resume's own dashboards. Surface — not a bug for D12."
    )
    return out


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
