# D15 follow-up — legacy users.promoted_to_role reconciliation

**Status:** Open. Triage → D17 cleanup unless founder flags load-bearing.
**Created:** 2026-05-08 (D15 CP1 closure → CP2 entry).
**Cross-references:**
- `migration-verification-discipline.md` Pattern 22 (spec-vs-schema reconciliation)
- D15 prompt at `docs/claude-code-prompts/d15-prompt.md`

## What this is

The `users` table has carried two pre-existing columns since well before D15:

```python
# backend/app/models/user.py
promoted_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True
)
promoted_to_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
```

Inline comment on `promoted_at` says: *"Promotion gate — set once when the
student crosses ALL four rungs. Used to fire the takeover exactly once and
to render 'Promoted on …' copy."*

`promoted_to_role` is a free-text `String(128)` — no foreign key, no enum,
no relationship to the six-role identity sequence introduced in D15
(`python_developer → … → senior_genai_engineer`). The "four rungs"
reference suggests it was wired to a now-superseded readiness/promotion
flow, not the role progression D15 ships.

D15 CP1 deliberately did not touch these columns:

- The CP1 backfill (`0062_role_progression_backfill.py`) seeds every existing
  user at `python_developer` regardless of `promoted_to_role` value.
- Models for D15 (`Role`, `RoleTransition`, `StudentRoleState`) make zero
  reference to the legacy columns.
- CP2-CP5 prompt updates and tools treat `student_role_state` as the
  canonical platform-internal source of truth for "what role is this
  student in."

This means the two systems coexist. That's fine for v1 — but creates a
question that needs answering before D17 cleanup.

## The question

**What was `promoted_to_role` for, and is anything still reading it?**

Three possibilities:

1. **Dead column** — written by a flow that no longer fires; nothing reads
   it. Drop in D17 with a one-line schema migration.
2. **Frontend-display column** — frontend reads it for copy ("Promoted on
   …"). Migrate the read site to derive from `student_role_state`
   (`role_started_at` of the current role, or the latest entry in
   `transitions_completed`), then drop the columns.
3. **Load-bearing semantically distinct flow** — `promoted_to_role` tracks
   something orthogonal to the six-role sequence (e.g., external job
   placement post-graduation). Keep, document the distinction, ensure
   neither system shadows the other.

## How to triage

Quick scan to settle this:

```bash
# Code references
docker exec pae_platform-backend-1 sh -c \
  "grep -rn 'promoted_to_role\|promoted_at' /app/app /app/tests | head -50"

# Frontend references
grep -rn "promoted_to_role\|promotedToRole\|promoted_at\|promotedAt" \
  frontend/src | head -50

# Live data: what values does it actually hold?
docker exec pae_platform-db-1 psql -U postgres -d platform -c \
  "SELECT promoted_to_role, count(*) FROM users GROUP BY promoted_to_role ORDER BY count(*) DESC;"
```

If the data shows mostly NULL plus a handful of values that look like the
six-role slugs or close cousins, possibility 2 is likely. If values look
like external job titles ("Senior ML Engineer at <company>"),
possibility 3.

## D17 actions (assuming triage lands at possibility 1 or 2)

- If 1 (dead): write Alembic migration `00NN_drop_legacy_promoted_columns.py`
  removing `promoted_to_role` + `promoted_at` from `users`.
- If 2 (display): identify reader sites, migrate to `StudentRoleState`
  derivation, then drop columns in the same PR.
- If 3 (distinct): rename to disambiguate (`external_placement_role`?),
  document in `app/models/user.py`, and ensure D15 agents never confuse
  the two.

## Why this is in the followups doc, not blocking CP2

Pattern 22 (spec-vs-schema reconciliation) says: surface schema gaps at
CP1/CP2 pre-authoring. This followup is the surfacing.

CP2 reads from `course_entitlements`, `courses`, `lessons`, `exercises`
— not from `users.promoted_to_role`. The legacy column shadows nothing
in CP2's path. Deferring to D17 is safe.

If the founder reads this and recognises `promoted_to_role` as
load-bearing — surface immediately and we revisit before CP3.
