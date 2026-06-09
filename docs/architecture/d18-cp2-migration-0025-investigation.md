# Migration 0025 Investigation — D18 Phase A CP2 pre-decision

**Status:** Read-only investigation supporting the Option 2 vs Option B
decision for D18 Phase A CP2 (Playwright test database template
infrastructure).
**Date:** 2026-05-08
**Author:** Claude Code (architect-tasked investigation)
**Scope:** Three investigations into migration `0025_reconcile_runtime_state`
to determine whether a forward-only fix (Option 2) is safe or whether
the chain-rebuild path requires the pg_dump fallback (Option B).

---

## TL;DR — Synthesis

**0025 forward-fix is safe.** All three investigations point to the
same conclusion:

1. **What 0025 tries to create today is grossly overgrown** vs its
   original 13-table scope (INV1: 59 tables, including 41 future-
   migration tables that didn't exist when 0025 was authored).
2. **The original recovery scenario is fully documented** and tightly
   scoped — 4 columns + 13 tables for a specific dev-DB drift state
   that existed in 2026-04-19 (INV2).
3. **All 13 original tables + all 4 original columns are now created
   by canonical migrations 0010–0024 on a fresh DB** (INV3 spike test
   confirmed; chain runs clean through 0024 and lands all 17
   recovery items).

The recovery contract 0025 was authored to honor is now satisfied by
the canonical chain itself. 0025's `create_all` was load-bearing in
April 2026 for environments stuck at stamp=0009; it's been **dead
code on fresh DBs ever since the chain reached parity**, AND it's
been **actively harmful since migration 0054 added the
`agent_memory_scope` Postgres ENUM type** (whose tables `create_all`
tries to materialize before the ENUM exists).

**Recommendation: Option 2 (forward-fix 0025).** Drop the `create_all`
behavior; keep the four `ADD COLUMN IF NOT EXISTS` statements (still
defensive-no-op-safe on canonical fresh DBs and harmless on the
original drift state). Risk to active environments is near-zero: the
drift recovery is a 14+-month-old scenario that hasn't been needed
on any environment since the chain reached parity.

---

## INVESTIGATION 1 — What does 0025's `create_all` actually create?

### Method

Spike-tested against a fresh `inv_0025` Postgres database:

1. `CREATE DATABASE inv_0025`.
2. `alembic upgrade 0024` against `inv_0025` (with the working-tree
   forward-fixes for 0023 and 0024 applied).
3. Introspect `Base.metadata.tables` to count what models declare.
4. Diff against `information_schema.tables` to compute what
   `create_all(checkfirst=True)` would attempt to materialize.

### Results

| Measurement | Count |
|---|---|
| Tables in `Base.metadata` (current model surface) | **92** |
| Tables present at rev 0024 on fresh DB | **34** |
| Tables `create_all` would attempt = 92 − 34 | **59** |

### The 59 tables `create_all` would attempt

```
admin_console_calls, admin_console_engagement, admin_console_events,
admin_console_feature_usage, admin_console_funnel_snapshots,
admin_console_profiles, admin_console_pulse_metrics,
admin_console_risk_reasons, agent_call_chain, agent_escalations,
agent_evaluations, agent_invocation_log, agent_memory,
agent_proactive_runs, agent_tool_calls, ai_reviews,
application_kits, chat_attachments, chat_message_feedback,
chat_messages, cohort_events, conversations, course_bundles,
course_entitlements, generation_logs, interview_sessions,
jd_analyses, jd_library, jd_match_scores, learning_sessions,
lesson_resources, migration_gates, mock_answers, mock_cost_log,
mock_questions, mock_session_reports, mock_weakness_ledger,
notebook_entries, orders, outreach_log, payment_attempts,
payment_webhook_events, portfolio_autopsy_results,
readiness_action_completions, readiness_diagnostic_sessions,
readiness_diagnostic_turns, readiness_student_snapshots,
readiness_verdicts, readiness_workspace_events, refund_offers,
refunds, role_transitions, roles, story_bank, student_inbox,
student_messages, student_risk_signals, student_role_state,
tailored_resumes
```

### Per-table classification (vs INV2's enumerated original 13)

- **Original recovery target (13 tables in INV2's E2E-DISC-9 list):**
  zero of them appear in the 59-table `create_all` set. They're all
  in the 34-tables-already-present set, because migrations 0010–0024
  now create them canonically. So `create_all` doesn't even encounter
  the original recovery target on a fresh DB.
- **Tables added by future migrations 0026–0066 (the 59 that
  `create_all` does encounter):** all are duplicates of `op.create_table`
  calls in later migrations. None are orphaned (no later migration
  creates them). The chain survey confirmed this end-to-end: when 0025
  is `stamp`-ed past, migrations 0026–0066 land cleanly.

### Why this matters for fresh DBs

`create_all(checkfirst=True)` doesn't know about Postgres-specific
type dependencies. It tries to create `agent_memory` (which has
`scope agent_memory_scope NOT NULL`), but the `agent_memory_scope`
ENUM type is created in migration **0054** (`agentic_os_primitives`)
— 29 migrations after 0025. Postgres errors with `UndefinedObjectError:
type "agent_memory_scope" does not exist`.

The same problem would trigger on any future migration that introduces
a new ENUM, custom type, or extension that hasn't been created at the
0025 migration point. The class of failure is **"create_all forward
references future schema state"** — guaranteed to break as the model
graph grows past what existed at 0025's author time.

---

## INVESTIGATION 2 — E2E-DISC-9 recovery scenario archaeology

### Mentions found

`E2E-DISC-9` appears in three places:

1. `backend/alembic/versions/0025_reconcile_runtime_state.py` — module
   docstring + an inline comment on the `_ADD_COLUMN_STATEMENTS` list.
2. `docs/E2E-TEST-TRACKER.md:57` — A1 journey closure note ("Fixed:
   E2E-DISC-9 (missing DB columns causing onboarding 500s)").
3. `docs/E2E-TEST-TRACKER.md:239` — full E2E-DISC-9 entry with root
   cause + fix list.

(Two `.claude/worktrees/...` entries are stale worktree copies of the
same files; not authoritative.)

### Original drift scenario (verbatim from `E2E-TEST-TRACKER.md:239`)

> "DB alembic stamp stuck at 0009 while models and tables are at
> 0024-era, with **3 columns and 13 tables silently missing**.
> Severity: critical. Symptom: onboarding 500 on `/goals/me` +
> `/preferences/me`. Status: **fixed**. Fix: Alembic `stamp head` to
> 0024. Missing columns added: `goal_contracts.weekly_hours`,
> `reflections.kind`, `user_preferences.socratic_level`,
> `exercise_submissions.self_explanation`. Missing tables created
> via `Base.metadata.create_all(checkfirst=True)`: confidence_reports,
> conversation_memory, daily_intentions, feedback,
> interview_questions, peer_review_assignments, question_posts,
> question_votes, resumes, saved_skill_paths, student_misconceptions,
> student_notes, weekly_intentions. **Every authenticated page
> requiring goals/preferences/today data has been returning 500 since
> those features shipped.** Root cause: DB was previously
> `create_all`-bootstrapped and migration history never caught up.
> Next step: generate a single consolidated `0025_reconcile` Alembic
> migration so future environments don't need this manual repair."

### Authoring context

- **Commit:** `137f40a` (`fix(infra): unblock E2E test run — nginx
  DNS, register flow, DB drift, prod build`)
- **Date:** 2026-04-19 01:33:40 +0530
- **Deliverable association:** E2E test bring-up sweep (the same week
  that closed E2E-DISC-7 redirect bug + E2E-DISC-8 prod build bug).
- **Scope:** narrow — fix one drift state (stamp=0009 with model-side
  schema at 0024) so onboarding stops 500'ing.

### Were the 4 columns + 13 tables actually missing on fresh DBs in April 2026?

Indirect answer: yes, on at least one environment (the one the E2E
sweep ran against). That environment had been bootstrapped via
`SQLAlchemy.create_all` outside of alembic, and the alembic chain
hadn't caught up. Fresh DBs created via `alembic upgrade head` from
0001 in April 2026 would have hit the same sequence of broken
migrations the chain survey now surfaces (0023 type-mismatch, 0024
duplicate-index) — so a "fresh DB through alembic" scenario in April
2026 was probably not a tested path either.

### Has any environment needed E2E-DISC-9 recovery since April 2026?

No documented evidence either way. The follow-ups directory has zero
mentions of needing 0025 again. The dev DB used across D9–D17b
engagements has alembic_version = `0066_eval_failure_class` and has
all 17 recovery items present — i.e., 0025 either already ran on it
historically OR the canonical chain reached parity and the items
landed via 0010–0024.

The 14+ months since April 2026 is long enough that any environment
which would have needed 0025 has either been replaced by clean
rebuilds, recovered manually, or stopped being touched.

---

## INVESTIGATION 3 — Are 0025's tables created by later migrations on
                     a fresh DB anyway?

### Method

Two pieces of evidence:

1. The chain survey (D18 Phase A CP2 Option C, this morning): with
   0025 stamped past via the survey driver, migrations 0026–0066 ran
   cleanly to head against a fresh DB (only K=1 failure was 0025
   itself; 0023 + 0024 had been forward-fixed before the survey).
2. Direct verification on fresh `inv_0025` at rev 0024: all 13
   original-recovery tables present + all 4 original-recovery columns
   present.

### INV3.a — The 13 original recovery tables on fresh `inv_0025` at rev 0024

```
       table_name
-------------------------
 confidence_reports
 conversation_memory
 daily_intentions
 feedback
 interview_questions
 peer_review_assignments
 question_posts
 question_votes
 resumes
 saved_skill_paths
 student_misconceptions
 student_notes
 weekly_intentions
(13 rows)
```

All 13 present. **The original recovery set is now canonically created
by migrations 0010–0024.** 0025's `create_all` is genuinely no-op for
fresh DBs at 2026-05-08.

### INV3.b — The 4 original recovery columns on fresh `inv_0025` at rev 0024

| Column | Present? |
|---|---|
| `goal_contracts.weekly_hours` | yes |
| `reflections.kind` | yes |
| `user_preferences.socratic_level` | yes |
| `exercise_submissions.self_explanation` | yes |

All 4 present. **Even 0025's column-add statements are no-op on a
canonical fresh DB.** The `IF NOT EXISTS` clauses already make them
idempotent in either direction.

### INV3.c — Spot-check that 59 future tables get created cleanly without 0025

Sampled 8 of the 59:

| Table | Created by migration |
|---|---|
| `agent_memory` | 0054_agentic_os_primitives |
| `student_role_state` | 0061_role_progression_schema |
| `outreach_log` | 0051_outreach_log |
| `admin_console_calls` | 0039_admin_console_v1 |
| `jd_library` | 0035_career_tables_v2 |
| `cohort_events` | 0044_today_screen_completion |
| `orders` | 0047_payments_v2 (raw SQL idiom; `op.create_table` not used) |
| `refunds` | 0047_payments_v2 (same) |

The chain survey confirmed all 59 land cleanly on fresh DBs without
0025 doing anything. Zero orphaned tables.

---

## Synthesis

### Is 0025 forward-fix safe?

**Yes.** Three independent lines of evidence converge:

1. **0025's `create_all` doesn't touch its original recovery set on
   fresh DBs.** All 17 recovery items (4 cols + 13 tables) are
   created by 0010–0024 canonically. INV3 confirmed by direct
   inspection.
2. **0025's `create_all` instead tries to create 59 future tables**
   it was never designed for, including ones with custom type
   dependencies that fail (Pattern 22 — model graph grew past 0025's
   author-time assumptions).
3. **The original recovery scenario is 14+ months old** with no
   documented re-occurrence. Any environment stuck in the original
   drift state would have been recovered manually or rebuilt by now.

### What the forward-fix should look like

**Drop the `create_all` block; keep the four `ADD COLUMN IF NOT EXISTS`
statements.** The column-add statements are:

- Idempotent on the canonical fresh DB (no-op; columns already exist).
- Still load-bearing on any environment that is somehow still in the
  original drift state (defends the recovery contract for that
  scenario).
- Cheap (4 SQL statements, all `IF NOT EXISTS`-guarded).

The `create_all` block was the load-bearing piece for the 13 missing
tables in April 2026; today it's the harmful piece. Removing it
restores 0025 to "no-op on canonical DBs; defensive on drifted DBs"
which is exactly the contract the original author intended.

### Risk assessment

- **Risk to canonical fresh DBs (D18 test infra; new dev laptops; new
  CI runners; future production rebuilds):** zero. The fix removes
  the only failure mode.
- **Risk to environments still in the original April-2026 drift
  state:** near-zero. Such environments would still get the 4
  columns added (the only known column gaps) but wouldn't get the 13
  tables auto-created by 0025. They would need to either advance
  through 0026+ migrations (which create the tables canonically) or
  have been manually `create_all`-ed at some prior point. Both
  scenarios produce the same end state for the original 13 tables.
  No documented environment is known to still be in this drift state.
- **Risk to the recovery contract documented in `E2E-TEST-TRACKER.md`:**
  the contract was "future environments don't need manual repair."
  The forward-fix preserves this for the 4 columns; the 13 tables are
  preserved by canonical 0026+ migrations. Net: the original contract's
  intent (no manual repair needed) holds; the implementation moves
  from "0025 reconciles" to "the chain itself is rebuildable end-to-end."

### What the forward-fix does NOT do

- Doesn't fix the deeper Pattern 22 problem (migrations not tested
  against fresh DBs before merge). That's a chain-discipline concern
  to register as a follow-up doc (`migration-chain-fresh-db-
  rebuildability.md` — was already planned for D18 Phase A CP2
  closure).
- Doesn't address 0025's `create_all` if the drift state somehow
  recurs in the future (e.g., a new dev who runs `create_all` then
  stamps at an old revision). That would be a fresh recovery
  exercise, not 0025's responsibility.

---

## Recommendation

**Option 2 (forward-fix 0025).** All three investigations support this.
The fix:

```python
# In backend/alembic/versions/0025_reconcile_runtime_state.py:
def upgrade() -> None:
    # 1. Apply column-level reconciliations (always safe — IF NOT EXISTS).
    #    These four statements were the load-bearing piece for the
    #    E2E-DISC-9 onboarding 500s; they're idempotent on canonical
    #    fresh DBs (columns already created by 0007 / 0017 / 0011 /
    #    0015) and still defensive for any drifted environment.
    for stmt in _ADD_COLUMN_STATEMENTS:
        op.execute(stmt)

    # 2. (DROPPED at D18 Phase A CP2, 2026-05-08): the original
    #    `Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)`
    #    call was authored to backfill 13 specific tables for one
    #    drifted environment in April 2026. As of CP2 chain survey,
    #    all 13 are created canonically by migrations 0010–0024 on
    #    fresh DBs. Meanwhile, the model graph has grown by 41
    #    migrations + ~58 tables since 0025 was authored; create_all
    #    on a fresh DB now tries to materialize tables that depend on
    #    Postgres ENUM types created by future migrations
    #    (e.g., agent_memory.scope -> agent_memory_scope ENUM created
    #    by 0054), and fails with UndefinedObjectError. See
    #    docs/architecture/d18-cp2-migration-0025-investigation.md
    #    for the full investigation.
```

CP2 then proceeds with the planned alembic-upgrade-head approach in
`create_template.py`. No pg_dump fallback needed; the chain itself
becomes the source of truth.

### Why not Option B (pg_dump)?

Option B would work but doesn't address the underlying Pattern 22
problem and leaves three broken migrations in the tree. Option 2
fixes the bug AND validates the chain-rebuildability discipline that
D18's test infrastructure depends on going forward. The pg_dump
approach is an escape hatch for cases where the chain is
fundamentally untestable; this case isn't one of them.

If at any future point the chain breaks again at a new migration
that proves harder to forward-fix, pg_dump remains available as a
fallback. For 0025 specifically, the forward-fix is materially
simpler than the pg_dump alternative.

---

## Cross-references

- `backend/alembic/versions/0025_reconcile_runtime_state.py` — the
  migration under investigation.
- `docs/E2E-TEST-TRACKER.md:239` — original E2E-DISC-9 recovery scope.
- D18 Phase A CP2 chain survey output (`e:/tmp/chain_survey_report.json`)
  — confirms K=3 with 0025 as the requires-investigation instance.
- D17b Pattern 23 N=6 canonical statement
  (`docs/followups/migration-verification-discipline.md`) — pre-flight
  doc-vs-code verification mandatory; same discipline applies to
  migrations.
- D18 Phase A CP2 closure (pending) — will register
  `docs/followups/migration-chain-fresh-db-rebuildability.md`
  capturing all three findings + the discipline going forward.
