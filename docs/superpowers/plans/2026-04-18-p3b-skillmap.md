# Phase 3B — Skill Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 6 skill-map enhancements (#21 cluster-collapse, #22 mastery legend, #24 path saving, #25 side-panel search, #26 prereq warning, #27 progress rings) that make the skill graph the student's primary orientation tool.

**Architecture:** All work is frontend-only except #24 (path saving adds a backend endpoint). Components live in `frontend/src/components/features/skill-map/`. The map page is a client component — all enhancements hook into the existing `SkillMap` + `SkillNodeCard` + `SkillSidePanel` component tree. Backend for #24 uses the existing `skill_path_service.py` + `skill_path.py` route pattern.

**Tech Stack:** React (client components), D3 layout (existing `layout.ts`), shadcn/ui, React Query hooks in `lib/hooks/use-skills.ts`, FastAPI route extension for #24.

---

## Worktree & pre-work

Working directory for all steps: `/mnt/e/Apps/pae_platform/wt/skillmap`

```bash
cd /mnt/e/Apps/pae_platform/wt/skillmap
git pull --rebase origin main
```

---

## File structure

**Modify (existing):**
- `frontend/src/components/features/skill-map/skill-map.tsx` — #21, #22
- `frontend/src/components/features/skill-map/skill-node-card.tsx` — #26, #27
- `frontend/src/components/features/skill-map/skill-side-panel.tsx` — #25
- `frontend/src/lib/hooks/use-skills.ts` — #24 (add save-path query)
- `backend/app/api/v1/routes/skill_path.py` — #24 (add save endpoint)
- `backend/app/services/skill_path_service.py` — #24 (add save logic)
- `docs/ROADMAP-P3-CRITIC.md` — claim/done markers

**Create (new):**
- `frontend/src/components/features/skill-map/mastery-legend.tsx` — #22
- `frontend/src/components/features/skill-map/cluster-collapse-button.tsx` — #21
- `backend/app/schemas/skill_path.py` — #24 (SavedPath request/response)
- `backend/tests/test_services/test_skill_path_save.py` — #24 unit test

---

## Task 1: #21 Cluster collapse

**Critic check:** Students with 30+ skills on screen quit. Collapsing topic clusters reduces cognitive load → more students attempt the map.

**Files:**
- Modify: `frontend/src/components/features/skill-map/skill-map.tsx`
- Create: `frontend/src/components/features/skill-map/cluster-collapse-button.tsx`

- [ ] **Step 1: Claim ticket in tracker**

```bash
cd /mnt/e/Apps/pae_platform/wt/skillmap
# Edit docs/ROADMAP-P3-CRITIC.md line:
# - [ ] #21 Cluster collapse
# → - [~] #21 Cluster collapse (p3b, feat/p3b-skillmap)
git add docs/ROADMAP-P3-CRITIC.md
git commit -m "chore(tracker): claim 3B-#21"
```

- [ ] **Step 2: Read existing skill-map.tsx**

```bash
cat frontend/src/components/features/skill-map/skill-map.tsx
```

Understand: how skills are rendered, what state exists, how `useSkills()` data flows in.

- [ ] **Step 3: Create cluster-collapse-button.tsx**

```tsx
// frontend/src/components/features/skill-map/cluster-collapse-button.tsx
"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ClusterCollapseButtonProps {
  clusterId: string;
  label: string;
  collapsed: boolean;
  skillCount: number;
  onToggle: (clusterId: string) => void;
}

export function ClusterCollapseButton({
  clusterId,
  label,
  collapsed,
  skillCount,
  onToggle,
}: ClusterCollapseButtonProps) {
  return (
    <Button
      variant="ghost"
      size="sm"
      className="flex items-center gap-1 text-xs font-medium text-muted-foreground"
      onClick={() => onToggle(clusterId)}
      aria-label={`${collapsed ? "Expand" : "Collapse"} ${label} cluster`}
    >
      {collapsed ? (
        <ChevronRight className="h-3 w-3" />
      ) : (
        <ChevronDown className="h-3 w-3" />
      )}
      {label}
      <span className="ml-1 rounded-full bg-muted px-1.5 py-0.5 text-[10px]">
        {skillCount}
      </span>
    </Button>
  );
}
```

- [ ] **Step 4: Add collapsed state to skill-map.tsx**

Add `collapsedClusters` state and toggle handler. Wrap cluster sections to hide skills when collapsed. The exact implementation depends on how clusters are currently identified in the data (check the `useSkills()` return shape and `layout.ts`). The state shape:

```tsx
const [collapsedClusters, setCollapsedClusters] = useState<Set<string>>(new Set());

const toggleCluster = (clusterId: string) => {
  setCollapsedClusters((prev) => {
    const next = new Set(prev);
    if (next.has(clusterId)) {
      next.delete(clusterId);
    } else {
      next.add(clusterId);
    }
    return next;
  });
};
```

Filter skills before rendering:

```tsx
const visibleSkills = skills.filter(
  (skill) => !collapsedClusters.has(skill.cluster_id ?? "")
);
```

- [ ] **Step 5: Playwright verify**

```bash
# Frontend already running on :3000, backend on :8000
# Use Playwright MCP:
# 1. browser_navigate to http://localhost:3000/map
# 2. browser_snapshot — confirm cluster headers render with ChevronDown
# 3. browser_click cluster toggle — snapshot confirms skills hidden
# 4. browser_click again — snapshot confirms skills visible
# 5. browser_console_messages — no errors
# 6. browser_take_screenshot → .playwright-mcp/3b-21-cluster-collapse.png
# Edge case: single-skill cluster → toggle still works
# Edge case: all clusters collapsed → page is not blank (shows cluster headers)
```

- [ ] **Step 6: Commit with tracker update**

```bash
# Edit tracker: - [~] #21 → - [x] #21 Cluster collapse DONE (sha)
git add frontend/src/components/features/skill-map/
git add docs/ROADMAP-P3-CRITIC.md
git commit -m "feat(skillmap): 3B-21 cluster collapse toggle"
```

---

## Task 2: #22 Mastery legend

**Critic check:** Students can't interpret node colours → don't act on the map. A legend converts colours into actionable meaning.

**Files:**
- Create: `frontend/src/components/features/skill-map/mastery-legend.tsx`
- Modify: `frontend/src/components/features/skill-map/skill-map.tsx`

- [ ] **Step 1: Claim ticket**

```bash
# Edit tracker line for #22, commit as chore(tracker): claim 3B-#22
```

- [ ] **Step 2: Create mastery-legend.tsx**

```tsx
// frontend/src/components/features/skill-map/mastery-legend.tsx
const LEGEND_ITEMS = [
  { label: "Mastered", colorClass: "bg-primary" },
  { label: "In progress", colorClass: "bg-yellow-400" },
  { label: "Not started", colorClass: "bg-muted" },
  { label: "Prerequisite gap", colorClass: "bg-destructive/60" },
] as const;

export function MasteryLegend() {
  return (
    <div className="flex flex-wrap gap-3 rounded-md border border-border bg-card px-3 py-2">
      {LEGEND_ITEMS.map(({ label, colorClass }) => (
        <div key={label} className="flex items-center gap-1.5">
          <span className={`h-3 w-3 rounded-full ${colorClass}`} aria-hidden />
          <span className="text-xs text-muted-foreground">{label}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Add legend to skill-map.tsx**

Import and render `<MasteryLegend />` in the page header area (above the graph canvas).

- [ ] **Step 4: Playwright verify + commit**

```bash
# browser_navigate /map, browser_snapshot confirms legend renders above graph
# browser_take_screenshot → .playwright-mcp/3b-22-mastery-legend.png
# commit: feat(skillmap): 3B-22 mastery legend
```

---

## Task 3: #24 Path saving

**Critic check:** Students find a path they like and lose it on refresh. Saving a path = students can commit to a learning sequence.

**Files:**
- Create: `backend/app/schemas/skill_path.py`
- Modify: `backend/app/services/skill_path_service.py`
- Modify: `backend/app/api/v1/routes/skill_path.py`
- Modify: `frontend/src/lib/hooks/use-skills.ts`
- Create: `backend/tests/test_services/test_skill_path_save.py`

- [ ] **Step 1: Claim ticket**

```bash
# Edit tracker line for #24, commit as chore(tracker): claim 3B-#24
```

- [ ] **Step 2: Write failing backend test**

```python
# backend/tests/test_services/test_skill_path_save.py
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.skill_path_service import save_skill_path, get_saved_skill_path

pytestmark = pytest.mark.asyncio

async def test_save_and_retrieve_skill_path(db_session: AsyncSession) -> None:
    user_id = uuid.uuid4()
    skill_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    await save_skill_path(db_session, user_id=user_id, skill_ids=skill_ids)
    result = await get_saved_skill_path(db_session, user_id=user_id)
    assert result is not None
    assert result.skill_ids == skill_ids

async def test_save_overwrites_existing_path(db_session: AsyncSession) -> None:
    user_id = uuid.uuid4()
    first = [uuid.uuid4()]
    second = [uuid.uuid4(), uuid.uuid4()]
    await save_skill_path(db_session, user_id=user_id, skill_ids=first)
    await save_skill_path(db_session, user_id=user_id, skill_ids=second)
    result = await get_saved_skill_path(db_session, user_id=user_id)
    assert result is not None
    assert result.skill_ids == second

async def test_get_path_returns_none_for_new_user(db_session: AsyncSession) -> None:
    result = await get_saved_skill_path(db_session, user_id=uuid.uuid4())
    assert result is None
```

- [ ] **Step 3: Run test — confirm failure**

```bash
cd /mnt/e/Apps/pae_platform/wt/skillmap/backend
uv run pytest tests/test_services/test_skill_path_save.py -v
```

Expected: ImportError or AttributeError — functions don't exist yet.

- [ ] **Step 4: Check existing skill_path_service.py for the pattern**

```bash
cat backend/app/services/skill_path_service.py | head -60
```

Understand existing imports and async session pattern.

- [ ] **Step 5: Create backend/app/schemas/skill_path.py**

```python
# backend/app/schemas/skill_path.py
import uuid
from pydantic import BaseModel

class SavedPathRequest(BaseModel):
    skill_ids: list[uuid.UUID]

class SavedPathResponse(BaseModel):
    user_id: uuid.UUID
    skill_ids: list[uuid.UUID]
```

- [ ] **Step 6: Add save/get functions to skill_path_service.py**

Check if a `UserSkillPath` or similar model exists. If not, store the path as JSON in `user_preferences.metadata` (JSONB field) to avoid a new migration:

```python
# Add to backend/app/services/skill_path_service.py
import uuid
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user_preferences import UserPreferences

log = structlog.get_logger()

async def save_skill_path(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    skill_ids: list[uuid.UUID],
) -> None:
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
    metadata = dict(prefs.metadata or {})
    metadata["saved_skill_path"] = [str(sid) for sid in skill_ids]
    prefs.metadata = metadata
    await db.commit()
    log.info("skillmap.path_saved", user_id=str(user_id), skill_count=len(skill_ids))

async def get_saved_skill_path(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> "SavedPathResponse | None":
    from app.schemas.skill_path import SavedPathResponse
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None or not (prefs.metadata or {}).get("saved_skill_path"):
        return None
    raw = prefs.metadata["saved_skill_path"]
    return SavedPathResponse(
        user_id=user_id,
        skill_ids=[uuid.UUID(s) for s in raw],
    )
```

**Note:** Check if `UserPreferences` has a `metadata` JSON column. If not, add to an existing JSONB/JSON field or add `saved_skill_path` as a proper column via Alembic. Do NOT create a new migration number — check the tracker's reservation (0010 is for meta, 0011 for career). If a migration is truly needed for path saving, ping before creating it.

- [ ] **Step 7: Run tests — confirm pass**

```bash
cd /mnt/e/Apps/pae_platform/wt/skillmap/backend
uv run pytest tests/test_services/test_skill_path_save.py -v
uv run mypy app/ && uv run ruff check .
```

Expected: 3 tests green, mypy clean.

- [ ] **Step 8: Add route endpoint to skill_path.py**

```python
# In backend/app/api/v1/routes/skill_path.py — add:
from app.schemas.skill_path import SavedPathRequest, SavedPathResponse
from app.services.skill_path_service import save_skill_path, get_saved_skill_path

@router.post("/me/path", status_code=204)
async def save_my_path(
    body: SavedPathRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await save_skill_path(db, user_id=current_user.id, skill_ids=body.skill_ids)

@router.get("/me/path", response_model=SavedPathResponse | None)
async def get_my_path(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavedPathResponse | None:
    return await get_saved_skill_path(db, user_id=current_user.id)
```

- [ ] **Step 9: Add useSavedPath hook to frontend**

```typescript
// In frontend/src/lib/hooks/use-skills.ts — add:
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export function useSavedSkillPath() {
  return useQuery({
    queryKey: ["skill-path", "saved"],
    queryFn: () => apiClient.get("/skill-path/me/path").then((r) => r.data),
  });
}

export function useSaveSkillPath() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (skillIds: string[]) =>
      apiClient.post("/skill-path/me/path", { skill_ids: skillIds }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skill-path", "saved"] }),
  });
}
```

- [ ] **Step 10: Add "Save path" button to skill-map.tsx**

Add a toolbar button that calls `useSaveSkillPath` with currently selected/highlighted skills.

- [ ] **Step 11: Playwright verify + commit**

```bash
# browser_navigate /map
# Select a few skills, click "Save path"
# browser_network_requests — confirm POST /skill-path/me/path returns 204
# Refresh page — browser_snapshot confirms path is restored
# commit: feat(skillmap): 3B-24 path saving via user_preferences metadata
```

---

## Task 4: #25 Skill side panel + search

**Critic check:** Students want to find a specific skill without scrolling the graph. Search = direct access.

**Files:**
- Modify: `frontend/src/components/features/skill-map/skill-side-panel.tsx`

- [ ] **Step 1: Claim ticket**

```bash
# Edit tracker for #25, commit claim
```

- [ ] **Step 2: Read existing skill-side-panel.tsx**

```bash
cat frontend/src/components/features/skill-map/skill-side-panel.tsx
```

- [ ] **Step 3: Add search input to side panel**

The panel already renders skill details. Add a search box at the top that filters the skill list (use existing `useSkills()` data). Pattern:

```tsx
const [query, setQuery] = useState("");
const filteredSkills = useMemo(
  () =>
    skills.filter((s) =>
      s.name.toLowerCase().includes(query.toLowerCase())
    ),
  [skills, query]
);
```

Add input:

```tsx
<input
  type="search"
  placeholder="Search skills…"
  value={query}
  onChange={(e) => setQuery(e.target.value)}
  className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm"
  aria-label="Search skills"
/>
```

When a result is clicked, pan/focus the map node (fire an `onSkillSelect` callback that the parent passes down).

- [ ] **Step 4: Playwright verify + commit**

```bash
# browser_navigate /map, open side panel
# browser_type in search input "python"
# browser_snapshot confirms filtered list
# browser_click result — confirms map focuses on that node
# commit: feat(skillmap): 3B-25 skill side panel search
```

---

## Task 5: #26 Prereq warning

**Critic check:** Students attempt skills they're not ready for and give up. A prereq warning sets correct expectations before they invest time.

**Files:**
- Modify: `frontend/src/components/features/skill-map/skill-node-card.tsx`

- [ ] **Step 1: Claim ticket**

- [ ] **Step 2: Read skill-node-card.tsx and skill edge data**

Check what data `SkillNodeCard` receives. Look at `useSkills()` to see if prerequisite edges are available. They come from `SkillEdge` model (the DB has `skill_edges` table with `source_id`, `target_id`).

- [ ] **Step 3: Add prereq warning badge**

If a skill node's prerequisites are not all mastered (mastery < 0.8 on any prereq skill), show a warning indicator:

```tsx
const hasUnmetPrereqs = prereqSkills.some((s) => (s.mastery ?? 0) < 0.8);

{hasUnmetPrereqs && (
  <span
    className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-yellow-400 text-[9px] font-bold text-yellow-900"
    title="Prerequisite skills not yet mastered"
    aria-label="Prerequisite skills not yet mastered"
  >
    !
  </span>
)}
```

In the side panel tooltip/popover: "You haven't mastered [Skill A] and [Skill B] yet — this skill may be harder."

- [ ] **Step 4: Playwright verify + commit**

```bash
# browser_navigate /map
# browser_snapshot — node with unmet prereqs shows yellow badge
# browser_click node — side panel shows prereq warning text
# commit: feat(skillmap): 3B-26 prereq warning on skill nodes
```

---

## Task 6: #27 Progress rings on nodes

**Critic check:** Students can't see their mastery at a glance. Progress rings make state scannable without clicking into each skill.

**Files:**
- Modify: `frontend/src/components/features/skill-map/skill-node-card.tsx`

- [ ] **Step 1: Claim ticket**

- [ ] **Step 2: Add SVG ring to skill node card**

```tsx
interface ProgressRingProps {
  progress: number; // 0–1
  size?: number;
}

function ProgressRing({ progress, size = 32 }: ProgressRingProps) {
  const r = (size - 4) / 2;
  const circumference = 2 * Math.PI * r;
  const filled = circumference * (1 - progress);
  return (
    <svg width={size} height={size} className="-rotate-90">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="currentColor"
        strokeWidth={3}
        className="text-muted"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="currentColor"
        strokeWidth={3}
        strokeDasharray={circumference}
        strokeDashoffset={filled}
        strokeLinecap="round"
        className="text-primary transition-all duration-500"
      />
    </svg>
  );
}
```

Wrap the skill node icon/label with this ring. Pass `progress={skill.mastery ?? 0}`.

- [ ] **Step 3: Run tests + playwright verify + commit**

```bash
cd /mnt/e/Apps/pae_platform/wt/skillmap/frontend
pnpm tsc --noEmit && pnpm lint && pnpm test
# browser_navigate /map
# browser_snapshot — nodes render with rings
# browser_take_screenshot → .playwright-mcp/3b-27-progress-rings.png
# commit: feat(skillmap): 3B-27 progress rings on skill nodes
```
