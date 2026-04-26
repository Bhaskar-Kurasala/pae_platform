"""Service tests for the Application Kit pipeline.

Two tiers:
  1. Pure tests for `build_manifest` — datetime serialization, missing-section
     omission, and shape correctness without touching the DB.
  2. Async DB tests for `list_kits_for_user` (ownership scoping) and
     `build_kit` (happy path with a stubbed PDF renderer).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles


# ── SQLite shim ─────────────────────────────────────────────────────────
# `notebook_entries.tags` uses postgres ARRAY, which the in-memory SQLite
# engine in tests/conftest.py can't render. Map it to TEXT for the test
# session — we never read those rows in this module, but `Base.metadata`
# is created wholesale.
@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(_type, _compiler, **_kw) -> str:  # type: ignore[no-untyped-def]
    return "TEXT"


def _visit_array(self, _type, **_kw):  # type: ignore[no-untyped-def]
    return "TEXT"


SQLiteTypeCompiler.visit_ARRAY = _visit_array  # type: ignore[attr-defined]

from app.models.application_kit import ApplicationKit  # noqa: E402
from app.models.interview_session import InterviewSession  # noqa: E402
from app.models.jd_library import JdLibrary  # noqa: E402
from app.models.mock_interview import MockSessionReport  # noqa: E402
from app.models.portfolio_autopsy_result import (  # noqa: E402
    PortfolioAutopsyResult,
)
from app.models.resume import Resume  # noqa: E402
from app.models.tailored_resume import TailoredResume  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.application_kit import BuildKitRequest  # noqa: E402
from app.services import application_kit_service  # noqa: E402
from app.services.application_kit_service import (  # noqa: E402
    build_kit,
    build_manifest,
    list_kits_for_user,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _make_resume(*, user_id: uuid.UUID) -> Resume:
    return Resume(
        id=uuid.uuid4(),
        user_id=user_id,
        title="Junior Python Engineer",
        summary="Built async APIs.",
        bullets=[{"text": "Wrote a CLI", "evidence_id": "py"}],
        skills_snapshot=["python", "fastapi"],
        ats_keywords=["async", "rest"],
        verdict="good_fit",
    )


def _make_tailored(*, user_id: uuid.UUID, base_id: uuid.UUID) -> TailoredResume:
    return TailoredResume(
        id=uuid.uuid4(),
        user_id=user_id,
        base_resume_id=base_id,
        jd_text="Looking for a Python engineer",
        jd_parsed={"role": "python"},
        intake_answers={},
        content={"summary": "Tailored", "bullets": [{"text": "Highlight A"}]},
        validation={"passed": True},
        pdf_blob=b"%PDF-fake",
    )


def _make_jd(*, user_id: uuid.UUID) -> JdLibrary:
    return JdLibrary(
        id=uuid.uuid4(),
        user_id=user_id,
        title="Senior Python Eng",
        company="Acme",
        jd_text="JD body",
        last_fit_score=87.0,
        verdict="apply",
    )


def _make_autopsy(*, user_id: uuid.UUID) -> PortfolioAutopsyResult:
    return PortfolioAutopsyResult(
        id=uuid.uuid4(),
        user_id=user_id,
        project_title="Async CLI",
        project_description="Pretty good description of a thing built.",
        headline="Solid foundation, missing observability",
        overall_score=72,
        axes={"architecture": {"score": 4, "assessment": "ok"}},
        what_worked=["clean async patterns"],
        what_to_do_differently=[
            {
                "issue": "no metrics",
                "why_it_matters": "blind in prod",
                "what_to_do_differently": "add structlog",
            }
        ],
        production_gaps=["no tests"],
    )


def test_build_manifest_includes_all_sections() -> None:
    uid = uuid.uuid4()
    resume = _make_resume(user_id=uid)
    tailored = _make_tailored(user_id=uid, base_id=resume.id)
    jd = _make_jd(user_id=uid)
    sess_id = uuid.uuid4()
    mock = MockSessionReport(
        id=uuid.uuid4(),
        session_id=sess_id,
        headline="Strong technical, weak STAR",
        verdict="borderline",
        strengths=["clear pseudocode"],
        weaknesses=["rambling stories"],
    )
    autopsy = _make_autopsy(user_id=uid)

    manifest = build_manifest(
        resume=resume,
        tailored=tailored,
        jd=jd,
        mock_report=mock,
        autopsy=autopsy,
        label="My First Kit",
        target_role="Python Eng",
    )

    assert set(manifest) == {
        "label",
        "target_role",
        "built_at",
        "resume",
        "tailored_resume",
        "jd",
        "mock_report",
        "autopsy",
    }
    assert manifest["label"] == "My First Kit"
    assert manifest["target_role"] == "Python Eng"
    # built_at must be isoformat-parseable
    datetime.fromisoformat(manifest["built_at"])
    assert manifest["resume"]["id"] == str(resume.id)
    assert manifest["tailored_resume"]["id"] == str(tailored.id)
    assert manifest["jd"]["fit_score"] == 87
    assert manifest["mock_report"]["verdict"] == "borderline"
    assert manifest["autopsy"]["overall_score"] == 72


def test_build_manifest_omits_missing_sections() -> None:
    uid = uuid.uuid4()
    resume = _make_resume(user_id=uid)
    manifest = build_manifest(
        resume=resume,
        tailored=None,
        jd=None,
        mock_report=None,
        autopsy=None,
        label="Resume only",
        target_role=None,
    )
    assert "resume" in manifest
    assert "tailored_resume" not in manifest
    assert "jd" not in manifest
    assert "mock_report" not in manifest
    assert "autopsy" not in manifest
    assert manifest["target_role"] is None


def test_build_manifest_is_json_safe() -> None:
    """No datetime objects (or other non-JSON types) should leak through."""
    import json

    uid = uuid.uuid4()
    resume = _make_resume(user_id=uid)
    manifest = build_manifest(
        resume=resume,
        tailored=None,
        jd=None,
        mock_report=None,
        autopsy=None,
        label="Pure",
        target_role=None,
    )
    # If any non-JSON-serializable object slipped in, this raises.
    json.dumps(manifest)


# ---------------------------------------------------------------------------
# DB-backed
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, email: str) -> User:
    user = User(
        email=email, full_name="Kit Tester", role="student", hashed_password="x"
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_list_kits_is_scoped_to_user(db_session: AsyncSession) -> None:
    alice = await _make_user(db_session, "alice@kit.test")
    bob = await _make_user(db_session, "bob@kit.test")

    db_session.add_all(
        [
            ApplicationKit(
                user_id=alice.id, label="A1", manifest={}, status="ready"
            ),
            ApplicationKit(
                user_id=alice.id, label="A2", manifest={}, status="ready"
            ),
            ApplicationKit(
                user_id=bob.id, label="B1", manifest={}, status="ready"
            ),
        ]
    )
    await db_session.commit()

    alice_kits = await list_kits_for_user(db_session, user_id=alice.id)
    bob_kits = await list_kits_for_user(db_session, user_id=bob.id)

    assert {k.label for k in alice_kits} == {"A1", "A2"}
    assert {k.label for k in bob_kits} == {"B1"}


@pytest.mark.asyncio
async def test_build_kit_happy_path(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Build a kit with all five sections wired up — verify status flips
    to 'ready', PDF lands on the row, and the manifest carries every section.
    """
    user = await _make_user(db_session, "build@kit.test")

    resume = _make_resume(user_id=user.id)
    db_session.add(resume)

    tailored = _make_tailored(user_id=user.id, base_id=resume.id)
    db_session.add(tailored)

    jd = _make_jd(user_id=user.id)
    db_session.add(jd)

    autopsy = _make_autopsy(user_id=user.id)
    db_session.add(autopsy)

    sess = InterviewSession(
        user_id=user.id, mode="behavioral", status="completed"
    )
    db_session.add(sess)
    await db_session.commit()
    await db_session.refresh(sess)

    report = MockSessionReport(
        session_id=sess.id,
        headline="Solid behavioral, soft on STAR results",
        verdict="borderline",
        strengths=["empathy", "structure"],
        weaknesses=["vague results"],
    )
    db_session.add(report)
    await db_session.commit()

    # Stub the PDF renderer so we don't need WeasyPrint or the GTK toolchain.
    monkeypatch.setattr(
        application_kit_service.pdf_renderer,
        "render_application_kit",
        lambda manifest: b"%PDF-fake",
    )

    request = BuildKitRequest(
        label="apply-acme",
        target_role="Python Engineer",
        jd_library_id=jd.id,
        tailored_resume_id=tailored.id,
        mock_session_id=sess.id,
        autopsy_id=autopsy.id,
    )

    kit = await build_kit(db_session, user=user, request=request)

    assert kit.status == "ready"
    assert kit.pdf_blob == b"%PDF-fake"
    assert isinstance(kit.generated_at, datetime)
    # tzinfo isn't asserted: SQLite drops the offset on round-trip even
    # though the column declares ``timezone=True``. Postgres preserves it.
    assert kit.manifest["label"] == "apply-acme"
    assert kit.manifest["resume"]["id"] == str(resume.id)
    assert kit.manifest["tailored_resume"]["id"] == str(tailored.id)
    assert kit.manifest["jd"]["fit_score"] == 87
    assert kit.manifest["mock_report"]["session_id"] == str(sess.id)
    assert kit.manifest["autopsy"]["overall_score"] == 72


@pytest.mark.asyncio
async def test_build_kit_with_no_optional_refs(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """label-only kits build cleanly even when the user has no resume yet."""
    user = await _make_user(db_session, "minimal@kit.test")
    monkeypatch.setattr(
        application_kit_service.pdf_renderer,
        "render_application_kit",
        lambda manifest: b"%PDF-fake",
    )
    kit = await build_kit(
        db_session,
        user=user,
        request=BuildKitRequest(label="empty"),
    )
    assert kit.status == "ready"
    # No source rows → manifest only carries scaffolding keys.
    assert set(kit.manifest) == {"label", "target_role", "built_at"}


@pytest.mark.asyncio
async def test_build_kit_rejects_unowned_jd(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing another user's JD id must 404 before any row is written."""
    from fastapi import HTTPException

    alice = await _make_user(db_session, "owner@kit.test")
    intruder = await _make_user(db_session, "intruder@kit.test")

    jd = _make_jd(user_id=alice.id)
    db_session.add(jd)
    await db_session.commit()

    monkeypatch.setattr(
        application_kit_service.pdf_renderer,
        "render_application_kit",
        lambda manifest: b"%PDF-fake",
    )

    with pytest.raises(HTTPException) as exc:
        await build_kit(
            db_session,
            user=intruder,
            request=BuildKitRequest(label="bad", jd_library_id=jd.id),
        )
    assert exc.value.status_code == 404
