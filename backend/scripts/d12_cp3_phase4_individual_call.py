"""D12 CP3 Phase 4 — single-agent diagnostic via the canonical endpoint.

Fires ONE HTTP call to /api/v1/agentic/default/chat as the test user
created during the Phase 1 setup. Captures:

  • HTTP status + response body (request_id, agent_name, response text)
  • agent_actions row(s) for the request window (cost, tokens, model, status, duration)
  • For non-tailored_resume agents: parsed output snippet from output_data.output_preview
  • For tailored_resume: agent_invocation_log row from the inner pipeline

Driven by an --agent argument so we can run each Stage 4.1 call separately
and pause between them per the protocol.

Usage (inside backend container):
    uv run python scripts/d12_cp3_phase4_individual_call.py --agent study_planner
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

import httpx
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
DB_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@db:5432/platform",
)
TEST_USER_EMAIL = "d12_cp3_smoke@example.com"

# Re-use the message shapes from the original Phase 2 / earlier smoke.
MESSAGES: dict[str, str] = {
    "study_planner": (
        "I have 8 hours this week. What should I focus on tonight and "
        "for tomorrow's study session — give me a specific weekly plan "
        "with daily blocks?"
    ),
    "career_coach": (
        "I'm a backend engineer with 5 years experience. I want to move into "
        "senior GenAI engineering roles in the next 6 months. What should I "
        "focus on, and how should I structure my learning given I have about "
        "8 hours per week?"
    ),
    "resume_reviewer": (
        "Please review my resume:\n\n"
        "John Doe — Backend Engineer\n"
        "EXPERIENCE\n"
        "* Built a RAG system using Pinecone and LangChain that "
        "ingests 10000 documents and serves queries at p50=120ms.\n"
        "* Led a team of 12 ML engineers on a production deployment.\n"
        "* Reduced infrastructure costs by 47% YoY through "
        "architecture refactoring.\n"
        "SKILLS: Python, FastAPI, Pinecone, LangChain, Docker."
    ),
    "tailored_resume": (
        "Tailor this resume for this AI Engineer role at Acme Corp:\n\n"
        "Resume:\n"
        "Jane Smith — Senior Backend Engineer (5y)\n"
        "EXPERIENCE\n"
        "* Built a RAG system using Pinecone + LangChain ingesting "
        "10k docs at p50=120ms.\n"
        "* Wrote async FastAPI services on PostgreSQL + Redis.\n"
        "SKILLS: Python, FastAPI, Pinecone, LangChain, async, Docker.\n\n"
        "Job description:\n"
        "AI Engineer at Acme Corp. Required: Python, RAG systems, "
        "vector databases (Pinecone or Weaviate), LangChain or "
        "LlamaIndex experience, async backend (FastAPI ideal). "
        "5+ years backend experience required."
    ),
    "chain": (
        "I want to transition to senior GenAI engineering in 12 weeks; "
        "help me figure out how to approach this and build me a study "
        "plan to get there. I have 8 hours per week available."
    ),
}


async def fetch_user_id(db: Any) -> uuid.UUID | None:
    result = await db.execute(
        sql_text("SELECT id FROM users WHERE email = :email"),
        {"email": TEST_USER_EMAIL},
    )
    row = result.fetchone()
    return row.id if row else None


async def fetch_agent_actions(
    db: Any, student_id: uuid.UUID, *, since: datetime
) -> list[dict[str, Any]]:
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
    return [
        {
            "id": str(row.id),
            "agent_name": row.agent_name,
            "status": row.status,
            "cost_inr": float(row.cost_inr) if row.cost_inr is not None else None,
            "tokens_used": row.tokens_used,
            "output_data": row.output_data,
            "duration_ms": row.duration_ms,
        }
        for row in result.fetchall()
    ]


async def fetch_agent_invocation_log(
    db: Any, user_id: uuid.UUID, source: str, *, since: datetime
) -> list[dict[str, Any]]:
    result = await db.execute(
        sql_text(
            """
            SELECT id, source, sub_agent, status, model,
                   tokens_in, tokens_out, cost_inr, error_message, created_at
            FROM agent_invocation_log
            WHERE user_id = :uid
              AND source = :src
              AND created_at >= :since
            ORDER BY created_at ASC
            """
        ),
        {"uid": user_id, "src": source, "since": since},
    )
    return [
        {
            "sub_agent": row.sub_agent,
            "status": row.status,
            "model": row.model,
            "tokens_in": row.tokens_in,
            "tokens_out": row.tokens_out,
            "cost_inr": float(row.cost_inr) if row.cost_inr is not None else None,
            "error_message": row.error_message,
        }
        for row in result.fetchall()
    ]


def scan_violations(text: str) -> dict[str, list[str]]:
    """For career_coach Deferral C compliance check."""
    salary = re.compile(
        r"(\$|₹|USD|INR|EUR|GBP)\s?[\d,]+(?:\.\d+)?\s?(k|K|million|M|lakh|crore|LPA)?"
        r"|\b\d+(?:\.\d+)?\s?(k|K|lakh|crore|LPA)\b"
    )
    jobs = re.compile(
        r"\b\d{2,}\s*(jobs?|openings?|positions?|listings?|vacancies?|roles?)\b",
        re.IGNORECASE,
    )
    growth = re.compile(
        r"\b\d{1,2}(?:\.\d+)?\s?%\s*(growth|increase|rise|expansion|YoY|year-over-year)",
        re.IGNORECASE,
    )
    return {
        "salary": salary.findall(text)[:5],
        "jobs": jobs.findall(text)[:5],
        "growth": growth.findall(text)[:5],
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--agent",
        required=True,
        choices=list(MESSAGES.keys()),
        help="Agent name OR 'chain' for the multi-agent dispatch test.",
    )
    args = parser.parse_args()

    print("=" * 70)
    print(f"D12 CP3 Phase 4 — single-agent diagnostic: {args.agent}")
    print("=" * 70)

    engine = create_async_engine(DB_DSN, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        user_id = await fetch_user_id(db)
        if user_id is None:
            print("ERROR: test user not found. Run Phase 1 setup first.")
            return 1
        print(f"\nTest user: {user_id}")

        from app.core.security import create_access_token

        token = create_access_token({"sub": str(user_id)})
        print("JWT minted")

        message = MESSAGES[args.agent]
        print(f"\nMessage ({len(message)} chars): {message[:200]!r}{'...' if len(message) > 200 else ''}")

        # Capture timestamps for the agent_actions/log queries.
        since = datetime.now(UTC) - timedelta(seconds=2)
        print(f"\nWindow start: {since.isoformat()}")
        print(f"\n→ POST {API_BASE_URL}/api/v1/agentic/default/chat ...")

        start = datetime.now(UTC)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{API_BASE_URL}/api/v1/agentic/default/chat",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"message": message},
                    timeout=180.0,  # exceed 120s tailored_resume override
                )
        except Exception as exc:  # noqa: BLE001
            print(f"\nHTTP call FAILED: {type(exc).__name__}: {exc}")
            return 1

        elapsed = (datetime.now(UTC) - start).total_seconds()
        print(f"\nHTTP response in {elapsed:.2f}s — status {resp.status_code}")

        try:
            body = resp.json()
        except Exception:
            body = {"_raw": resp.text}

        print(f"  request_id:   {body.get('request_id')}")
        print(f"  agent_name:   {body.get('agent_name')}")
        print(f"  blocked:      {body.get('blocked')}")
        print(f"  block_reason: {body.get('block_reason')}")
        print(f"  decline:      {body.get('decline_reason')}")
        print(f"  duration_ms (server-reported): {body.get('duration_ms')}")
        print()
        response_text = body.get("response", "") or ""
        print(f"  response excerpt (first 600 chars):\n  ---\n  {response_text[:600]!r}\n  ---")

        # Read agent_actions in window.
        print(f"\nFetching agent_actions rows for user since {since.isoformat()}...")
        actions = await fetch_agent_actions(db, user_id, since=since)
        print(f"  {len(actions)} row(s) found:")
        for a in actions:
            model = (
                a["output_data"].get("llm", {}).get("model")
                if isinstance(a["output_data"], dict)
                else None
            )
            cost_str = f"₹{a['cost_inr']:.4f}" if a["cost_inr"] is not None else "N/A"
            print(
                f"    - agent={a['agent_name']!r} status={a['status']!r} "
                f"cost={cost_str} tokens={a['tokens_used']} "
                f"model={model!r} duration={a['duration_ms']}ms"
            )

        # Look at the target agent's row specifically.
        target_row = next(
            (a for a in actions if a["agent_name"] == args.agent), None
        )
        print()
        if target_row is None:
            print(f"WARNING: no agent_actions row for {args.agent!r}.")
        else:
            print(f"Target agent row ({args.agent}):")
            print(f"  status:        {target_row['status']}")
            print(f"  duration_ms:   {target_row['duration_ms']}ms")
            cost_str = (
                f"₹{target_row['cost_inr']:.4f}"
                if target_row["cost_inr"] is not None
                else "N/A"
            )
            print(f"  cost_inr:      {cost_str}")
            print(f"  tokens_used:   {target_row['tokens_used']}")
            od = target_row["output_data"] or {}
            if isinstance(od, dict):
                print(f"  llm.model:     {od.get('llm', {}).get('model')}")
                preview = od.get("output_preview")
                if preview is not None:
                    print()
                    print(
                        f"  output_preview (first 800 chars of dump):\n"
                        f"  {json.dumps(preview, default=str)[:800]}"
                    )

        # Agent-specific extra evidence
        if args.agent == "tailored_resume":
            print("\nFetching agent_invocation_log rows (source=tailored_resume)...")
            inv = await fetch_agent_invocation_log(
                db, user_id, "tailored_resume", since=since
            )
            print(f"  {len(inv)} row(s):")
            for r in inv:
                print(
                    f"    - sub_agent={r['sub_agent']!r} status={r['status']!r} "
                    f"model={r['model']!r} cost=₹{r['cost_inr']:.4f if r['cost_inr'] else '0'} "
                    f"tokens_in={r['tokens_in']} tokens_out={r['tokens_out']}"
                )

        if args.agent == "career_coach":
            v = scan_violations(response_text)
            n_salary, n_jobs, n_growth = (
                len(v["salary"]),
                len(v["jobs"]),
                len(v["growth"]),
            )
            if n_salary == 0 and n_jobs == 0 and n_growth == 0:
                print(
                    "\nDeferral C check: ✓ clean — no salary/job-count/growth-pct"
                )
            else:
                print(
                    f"\nDeferral C check: ⚠ salary={n_salary} jobs={n_jobs} growth={n_growth}"
                )
                if n_salary:
                    print(f"  salary hits: {v['salary']!r}")
                if n_jobs:
                    print(f"  jobs hits:   {v['jobs']!r}")
                if n_growth:
                    print(f"  growth hits: {v['growth']!r}")

        # Cost summary
        target_cost = (
            target_row["cost_inr"]
            if target_row and target_row["cost_inr"] is not None
            else 0.0
        )
        print(f"\nCost (target row only): ₹{target_cost:.4f}")
        all_cost = sum(a["cost_inr"] or 0 for a in actions)
        print(f"Cost (all rows in window): ₹{all_cost:.4f}")

    print("\n" + "=" * 70)
    print("END OF DIAGNOSTIC")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
