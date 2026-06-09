"""D17b/ITEM 2.C — pin tests for lookup_jd_decoded.

Closes the cross-student JD leak vector flagged at MEDIUM in
docs/followups/d12-d14c-read-tool-entitlement-leakage-audit.md.
The tool now requires student_id and gates the SQL with
`AND user_id = :student_id`. Mismatched ownership returns
found=False (single error mode).

NOTE: As of D17b/ITEM 2 pre-flight audit, no agent currently
invokes this tool — tailored_resume_v2 fetches the JD via the
service path generate_tailored_resume(jd_id=...) in
tailored_resume_service.py, not via this tool. The fix is
defense-in-depth before someone wires it up.
"""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.agent_specific.tailored_resume.lookup_jd_decoded import (
    LookupJdDecodedInput,
    LookupJdDecodedOutput,
    lookup_jd_decoded,
)


async def _insert_user(session: AsyncSession, uid: uuid.UUID) -> None:
    await session.execute(
        sql_text(
            "INSERT INTO users (id, email, full_name) VALUES (:id, :email, :n)"
        ),
        {"id": uid, "email": f"u-{uid}@test.invalid", "n": "x"},
    )


async def _insert_tailored_resume(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    jd_id: uuid.UUID,
    jd_text: str = "Senior ML Engineer at Acme...",
    jd_parsed: dict | None = None,
) -> None:
    parsed = jd_parsed if jd_parsed is not None else {"role": "ML Engineer"}
    await session.execute(
        sql_text(
            """
            INSERT INTO tailored_resumes
              (id, user_id, jd_id, jd_text, jd_parsed)
            VALUES (:id, :uid, :jid, :txt, CAST(:parsed AS JSONB))
            """
        ),
        {
            "id": uuid.uuid4(),
            "uid": user_id,
            "jid": jd_id,
            "txt": jd_text,
            "parsed": json.dumps(parsed),
        },
    )
    await session.flush()


# ── Authorized read ───────────────────────────────────────────────────


async def test_authorized_read_returns_jd_content(
    session_on_contextvar: AsyncSession,
) -> None:
    student = uuid.uuid4()
    await _insert_user(session_on_contextvar, student)
    jd = uuid.uuid4()
    await _insert_tailored_resume(
        session_on_contextvar, user_id=student, jd_id=jd
    )

    out = await lookup_jd_decoded(
        LookupJdDecodedInput(jd_id=jd, student_id=student)
    )
    assert isinstance(out, LookupJdDecodedOutput)
    assert out.found is True
    assert out.jd_text and "Acme" in out.jd_text
    assert out.jd_parsed and out.jd_parsed.get("role") == "ML Engineer"


# ── Cross-student leak attempt → found=False ──────────────────────────


async def test_cross_student_leak_attempt_returns_not_found(
    session_on_contextvar: AsyncSession,
) -> None:
    """SECURITY: a jd_id from another student must not return JD content
    when the caller's student_id doesn't match.

    Single error mode preserved (found=False; jd_text/jd_parsed both
    None) so an attacker can't probe JD existence."""
    student_a = uuid.uuid4()
    student_b = uuid.uuid4()
    await _insert_user(session_on_contextvar, student_a)
    await _insert_user(session_on_contextvar, student_b)
    jd_b = uuid.uuid4()
    await _insert_tailored_resume(
        session_on_contextvar,
        user_id=student_b,
        jd_id=jd_b,
        jd_text="Confidential JD content for student B",
    )

    out = await lookup_jd_decoded(
        LookupJdDecodedInput(jd_id=jd_b, student_id=student_a)
    )
    assert out.found is False
    assert out.jd_text is None
    assert out.jd_parsed is None


# ── Unknown JD → found=False ──────────────────────────────────────────


async def test_unknown_jd_returns_not_found(
    session_on_contextvar: AsyncSession,
) -> None:
    student = uuid.uuid4()
    await _insert_user(session_on_contextvar, student)
    bogus_jd = uuid.uuid4()

    out = await lookup_jd_decoded(
        LookupJdDecodedInput(jd_id=bogus_jd, student_id=student)
    )
    assert out.found is False


# ── Schema validation ────────────────────────────────────────────────


def test_input_schema_requires_student_id() -> None:
    with pytest.raises(ValidationError):
        LookupJdDecodedInput(jd_id=uuid.uuid4())  # type: ignore[call-arg]
