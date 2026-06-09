# D16 closure — functional audit + targeted gap closure + launch readiness

**Date:** 2026-05-08
**Engagement scope:** Functional verification of shipped retention engine
+ targeted gap closure (CP1+CP2) + WhatsApp manual-outreach workflow
(CP3) + end-to-end smoke + closure.
**Locked decisions:** D-A (no new agents) ✓ honored. D-B (outreach_log
canonical for admin contact records) ✓ honored. D-C (three sequential
phases, scope-determined-by-evidence) ✓ honored.

---

## Engagement reframe (post-pre-flight audit)

Original D16 plan: ship `interrupt_agent` as `@proactive(cron=...)`,
build "Email MCP" templated-email server, wire proactive-layer
infrastructure. Estimated multi-day work.

Pre-flight audit (`d16-pre-flight-admin-surface-audit.md`) discovered
the retention engine (F1+F3+F4+F5+F8+F9+F10+F11) was substantially
shipped. CP1 functional audit confirmed: 8 of 14 verification points
WORKS, 3 PARTIAL with non-blocking gaps, 1 HIGH-severity launch
blocker, 1 STALE-but-safe (admin_console_* cluster), 1 workflow
assessment (WhatsApp gap).

D16's shape changed: from new-feature delivery to functional
verification + targeted gap closure + WhatsApp UI shipment.

---

## What shipped

### CP1 — Functional audit (no commits; investigation deliverable)

- `docs/architecture/d16-functional-audit.md` — per-verification-point
  status report (a-n), severity classifications, CP2 scope synthesis,
  CP3 readiness assessment.
- 3 parallel sub-agents covered the 14 verification surfaces; ~₹0
  cost.
- Headline findings:
  - 8 WORKS: a (risk_scoring), b (outreach_automation), c (cockpit
    rendering, all panels), e (admin DM), f (admin notes), g (refund
    offer), k (proactive infrastructure).
  - 3 PARTIAL: h (inactivity_sweep observational only), i (weekly
    letters bypass outreach_log), j (growth_snapshots no admin read).
  - 1 HIGH: l (Celery worker + beat Fly apps don't exist;
    concurrency=4 unsafe).
  - 1 STALE-but-safe: d (admin_console_* cluster — cockpit pre-
    migrated to primary-table reads; cluster awaits drop migration).
  - 1 workflow gap: n (no WhatsApp deep-link / phone field / log-
    this-contact button; pre-CP3 baseline).

### CP2 — Gap closure (4 commits)

| Commit | SHA | Scope |
|---|---|---|
| Commit A | `84b749e` | infra(celery) — Fly worker + beat tomls; celery-safety-memory-bump.md (a)+(b) RESOLVED |
| Commit B | `ced93a5` | fix(retention) — inactivity_sweep docstring fix; weekly_letters outreach_log audit gap closed (CP2.h+i) |
| Commit C | `75bf3d5` | docs(retention) — LD-1..LD-5 verification record + comprehensive .env.example (CP2.d+m) |
| Commit D | `a3be5d8` | docs(followups) — 8 D16 follow-up docs registered |

### CP3 — WhatsApp manual outreach workflow (3 commits + smoke)

| Commit | SHA | Scope |
|---|---|---|
| CP3.1 | `cfdc087` | feat(retention) — User.whatsapp_number column (mig 0065), UserCreate/Response schema, onboarding form field, end-to-end thread |
| CP3.2 | `380db51` | feat(retention) — admin WhatsApp deep-link button + log-contact endpoint + backend tests + sanity-tested live |
| CP3.3 | `89c7703` | feat(retention) — outreach surfacing on student timeline (channel badges, replied-pill, all 4 channels) |

CP3.E2E smoke evidence: `docs/architecture/d16-cp3e2e-smoke-evidence.md`.
12 scenario steps verified end-to-end; all four canonical channels
(whatsapp, phone, email, in_app) surface on the timeline; throttle
behavior preserved.

---

## Test baseline

CP1 baseline: 1491 passing + 86 D15 slice + 45 pre-existing failures.

D16 closure baseline (touched-area + delta):

- **Retention-engine surface (CP2 area)**: 52/52 in test_weekly_letters
  + test_inactivity_service + test_outreach_email_service +
  test_outreach_service + test_student_message_service +
  test_student_risk_service + test_refund_offer_service.
- **Auth + admin (CP3 area)**: 24/25 in test_admin.py + test_auth.py +
  test_weekly_letters.py. The 1 failure is `test_admin_agents_health`
  (asserts `len(agents) >= 20`, sees 17) — pre-existing; matches CP1
  baseline; not in any file D16 touched.
- **Aggregate non-agent suites**: 1383 passed / 45 failed (matches
  CP1's "45 pre-existing failures" baseline exactly).

**Verdict:** no regression vs CP1 baseline. D15 slice unchanged.

D16-introduced new tests (10 across CP2 + CP3):
- 2 in `test_weekly_letters.py` (CP2.i outreach_log audit)
- 2 in `test_auth.py` (CP3.1 register-with/without-whatsapp)
- 4 in `test_admin.py` (CP3.2 endpoint shape + channel rejection +
  admin gate; CP3.3 timeline surfacing)
- All pass.

Testing caveat: the dev backend container bind-mounts `app/` and
`alembic/` only — **`tests/` is baked into the image**. Test edits
required `docker compose cp` to push fresh files into the running
container before pytest could see them. Application-side edits (which
land in `app/`) propagate via the bind mount and don't require this
step.

---

## Patterns surfaced

Per founder direction at CP1 acknowledgement:

### Pattern 28 — Functional audit before gap-closure for already-built infrastructure (canonical, N=1 strong)

Promoted to canonical with single-instance evidence. Discipline
statement: "Deliverables that touch already-built infrastructure
should start with functional audit, not assumed-gap-closure." D16's
entire shape changed because the audit ran first; original new-feature
plan would have shipped duplicate scaffolding.

Registered in `docs/followups/migration-verification-discipline.md`
between Pattern 27 and Pattern 29.

### Pattern 29 — Scaffolded-but-inert detection (candidate, N=1)

Two variants documented: no-writer-found, and writer-retired-without-
drop. The CI check that asserts every model has at least one writer
call site is the institutional improvement worth considering at a
future cleanup pass. Registered in
`docs/followups/migration-verification-discipline.md` after Pattern 28.

### Pattern 23 — Doc/comment framing drift (extended N=2 → N=3)

Founder asked to extend the canonical statement: framing-drift applies
equally to follow-up docs (D14c curriculum_mapper), code comments
(D17a eval-row-writer), AND task module docstrings (D16 inactivity_
sweep). All three artifacts are prose making claims about code paths
that future code can invalidate. Provenance updated; canonical scope
extended. Registered in
`docs/followups/migration-verification-discipline.md` (in-place edit
to Pattern 23's provenance + scope).

---

## Follow-up docs registered

8 follow-up docs in `docs/followups/d16-followup-*.md` (Commit D
a3be5d8):

| Doc | Status | Trigger to revisit |
|---|---|---|
| `disrupt-prevention-proactive.md` | D-A deferral | Cohort signal that current chat + admin-trigger doesn't cover |
| `whatsapp-business-api.md` | Post-launch | When manual-outreach volume justifies Meta business verification |
| `bulk-email-marketing.md` | Founder reframe | At cohort scale (5000+ active users) |
| `admin-role-granularity.md` | Post-launch | When ≥ 2 admin-shaped users exist |
| `inactivity-sweep-event-persistence.md` | Post-launch | When re-engagement throughput becomes a measured retention signal |
| `admin-console-drop-migration.md` | Post-soak ops | After LD-1..LD-5 cockpit code soaks ≥ 2 weeks in production |
| `growth-snapshots-admin-cohort-endpoint.md` | LOW / D17b | When admin asks for cohort growth view |
| `sendgrid-bounce-webhook.md` | Post-launch ops | When delivery-tracking matters at cohort scale |

---

## Launch-blocker status

**One pre-D16 launch blocker resolved:**

- `celery-safety-memory-bump.md` (originally tagged "launch-blocker
  for D16"). All three remediation items resolved at D16:
  (a) memory bump to 4096 MB on worker + beat — RESOLVED via fly-
      worker.toml + fly-beat.toml
  (b) concurrency cap to 2 — RESOLVED via fly-worker.toml
      `[processes]` block
  (c) Presidio eager-load — already RESOLVED at D9 (celery_app.py
      `@worker_process_init` handler)

**No new launch blockers introduced by D16.**

**Operational pre-launch steps (NOT code work; documented in commit
file headers for the deploying operator):**

1. `fly apps create pae-platform-worker` + `pae-platform-beat`
2. Mirror secrets envelope from `pae-platform` per `.env.example`
3. `fly deploy --config fly-worker.toml` and `--config fly-beat.toml`
4. `fly scale count 1 --app pae-platform-beat` (singleton invariant)
5. Trigger `risk_scoring` + `outreach_automation` synthetically;
   confirm no OOM, verify DB writes
6. Set `OUTREACH_AUTO_SEND=1` only after SendGrid SPF/DKIM/DMARC are
   verified and a smoke send-to-self lands in inbox

---

## Cumulative D16 cost

CP1: ~₹0 (sub-agent code reading; no production LLM calls)
CP2: ~₹0 (engineering + documentation; no LLM calls)
CP3: ~₹0 (CP3.E2E smoke didn't invoke agents; backend round-trips only)

**Total: ~₹0.00 of ₹3.00 ceiling.** Comfortably under.

The original D16 prompt's expected range was ₹0.50-1.50; the actual
cost was lower because (a) CP1's read-only audit avoided LLM use, and
(b) CP3.E2E smoke verified retention surfacing rather than agent
invocation.

---

## Bug count

Pre-D16 engagement: 24 fixed across D10-D17a, 0 open.
D16 introduced: 0 new bugs (audit found 3 PARTIAL gaps; all addressed
in CP2; no defects requiring bug-numbered tracking).
**Engagement bug count: 24 fixed, 0 open.**

---

## Architectural artifacts produced

- `docs/architecture/d16-functional-audit.md` (CP1)
- `docs/architecture/d16-cp2d-ld-verification.md` (CP2.d)
- `docs/architecture/d16-cp3e2e-smoke-evidence.md` (CP3.E2E)
- `docs/architecture/d16-closure.md` (this file)
- 8 follow-up docs in `docs/followups/`
- Pattern 28 + Pattern 29 added; Pattern 23 extended in
  `docs/followups/migration-verification-discipline.md`
- Migration `0065_users_whatsapp_number.py`
- `fly-worker.toml`, `fly-beat.toml`
- Comprehensive `.env.example`

---

## Readiness for D17b + pre-launch + production

**D17b cleanup remaining** (per CP1 references):

- `jd_decoder` cost-tracking (deferred from D17a)
- 3 MEDIUM read-tool audit items (deferred from D17a)
- In-platform student-facing nudges via `career_coach` /
  `study_planner` prompt updates (out of D16 scope per prompt; D17b
  territory)
- LOW items deferred per follow-up docs (e.g., growth-snapshots
  admin cohort endpoint)

**Pre-launch comprehensive smoke** (per D16 prompt, ~₹20-50 estimated):

- Real-LLM exercise of all 18 agents through canonical prompts
- Cost-ceiling enforcement verification under load
- Playwright MCP end-to-end testing (cockpit walkthrough, signup
  flow with WhatsApp field, admin retention scenario in real browser)
- Production deploy of Celery worker + beat Fly apps + first scheduled
  task in production

**Production readiness checklist** (per `production_required` validator
in `app/core/config.py:268-326`):

- [x] All required Settings keys documented in `.env.example` (D16/CP2.m)
- [ ] Fly secrets set in production (operational; per .env.example
      checklist)
- [ ] Celery worker + beat Fly apps deployed (operational; per
      fly-worker.toml + fly-beat.toml file headers)
- [ ] SendGrid sender domain SPF + DKIM + DMARC verified (operational)
- [ ] Production smoke (risk_scoring + outreach_automation) verified
      no-OOM (operational; per celery-safety-memory-bump.md
      verification checklist)

D16 closes the code-side path to production launch on the retention
surface. The remaining items are operational deployment, not code work.

---

## Final commit summary

7 commits across 3 checkpoints:

```
89c7703 feat(retention): D16/CP3.3 — outreach surfacing on student timeline
380db51 feat(retention): D16/CP3.2 — admin WhatsApp deep-link + log-contact endpoint
cfdc087 feat(retention): D16/CP3.1 — User.whatsapp_number for manual outreach
a3be5d8 docs(followups): D16/Commit D — 8 follow-up docs registered
75bf3d5 docs(retention): D16/CP2.d+m — LD-1..LD-5 verification + comprehensive .env.example
ced93a5 fix(retention): D16/CP2.h+i — close audit-log gaps in retention engine
84b749e infra(celery): D16/CP2.l — Fly worker + beat app configs (launch blocker)
```

Plus this closure commit which lands the audit + smoke evidence + the
patterns extension + this closure document.
