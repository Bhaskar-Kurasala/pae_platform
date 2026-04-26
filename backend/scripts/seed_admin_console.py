"""Seed mock data for the v1 Admin Console (CareerForge_admin_v1).

Populates the eight admin_console_* tables with the 30 students, pulse
metrics, funnel snapshot, feature usage rows, today's call list, live event
feed and risk reasons that match the approved design mock.

Idempotent: clears the admin_console_* tables and any matching demo students
on each run before reinserting.

Run with:
    docker compose exec backend uv run python -m scripts.seed_admin_console
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.hashing import hash_password
from app.models.admin_console import (
    AdminConsoleCall,
    AdminConsoleEngagement,
    AdminConsoleEvent,
    AdminConsoleFeatureUsage,
    AdminConsoleFunnelSnapshot,
    AdminConsoleProfile,
    AdminConsolePulseMetric,
    AdminConsoleRiskReason,
)
from app.models.user import User

# ── Source data — mirrors the 30 students in the v1 design ──────────────

STUDENTS_RAW: list[dict] = [
    # SEVERE
    dict(slug=1, name="Aanya Reddy", track="Data Analyst", stage="Studio", progress=38, streak=0, last_seen=11, risk=92, paid=True, joined="Feb 14", email="aanya@example.com", city="Hyderabad",
         sessions14=1, flashcards=0, agent_q=0, reviews=0, notes=0, labs=1, capstones=0, purchases=1),
    dict(slug=2, name="Marcus Chen", track="ML Engineer", stage="Capstone", progress=72, streak=0, last_seen=14, risk=89, paid=True, joined="Jan 02", email="marcus@example.com", city="Singapore",
         sessions14=0, flashcards=0, agent_q=1, reviews=0, notes=0, labs=0, capstones=1, purchases=1),
    dict(slug=3, name="Priya Nair", track="Python Developer", stage="Today", progress=14, streak=0, last_seen=18, risk=86, paid=True, joined="Mar 03", email="priya@example.com", city="Bengaluru",
         sessions14=0, flashcards=0, agent_q=0, reviews=0, notes=0, labs=0, capstones=0, purchases=1),
    dict(slug=4, name="Daniel Okafor", track="Data Scientist", stage="Studio", progress=51, streak=0, last_seen=9, risk=78, paid=True, joined="Jan 28", email="daniel@example.com", city="Lagos",
         sessions14=2, flashcards=4, agent_q=1, reviews=0, notes=1, labs=1, capstones=0, purchases=2),
    dict(slug=5, name="Yuki Tanaka", track="GenAI Engineer", stage="Promotion", progress=84, streak=0, last_seen=8, risk=74, paid=True, joined="Dec 11", email="yuki@example.com", city="Tokyo",
         sessions14=1, flashcards=2, agent_q=0, reviews=1, notes=0, labs=0, capstones=1, purchases=1),
    # HIGH
    dict(slug=6, name="Sara Ibrahim", track="Data Analyst", stage="Studio", progress=42, streak=1, last_seen=5, risk=68, paid=True, joined="Feb 20", email="sara@example.com", city="Cairo",
         sessions14=3, flashcards=8, agent_q=2, reviews=1, notes=2, labs=2, capstones=0, purchases=1),
    dict(slug=7, name="Rohan Mehta", track="Python Developer", stage="Today", progress=22, streak=2, last_seen=4, risk=64, paid=False, joined="Apr 02", email="rohan@example.com", city="Mumbai",
         sessions14=4, flashcards=11, agent_q=3, reviews=0, notes=1, labs=1, capstones=0, purchases=0),
    dict(slug=8, name="Elena Vasquez", track="ML Engineer", stage="Capstone", progress=67, streak=1, last_seen=6, risk=62, paid=True, joined="Jan 09", email="elena@example.com", city="Madrid",
         sessions14=5, flashcards=14, agent_q=4, reviews=2, notes=3, labs=3, capstones=1, purchases=2),
    dict(slug=9, name="Tomas Ferreira", track="Data Scientist", stage="Studio", progress=34, streak=0, last_seen=7, risk=60, paid=True, joined="Mar 18", email="tomas@example.com", city="Lisbon",
         sessions14=3, flashcards=6, agent_q=1, reviews=0, notes=1, labs=2, capstones=0, purchases=1),
    dict(slug=10, name="Aisha Patel", track="GenAI Engineer", stage="Studio", progress=29, streak=0, last_seen=5, risk=58, paid=True, joined="Mar 22", email="aisha@example.com", city="London",
         sessions14=4, flashcards=9, agent_q=2, reviews=1, notes=2, labs=1, capstones=0, purchases=1),
    dict(slug=11, name="Liam O'Brien", track="Python Developer", stage="Today", progress=19, streak=1, last_seen=6, risk=56, paid=False, joined="Apr 08", email="liam@example.com", city="Dublin",
         sessions14=3, flashcards=7, agent_q=1, reviews=0, notes=1, labs=0, capstones=0, purchases=0),
    dict(slug=12, name="Mei Wong", track="Data Analyst", stage="Capstone", progress=71, streak=2, last_seen=3, risk=54, paid=True, joined="Jan 14", email="mei@example.com", city="Hong Kong",
         sessions14=6, flashcards=18, agent_q=5, reviews=3, notes=4, labs=3, capstones=1, purchases=1),
    # MEDIUM
    dict(slug=13, name="Carlos Rivera", track="ML Engineer", stage="Studio", progress=48, streak=3, last_seen=2, risk=42, paid=True, joined="Feb 02", email="carlos@example.com", city="Mexico City",
         sessions14=7, flashcards=22, agent_q=6, reviews=2, notes=5, labs=4, capstones=0, purchases=1),
    dict(slug=14, name="Hannah Schmidt", track="Data Scientist", stage="Promotion", progress=88, streak=4, last_seen=1, risk=38, paid=True, joined="Dec 05", email="hannah@example.com", city="Berlin",
         sessions14=8, flashcards=28, agent_q=7, reviews=4, notes=6, labs=5, capstones=1, purchases=2),
    dict(slug=15, name="Vikram Singh", track="Python Developer", stage="Studio", progress=55, streak=5, last_seen=1, risk=34, paid=True, joined="Feb 26", email="vikram@example.com", city="Delhi",
         sessions14=9, flashcards=34, agent_q=9, reviews=3, notes=7, labs=6, capstones=0, purchases=1),
    dict(slug=16, name="Olivia Brennan", track="Data Analyst", stage="Capstone", progress=74, streak=6, last_seen=0, risk=30, paid=True, joined="Jan 22", email="olivia@example.com", city="Sydney",
         sessions14=11, flashcards=42, agent_q=11, reviews=5, notes=8, labs=7, capstones=1, purchases=1),
    dict(slug=17, name="Jamal Washington", track="GenAI Engineer", stage="Studio", progress=46, streak=4, last_seen=1, risk=28, paid=True, joined="Feb 11", email="jamal@example.com", city="Atlanta",
         sessions14=8, flashcards=25, agent_q=8, reviews=3, notes=5, labs=4, capstones=0, purchases=1),
    dict(slug=18, name="Naomi Harper", track="Data Scientist", stage="Studio", progress=39, streak=3, last_seen=2, risk=26, paid=True, joined="Mar 06", email="naomi@example.com", city="Toronto",
         sessions14=7, flashcards=21, agent_q=7, reviews=2, notes=6, labs=3, capstones=0, purchases=1),
    # LOW / THRIVING
    dict(slug=19, name="Arjun Krishnan", track="Python Developer", stage="Promotion", progress=91, streak=9, last_seen=0, risk=15, paid=True, joined="Nov 14", email="arjun@example.com", city="Chennai",
         sessions14=12, flashcards=48, agent_q=14, reviews=7, notes=11, labs=9, capstones=1, purchases=2),
    dict(slug=20, name="Sophie Dubois", track="Data Analyst", stage="Readiness", progress=96, streak=11, last_seen=0, risk=9, paid=True, joined="Oct 28", email="sophie@example.com", city="Paris",
         sessions14=14, flashcards=52, agent_q=18, reviews=9, notes=14, labs=11, capstones=2, purchases=2),
    dict(slug=21, name="Ravi Sharma", track="ML Engineer", stage="Capstone", progress=78, streak=8, last_seen=0, risk=18, paid=True, joined="Dec 19", email="ravi@example.com", city="Pune",
         sessions14=11, flashcards=39, agent_q=13, reviews=6, notes=9, labs=8, capstones=1, purchases=2),
    dict(slug=22, name="Bianca Romano", track="GenAI Engineer", stage="Promotion", progress=85, streak=7, last_seen=0, risk=20, paid=True, joined="Dec 02", email="bianca@example.com", city="Milan",
         sessions14=10, flashcards=36, agent_q=12, reviews=5, notes=8, labs=7, capstones=1, purchases=2),
    dict(slug=23, name="Tariq Al-Rashid", track="Data Scientist", stage="Studio", progress=52, streak=6, last_seen=1, risk=24, paid=True, joined="Feb 09", email="tariq@example.com", city="Dubai",
         sessions14=9, flashcards=31, agent_q=9, reviews=4, notes=7, labs=5, capstones=0, purchases=1),
    dict(slug=24, name="Isabel Costa", track="Data Analyst", stage="Capstone", progress=80, streak=7, last_seen=0, risk=22, paid=True, joined="Jan 06", email="isabel@example.com", city="São Paulo",
         sessions14=10, flashcards=34, agent_q=11, reviews=5, notes=8, labs=6, capstones=1, purchases=1),
    # NEW
    dict(slug=25, name="Kenji Yamamoto", track="Python Developer", stage="Onboarding", progress=6, streak=2, last_seen=0, risk=32, paid=False, joined="Apr 21", email="kenji@example.com", city="Osaka",
         sessions14=2, flashcards=3, agent_q=1, reviews=0, notes=0, labs=0, capstones=0, purchases=0),
    dict(slug=26, name="Zara Khan", track="Data Analyst", stage="Today", progress=12, streak=3, last_seen=0, risk=25, paid=True, joined="Apr 19", email="zara@example.com", city="Karachi",
         sessions14=3, flashcards=6, agent_q=2, reviews=0, notes=1, labs=0, capstones=0, purchases=1),
    dict(slug=27, name="Felix Andersson", track="GenAI Engineer", stage="Onboarding", progress=4, streak=1, last_seen=1, risk=48, paid=False, joined="Apr 22", email="felix@example.com", city="Stockholm",
         sessions14=1, flashcards=1, agent_q=0, reviews=0, notes=0, labs=0, capstones=0, purchases=0),
    # STABLE
    dict(slug=28, name="Ananya Iyer", track="Python Developer", stage="Studio", progress=43, streak=4, last_seen=1, risk=36, paid=True, joined="Feb 15", email="ananya@example.com", city="Bengaluru",
         sessions14=6, flashcards=19, agent_q=5, reviews=2, notes=4, labs=3, capstones=0, purchases=1),
    dict(slug=29, name="Diego Morales", track="ML Engineer", stage="Studio", progress=36, streak=3, last_seen=2, risk=44, paid=True, joined="Mar 01", email="diego@example.com", city="Buenos Aires",
         sessions14=5, flashcards=14, agent_q=3, reviews=1, notes=3, labs=2, capstones=0, purchases=1),
    dict(slug=30, name="Lena Petersen", track="Data Scientist", stage="Capstone", progress=69, streak=5, last_seen=1, risk=31, paid=True, joined="Jan 18", email="lena@example.com", city="Copenhagen",
         sessions14=8, flashcards=26, agent_q=8, reviews=3, notes=6, labs=5, capstones=1, purchases=2),
]

RISK_REASONS: dict[int, str] = {
    1: "Paid 8 weeks ago. Hasn't opened a lesson in 11 days. Stuck on Lab B for 3 attempts.",
    2: "Ghosted mid-capstone. No senior review requested. 14 days silent — biggest paid drop this month.",
    3: "Joined excited, paid in week 1. Hasn't crossed Lesson 2. Classic \"first-week-only\" pattern.",
}

PULSE_METRICS = [
    dict(metric_key="active_24h", label="Active learners (24h)", display_value="138", unit="",
         delta_pct=8, delta_text="vs yesterday", color_hex="#5fa37f", invert=False,
         spark=[42, 48, 51, 55, 62, 71, 68, 74, 82, 88, 95, 102, 118, 138]),
    dict(metric_key="sessions_today", label="Sessions today", display_value="412", unit="",
         delta_pct=14, delta_text="vs avg day", color_hex="#5fa37f", invert=False,
         spark=[280, 310, 295, 340, 360, 355, 380, 390, 372, 395, 400, 408, 412, 412]),
    dict(metric_key="capstones_wk", label="Capstones submitted", display_value="7", unit=" wk",
         delta_pct=40, delta_text="vs last week", color_hex="#5fa37f", invert=False,
         spark=[2, 3, 1, 4, 2, 3, 5, 4, 6, 3, 5, 4, 6, 7]),
    dict(metric_key="promotions_wk", label="Promotions earned", display_value="4", unit=" wk",
         delta_pct=33, delta_text="vs last week", color_hex="#d6a54d", invert=False,
         spark=[1, 2, 1, 3, 1, 2, 2, 3, 2, 3, 2, 3, 4, 4]),
    dict(metric_key="mrr", label="MRR", display_value="$12.3", unit="k",
         delta_pct=11, delta_text="this month", color_hex="#5fa37f", invert=False,
         spark=[8.2, 8.8, 9.1, 9.4, 9.8, 10.1, 10.4, 10.7, 11.0, 11.3, 11.6, 11.9, 12.1, 12.3]),
    dict(metric_key="at_risk", label="At-risk learners", display_value="12", unit="",
         delta_pct=-2, delta_text="vs last week", color_hex="#b8443a", invert=True,
         spark=[18, 17, 16, 16, 15, 15, 14, 14, 13, 13, 13, 12, 12, 12]),
]

FEATURE_USAGE = [
    dict(feature_key="flashcards", name="Flashcard reviews", count="2,847", sub="this week · ▲ 18%", cold=False, bars=[6, 7, 5, 8, 9, 7, 10]),
    dict(feature_key="agent_q", name="Agent questions", count="1,392", sub="this week · ▲ 24%", cold=False, bars=[5, 6, 8, 7, 9, 8, 10]),
    dict(feature_key="senior_reviews", name="Senior reviews", count="184", sub="this week · ▲ 12%", cold=False, bars=[4, 5, 5, 6, 7, 6, 7]),
    dict(feature_key="notes", name="Notes graduated", count="412", sub="this week · ▲ 8%", cold=False, bars=[5, 6, 5, 7, 6, 7, 7]),
    dict(feature_key="labs", name="Lab completions", count="267", sub="this week · ▲ 32%", cold=False, bars=[3, 4, 5, 6, 7, 8, 9]),
    dict(feature_key="capstones", name="Capstone submissions", count="18", sub="this week · ▲ 50%", cold=False, bars=[2, 2, 3, 3, 4, 4, 5]),
    dict(feature_key="jd_match", name="JD Match runs", count="89", sub="this week · ▼ 6%", cold=True, bars=[5, 4, 4, 3, 3, 2, 3]),
    dict(feature_key="interview", name="Interview Coach", count="51", sub="this week · ▼ 18%", cold=True, bars=[4, 4, 3, 3, 2, 2, 2]),
]

FUNNEL_TODAY = dict(signups=1240, onboarded=892, first_lesson=614, paid=387, capstone=218, promoted=142, hired=68)

CALL_LIST = [
    dict(time="10:30", student_slug=1, reason="Stuck on Lab B · stalled 11 days"),
    dict(time="14:00", student_slug=5, reason="Capstone unsubmitted · paid customer"),
    dict(time="16:30", student_slug=11, reason="New learner check-in · onboarding day 17"),
]

EVENT_FEED = [
    dict(slug=20, kind="promo", text="<b>Sophie Dubois</b> earned <b>Data Analyst</b> promotion.", minutes_ago=0),
    dict(slug=19, kind="capstone", text="<b>Arjun Krishnan</b> submitted CLI capstone for review.", minutes_ago=4),
    dict(slug=11, kind="purchase", text="<b>Liam O'Brien</b> purchased Python Developer track ($89).", minutes_ago=12),
    dict(slug=13, kind="review", text="<b>Carlos Rivera</b> requested senior review on async lab.", minutes_ago=28),
    dict(slug=27, kind="signup", text="<b>Felix Andersson</b> joined the GenAI Engineer track.", minutes_ago=42),
    dict(slug=12, kind="capstone", text="<b>Mei Wong</b> resubmitted capstone after revisions.", minutes_ago=60),
    dict(slug=14, kind="promo", text="<b>Hannah Schmidt</b> opened the promotion gate.", minutes_ago=65),
]


# ── Seeder ───────────────────────────────────────────────────────────────


async def _wipe(session: AsyncSession) -> None:
    """Truncate the eight admin_console_* tables and remove any prior demo
    students from a previous seed run."""
    await session.execute(delete(AdminConsoleRiskReason))
    await session.execute(delete(AdminConsoleEvent))
    await session.execute(delete(AdminConsoleCall))
    await session.execute(delete(AdminConsoleEngagement))
    await session.execute(delete(AdminConsoleProfile))
    await session.execute(delete(AdminConsoleFeatureUsage))
    await session.execute(delete(AdminConsolePulseMetric))
    await session.execute(delete(AdminConsoleFunnelSnapshot))

    emails = [s["email"] for s in STUDENTS_RAW]
    await session.execute(delete(User).where(User.email.in_(emails)))
    await session.flush()


async def _ensure_users(session: AsyncSession) -> dict[int, uuid.UUID]:
    """Create one User per student and return a slug→user_id map."""
    pw = hash_password("admin-console-demo")
    slug_to_id: dict[int, uuid.UUID] = {}
    for s in STUDENTS_RAW:
        last_login = datetime.now(UTC) - timedelta(days=s["last_seen"])
        user = User(
            id=uuid.uuid4(),
            email=s["email"],
            full_name=s["name"],
            hashed_password=pw,
            role="student",
            is_active=True,
            is_verified=True,
            last_login_at=last_login,
        )
        session.add(user)
        slug_to_id[s["slug"]] = user.id
    await session.flush()
    return slug_to_id


async def _seed_profiles_and_engagement(session: AsyncSession, slug_to_id: dict[int, uuid.UUID]) -> None:
    for s in STUDENTS_RAW:
        sid = slug_to_id[s["slug"]]
        session.add(
            AdminConsoleProfile(
                id=uuid.uuid4(),
                student_id=sid,
                track=s["track"],
                stage=s["stage"],
                progress_pct=s["progress"],
                streak_days=s["streak"],
                last_seen_days=s["last_seen"],
                risk_score=s["risk"],
                paid=s["paid"],
                joined_label=s["joined"],
                city=s["city"],
            )
        )
        session.add(
            AdminConsoleEngagement(
                id=uuid.uuid4(),
                student_id=sid,
                sessions_14d=s["sessions14"],
                flashcards_14d=s["flashcards"],
                agent_questions_14d=s["agent_q"],
                reviews_14d=s["reviews"],
                notes_14d=s["notes"],
                labs_14d=s["labs"],
                capstones_14d=s["capstones"],
                purchases_total=s["purchases"],
            )
        )
        if s["slug"] in RISK_REASONS:
            session.add(
                AdminConsoleRiskReason(
                    id=uuid.uuid4(),
                    student_id=sid,
                    reason=RISK_REASONS[s["slug"]],
                )
            )


async def _seed_pulse(session: AsyncSession) -> None:
    for i, m in enumerate(PULSE_METRICS):
        session.add(
            AdminConsolePulseMetric(
                id=uuid.uuid4(),
                metric_key=m["metric_key"],
                label=m["label"],
                display_value=m["display_value"],
                unit=m["unit"],
                delta_pct=m["delta_pct"],
                delta_text=m["delta_text"],
                color_hex=m["color_hex"],
                invert_delta=m["invert"],
                spark=m["spark"],
                sort_order=i,
            )
        )


async def _seed_features(session: AsyncSession) -> None:
    for i, f in enumerate(FEATURE_USAGE):
        session.add(
            AdminConsoleFeatureUsage(
                id=uuid.uuid4(),
                feature_key=f["feature_key"],
                name=f["name"],
                count_label=f["count"],
                sub_label=f["sub"],
                is_cold=f["cold"],
                bars=f["bars"],
                sort_order=i,
            )
        )


async def _seed_funnel(session: AsyncSession) -> None:
    session.add(
        AdminConsoleFunnelSnapshot(
            id=uuid.uuid4(),
            snapshot_date=date.today(),
            **FUNNEL_TODAY,
        )
    )


async def _seed_calls(session: AsyncSession, slug_to_id: dict[int, uuid.UUID]) -> None:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    for c in CALL_LIST:
        hh, mm = (int(p) for p in c["time"].split(":"))
        scheduled = today.replace(hour=hh, minute=mm)
        session.add(
            AdminConsoleCall(
                id=uuid.uuid4(),
                student_id=slug_to_id[c["student_slug"]],
                scheduled_for=scheduled,
                display_time=c["time"],
                reason=c["reason"],
            )
        )


async def _seed_events(session: AsyncSession, slug_to_id: dict[int, uuid.UUID]) -> None:
    now = datetime.now(UTC)
    for e in EVENT_FEED:
        session.add(
            AdminConsoleEvent(
                id=uuid.uuid4(),
                student_id=slug_to_id[e["slug"]],
                kind=e["kind"],
                body_html=e["text"],
                occurred_at=now - timedelta(minutes=e["minutes_ago"]),
            )
        )


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await _wipe(session)
        slug_to_id = await _ensure_users(session)
        await _seed_profiles_and_engagement(session, slug_to_id)
        await _seed_pulse(session)
        await _seed_features(session)
        await _seed_funnel(session)
        await _seed_calls(session, slug_to_id)
        await _seed_events(session, slug_to_id)
        await session.commit()
    print(
        f"✓ Seeded admin console: {len(STUDENTS_RAW)} students, "
        f"{len(PULSE_METRICS)} pulse metrics, {len(FEATURE_USAGE)} feature tiles, "
        f"{len(CALL_LIST)} calls, {len(EVENT_FEED)} events."
    )


if __name__ == "__main__":
    asyncio.run(main())
