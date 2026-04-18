# Phase 3B — Receipts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 6 Receipts enhancements (#75 week-on-week diff, #76 concept coverage map, #79 portfolio items, #81 reflection aggregation, #82 time investment chart, #83 next-week suggestion) that turn the weekly receipt into a genuine self-assessment tool.

**Architecture:** Backend: new `receipts_service.py` (pure helpers → service functions → thin route additions to existing `receipts.py`). Frontend: new card components added to the existing `receipts/page.tsx`. Receipts page is already a client component (`"use client"`) — follow that pattern. All data flows through the existing `useMyReceipts()` hook unless a new endpoint is needed.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, React Query (`useMyReceipts`), Recharts (check `package.json` — if absent, use a CSS-based bar chart), shadcn/ui cards.

---

## Worktree & pre-work

Working directory: `/mnt/e/Apps/pae_platform/wt/receipts`

```bash
cd /mnt/e/Apps/pae_platform/wt/receipts
git pull --rebase origin main
cat backend/app/api/v1/routes/receipts.py
cat frontend/src/lib/hooks/use-receipts.ts
cat frontend/src/app/(portal)/receipts/page.tsx
```

Read all three before writing a line. Note what fields `useMyReceipts()` already returns — add new fields to the existing response rather than creating new endpoints where possible.

---

## File structure

**Create (new):**
- `backend/app/services/receipts_service.py`
- `backend/tests/test_services/test_receipts_service.py`
- `frontend/src/components/features/receipts-wow-card.tsx` — #75
- `frontend/src/components/features/receipts-skill-coverage.tsx` — #76
- `frontend/src/components/features/receipts-time-chart.tsx` — #82

**Modify (existing):**
- `backend/app/api/v1/routes/receipts.py` — add new fields
- `frontend/src/app/(portal)/receipts/page.tsx` — add new card components
- `docs/ROADMAP-P3-CRITIC.md` — claim/done markers

---

## Claim protocol (repeat for every ticket)

```bash
# Edit docs/ROADMAP-P3-CRITIC.md: - [ ] #NN → - [~] #NN (p3b, feat/p3b-receipts)
git add docs/ROADMAP-P3-CRITIC.md
git commit -m "chore(tracker): claim 3B-#NN"
```

---

## Task 1: #75 Week-on-week diff

**Critic check:** Students see absolute numbers but can't tell if they improved. Week-on-week diff makes progress legible.

**Files:**
- Create: `backend/app/services/receipts_service.py`
- Create: `backend/tests/test_services/test_receipts_service.py`
- Modify: `backend/app/api/v1/routes/receipts.py`
- Create: `frontend/src/components/features/receipts-wow-card.tsx`

- [ ] **Step 1: Claim #75**

- [ ] **Step 2: Write failing tests**

```python
# backend/tests/test_services/test_receipts_service.py
import pytest
from app.services.receipts_service import compute_week_over_week

def test_improvement() -> None:
    result = compute_week_over_week(prior_lessons=3, current_lessons=5)
    assert result["lessons_delta"] == 2
    assert result["lessons_trend"] == "up"

def test_regression() -> None:
    result = compute_week_over_week(prior_lessons=5, current_lessons=2)
    assert result["lessons_delta"] == -3
    assert result["lessons_trend"] == "down"

def test_no_change() -> None:
    result = compute_week_over_week(prior_lessons=4, current_lessons=4)
    assert result["lessons_delta"] == 0
    assert result["lessons_trend"] == "flat"

def test_first_week_no_prior() -> None:
    result = compute_week_over_week(prior_lessons=None, current_lessons=3)
    assert result["lessons_trend"] == "first_week"
    assert result["lessons_delta"] is None
```

- [ ] **Step 3: Run test — confirm failure**

```bash
cd /mnt/e/Apps/pae_platform/wt/receipts/backend
uv run pytest tests/test_services/test_receipts_service.py -v
```

Expected: ImportError.

- [ ] **Step 4: Create receipts_service.py with pure helpers**

```python
# backend/app/services/receipts_service.py
"""Receipts service — weekly learning summaries and diffs."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_action import AgentAction
from app.models.student_progress import StudentProgress
from app.models.reflection import Reflection

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Pure helpers — unit-testable without a DB
# ---------------------------------------------------------------------------

def compute_week_over_week(
    *,
    prior_lessons: int | None,
    current_lessons: int,
) -> dict[str, Any]:
    """Return delta and trend for lessons completed week-over-week."""
    if prior_lessons is None:
        return {"lessons_delta": None, "lessons_trend": "first_week"}
    delta = current_lessons - prior_lessons
    trend: Literal["up", "down", "flat"] = (
        "up" if delta > 0 else "down" if delta < 0 else "flat"
    )
    return {"lessons_delta": delta, "lessons_trend": trend}


def aggregate_reflections(moods: list[str]) -> dict[str, Any]:
    """Summarise a list of mood strings into counts and dominant mood."""
    from collections import Counter
    counts = Counter(moods)
    dominant = counts.most_common(1)[0][0] if counts else "none"
    return {"mood_counts": dict(counts), "dominant_mood": dominant}
```

- [ ] **Step 5: Run tests — confirm pass**

```bash
uv run pytest tests/test_services/test_receipts_service.py -v
```

Expected: 4 tests green.

- [ ] **Step 6: Add wow field to receipts route**

Check what `GET /api/v1/receipts` currently returns. Add `week_over_week` field to the response by comparing this week's lesson count against last week's. Pattern:

```python
# In routes/receipts.py — augment the existing handler:
from app.services.receipts_service import compute_week_over_week

# After computing this_week_lessons and prior_week_lessons:
wow = compute_week_over_week(
    prior_lessons=prior_week_lessons,
    current_lessons=this_week_lessons,
)
log.info("receipts.wow_computed", user_id=str(current_user.id), trend=wow["lessons_trend"])
# Include wow in the response dict/schema
```

- [ ] **Step 7: Create receipts-wow-card.tsx**

```tsx
// frontend/src/components/features/receipts-wow-card.tsx
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

interface WowData {
  lessons_delta: number | null;
  lessons_trend: "up" | "down" | "flat" | "first_week";
}

export function ReceiptsWowCard({ wow }: { wow: WowData }) {
  if (wow.lessons_trend === "first_week") {
    return (
      <Card>
        <CardContent className="p-4 text-sm text-muted-foreground">
          First week — come back next week to see your progress trend.
        </CardContent>
      </Card>
    );
  }

  const Icon =
    wow.lessons_trend === "up"
      ? TrendingUp
      : wow.lessons_trend === "down"
        ? TrendingDown
        : Minus;
  const colour =
    wow.lessons_trend === "up"
      ? "text-green-600"
      : wow.lessons_trend === "down"
        ? "text-red-500"
        : "text-muted-foreground";

  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <Icon className={`h-5 w-5 ${colour}`} aria-hidden />
        <div>
          <p className="text-sm font-medium">
            {wow.lessons_delta !== null && wow.lessons_delta > 0 ? "+" : ""}
            {wow.lessons_delta} lessons vs last week
          </p>
          <p className="text-xs text-muted-foreground capitalize">{wow.lessons_trend}</p>
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 8: Add card to receipts/page.tsx**

Import and render `<ReceiptsWowCard wow={receipts.week_over_week} />` at the top of the receipt sections.

- [ ] **Step 9: Playwright verify + commit**

```bash
# browser_navigate /receipts
# browser_snapshot — WoW card renders
# Edge case: first-week user sees "first week" message
# commit: feat(receipts): 3B-75 week-on-week diff card
```

---

## Task 2: #76 Concept coverage miniature skill map

**Critic check:** Students don't know which skills they touched this week. A mini map makes coverage scannable.

**Files:**
- Create: `frontend/src/components/features/receipts-skill-coverage.tsx`
- Modify: `frontend/src/app/(portal)/receipts/page.tsx`

- [ ] **Step 1: Claim #76**

- [ ] **Step 2: Add skill coverage data to receipts route**

In `routes/receipts.py`, add a list of skill IDs touched this week (from `agent_actions` where skill context was logged, or from `student_progress` joins). Return as `skills_touched: list[SkillCoverageItem]` where each item has `{ id, name, mastery }`.

- [ ] **Step 3: Create receipts-skill-coverage.tsx**

A simple list of coloured badges (no D3 — that's overkill for a mini view):

```tsx
// frontend/src/components/features/receipts-skill-coverage.tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface SkillItem {
  id: string;
  name: string;
  mastery: number; // 0–1
}

function masteryColour(m: number): string {
  if (m >= 0.8) return "bg-primary text-primary-foreground";
  if (m >= 0.4) return "bg-yellow-400 text-yellow-900";
  return "bg-muted text-muted-foreground";
}

export function ReceiptsSkillCoverage({ skills }: { skills: SkillItem[] }) {
  if (skills.length === 0) {
    return (
      <Card>
        <CardContent className="p-4 text-sm text-muted-foreground">
          No skills touched this week.
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Skills this week</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2 pb-4">
        {skills.map((s) => (
          <span
            key={s.id}
            className={cn("rounded-full px-2.5 py-0.5 text-xs font-medium", masteryColour(s.mastery))}
            title={`Mastery: ${Math.round(s.mastery * 100)}%`}
          >
            {s.name}
          </span>
        ))}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 4: Playwright verify + commit**

```bash
# browser_navigate /receipts
# browser_snapshot — skill badges render with mastery colours
# commit: feat(receipts): 3B-76 concept coverage skill badges
```

---

## Task 3: #79 Portfolio items this week

**Critic check:** Students complete exercises and forget them. Surfacing this week's portfolio items reminds them of concrete output.

**Files:**
- Modify: `backend/app/api/v1/routes/receipts.py`
- Modify: `frontend/src/app/(portal)/receipts/page.tsx`

- [ ] **Step 1: Claim #79**

- [ ] **Step 2: Add portfolio_items to receipts response**

In `routes/receipts.py`, query `ExerciseSubmission` for the current user this week where `passed = True`:

```python
from app.models.exercise_submission import ExerciseSubmission
from app.models.exercise import Exercise

week_start = datetime.now(UTC) - timedelta(days=7)
result = await db.execute(
    select(ExerciseSubmission, Exercise)
    .join(Exercise, ExerciseSubmission.exercise_id == Exercise.id)
    .where(
        ExerciseSubmission.user_id == current_user.id,
        ExerciseSubmission.created_at >= week_start,
        ExerciseSubmission.passed == True,  # noqa: E712
    )
    .order_by(ExerciseSubmission.created_at.desc())
)
portfolio_items = [
    {"id": str(sub.id), "exercise_title": ex.title, "submitted_at": sub.created_at.isoformat()}
    for sub, ex in result.all()
]
```

Log: `log.info("receipts.portfolio_items_computed", user_id=str(current_user.id), count=len(portfolio_items))`

- [ ] **Step 3: Add portfolio section to receipts/page.tsx**

```tsx
{receipts.portfolio_items?.length > 0 && (
  <section>
    <h2 className="mb-2 text-sm font-semibold">Completed this week</h2>
    <ul className="space-y-1">
      {receipts.portfolio_items.map((item) => (
        <li key={item.id} className="flex items-center gap-2 text-sm">
          <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
          {item.exercise_title}
        </li>
      ))}
    </ul>
  </section>
)}
```

- [ ] **Step 4: Playwright verify + commit**

```bash
# commit: feat(receipts): 3B-79 portfolio items this week
```

---

## Task 4: #81 Reflection aggregation

**Critic check:** Students can't see their mood patterns. Aggregated reflections make emotional trends visible.

**Files:**
- Modify: `backend/app/services/receipts_service.py`
- Modify: `backend/app/api/v1/routes/receipts.py`
- Modify: `frontend/src/app/(portal)/receipts/page.tsx`

- [ ] **Step 1: Claim #81**

- [ ] **Step 2: Write test for aggregate_reflections**

```python
# In test_receipts_service.py — add:
def test_aggregate_reflections_dominant() -> None:
    moods = ["good", "good", "rough", "good", "ok"]
    result = aggregate_reflections(moods)
    assert result["dominant_mood"] == "good"
    assert result["mood_counts"]["good"] == 3

def test_aggregate_reflections_empty() -> None:
    result = aggregate_reflections([])
    assert result["dominant_mood"] == "none"
```

- [ ] **Step 3: Run tests — confirm pass** (function already implemented in Task 1)

```bash
uv run pytest tests/test_services/test_receipts_service.py -v
```

- [ ] **Step 4: Add reflections to receipts route**

Query this week's reflections for the user, pass moods to `aggregate_reflections`:

```python
from app.services.receipts_service import aggregate_reflections
from app.models.reflection import Reflection

refl_result = await db.execute(
    select(Reflection.mood)
    .where(Reflection.user_id == current_user.id, Reflection.created_at >= week_start)
)
moods = [r[0] for r in refl_result.all() if r[0]]
reflection_summary = aggregate_reflections(moods)
```

- [ ] **Step 5: Add mood summary to receipts/page.tsx**

```tsx
{receipts.reflection_summary && (
  <div className="rounded-md bg-muted/50 px-4 py-3 text-sm">
    <span className="font-medium">This week's mood: </span>
    <span className="capitalize">{receipts.reflection_summary.dominant_mood}</span>
    {" · "}
    <span className="text-muted-foreground">
      {Object.entries(receipts.reflection_summary.mood_counts)
        .map(([mood, count]) => `${mood}: ${count}`)
        .join(", ")}
    </span>
  </div>
)}
```

- [ ] **Step 6: Playwright verify + commit**

```bash
# commit: feat(receipts): 3B-81 reflection aggregation summary
```

---

## Task 5: #82 Time investment chart

**Critic check:** Students can't see how much time they're putting in. A visual chart makes effort legible.

**Files:**
- Modify: `backend/app/api/v1/routes/receipts.py`
- Create: `frontend/src/components/features/receipts-time-chart.tsx`

- [ ] **Step 1: Claim #82**

- [ ] **Step 2: Add daily time data to receipts route**

Use `agent_actions.created_at` as a proxy for active minutes (1 action ≈ 5 min of engagement). Group by day for the past 7 days:

```python
from sqlalchemy import cast, Date as SADate

time_result = await db.execute(
    select(
        cast(AgentAction.created_at, SADate).label("day"),
        func.count(AgentAction.id).label("actions"),
    )
    .where(
        AgentAction.student_id == str(current_user.id),
        AgentAction.created_at >= week_start,
    )
    .group_by("day")
    .order_by("day")
)
daily_activity = [
    {"day": str(row.day), "minutes": row.actions * 5}
    for row in time_result.all()
]
```

- [ ] **Step 3: Create receipts-time-chart.tsx**

Check if `recharts` is in `frontend/package.json`:

```bash
grep recharts frontend/package.json
```

**If recharts is available:**

```tsx
// frontend/src/components/features/receipts-time-chart.tsx
"use client";

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface DayData { day: string; minutes: number }

export function ReceiptsTimeChart({ data }: { data: DayData[] }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Time this week</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={120}>
          <BarChart data={data}>
            <XAxis dataKey="day" tick={{ fontSize: 10 }} />
            <YAxis unit="m" tick={{ fontSize: 10 }} />
            <Tooltip formatter={(v) => [`${v} min`, "Active time"]} />
            <Bar dataKey="minutes" fill="hsl(var(--primary))" radius={[4,4,0,0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
```

**If recharts is NOT available (CSS bars):**

```tsx
export function ReceiptsTimeChart({ data }: { data: DayData[] }) {
  const max = Math.max(...data.map((d) => d.minutes), 1);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Time this week</CardTitle>
      </CardHeader>
      <CardContent className="flex items-end gap-1 pb-4" style={{ height: 100 }}>
        {data.map((d) => (
          <div key={d.day} className="flex flex-1 flex-col items-center gap-1">
            <div
              className="w-full rounded-t bg-primary"
              style={{ height: `${(d.minutes / max) * 64}px` }}
              title={`${d.minutes} min`}
            />
            <span className="text-[10px] text-muted-foreground">
              {new Date(d.day).toLocaleDateString("en", { weekday: "short" })}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 4: Playwright verify + commit**

```bash
# browser_navigate /receipts
# browser_snapshot — bar chart renders for each day
# commit: feat(receipts): 3B-82 time investment chart
```

---

## Task 6: #83 Next-week suggestion

**Critic check:** Students finish the week and don't know what to do next. One concrete suggestion converts receipt-reading into action.

**Files:**
- Modify: `backend/app/api/v1/routes/receipts.py`
- Modify: `frontend/src/app/(portal)/receipts/page.tsx`

- [ ] **Step 1: Claim #83**

- [ ] **Step 2: Add next-week suggestion to receipts route**

Use a deterministic rule (no LLM) for cost control: find the skill with lowest mastery that has been touched in the last 30 days (active but weak):

```python
from app.models.user_skill_state import UserSkillState
from app.models.skill import Skill

suggestion_result = await db.execute(
    select(Skill.name, UserSkillState.mastery)
    .join(UserSkillState, UserSkillState.skill_id == Skill.id)
    .where(
        UserSkillState.user_id == current_user.id,
        UserSkillState.last_practiced_at >= datetime.now(UTC) - timedelta(days=30),
        UserSkillState.mastery < 0.8,
    )
    .order_by(UserSkillState.mastery.asc())
    .limit(1)
)
row = suggestion_result.first()
next_week_suggestion = (
    {"skill_name": row.name, "current_mastery": round(row.mastery, 2)}
    if row else None
)
log.info("receipts.suggestion_generated", user_id=str(current_user.id), has_suggestion=row is not None)
```

- [ ] **Step 3: Add suggestion card to receipts/page.tsx**

```tsx
{receipts.next_week_suggestion && (
  <div className="rounded-md border border-primary/30 bg-primary/5 p-4">
    <p className="text-sm font-medium text-primary">Next week: focus on</p>
    <p className="mt-1 text-base font-semibold">
      {receipts.next_week_suggestion.skill_name}
    </p>
    <p className="text-xs text-muted-foreground">
      Current mastery: {Math.round(receipts.next_week_suggestion.current_mastery * 100)}%
    </p>
  </div>
)}
```

- [ ] **Step 4: Playwright verify + commit**

```bash
# browser_navigate /receipts
# browser_snapshot — suggestion card renders
# Edge case: new user with no skill states → no suggestion card (graceful)
# commit: feat(receipts): 3B-83 next-week skill suggestion
```

---

## Final checks

```bash
cd /mnt/e/Apps/pae_platform/wt/receipts/backend
uv run pytest -x && uv run mypy app/ && uv run ruff check .

cd /mnt/e/Apps/pae_platform/wt/receipts/frontend
pnpm tsc --noEmit && pnpm lint && pnpm test
```
