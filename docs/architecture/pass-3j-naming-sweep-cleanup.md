---
title: Pass 3j — Naming Sweep + Cleanup
status: Final — execution playbook for identity convergence and dead-code removal
date: After Pass 3i sign-off, before D17 implementation
authored_by: Architect Claude (Opus 4.7)
purpose: Resolve the identity drift Pass 1 found (PAE Platform / CareerForge / Production AI Engineering Platform → AICareerOS canonical) and execute the deletion inventory Track 4 produced (scaffolding folders, stale test files, retired agents, dead dependencies). Specifies per-category sweep procedures, verification protocols, and sequencing across implementation deliverables.
supersedes: nothing
superseded_by: nothing — this is the canonical cleanup contract
informs: Every implementation deliverable D9 onward (each does its share of the sweep), with the bulk of standalone cleanup landing in D17
implemented_by: Distributed across D9, D11, D12, D13, D15, D16, D17 — each retires its in-scope agents and updates its in-scope strings, with D17 doing standalone cleanup
depends_on: Pass 1 (identity drift finding), Track 4 (naming-audit.md and dead-code-audit.md inventories), Pass 3a Addendum (final 16-agent roster — defines what's retired), Pass 3c §F (caller updates for retired agents)
---

# Pass 3j — Naming Sweep + Cleanup

> Track 4 inventoried what needs to change. Pass 3a Addendum decided what gets retired. This pass turns those inventories into an execution plan with verification protocols and explicit sequencing. The work is largely mechanical, but mechanical work that breaks production is still broken production. Hence the protocols.

> Read alongside: `docs/audits/naming-audit.md` and `docs/audits/dead-code-audit.md` (Track 4 outputs), Pass 3a Addendum (the canonical roster), Pass 3c §F (caller updates for retired agents).

---

## Section A — The Naming Convergence

### A.1 The canonical name

**AICareerOS** is the canonical platform name going forward. Always one word, capitalized as `AICareerOS` (not `AICareerOs`, `aicareeros`, or `AI CareerOS`). Domain: `aicareeros.com`.

Variants that exist today and are NOT canonical:

| Legacy variant | Where it appears | Disposition |
|---|---|---|
| `PAE Platform` | Code identifiers, some doc titles, internal references | Replace |
| `PAE` (standalone) | Some module names, environment variable prefixes, code comments | Replace where surfaces to users; leave in code where rename is high-risk |
| `Production AI Engineering Platform` | Marketing copy, public pages, some docs | Replace |
| `CareerForge` | Receipt prefixes (`CF-`), some email templates, possibly a few code constants | Replace in templates/copy; preserve in legacy receipt data |
| `pae_platform` | Repo folder name (`pae_platform/pae_platform/`), some Python module paths | **Leave alone** (renaming the repo root is outsized work for marginal gain; folder name doesn't surface to students) |
| `pae.dev` | Email domain in support address, some legacy URLs | Replace |

### A.2 What gets renamed (the inventory)

**User-facing strings (highest priority):**

- Page titles, meta descriptions in HTML
- Email templates (welcome, receipt, password reset, marketing, transactional, notification)
- Email "from" name (`From: AICareerOS <support@aicareeros.com>`)
- Public marketing pages: `/`, `/about`, `/pricing`, `/contact`, `/agents`
- Auth-flow pages: signup, login, password reset
- Footer branding across all pages
- Privacy policy and terms of service references
- Receipt template (new receipts only; legacy receipts unchanged)
- Notification subject lines
- Push notification copy (when push ships)
- Browser tab titles
- OG / Twitter card metadata
- App icon alt-text and aria-labels

**Agent-facing strings (medium priority):**

- Every prompt's brand section (Pass 3c §A.9 mandates this section in every agent prompt). Brand section says: "You are an agent in AICareerOS. When self-referring, use AICareerOS. Do not identify as PAE, PAE Platform, or CareerForge."
- Supervisor's prompt (specifically the role-definition paragraph)
- Decline messages, escalation messages, error messages that mention the platform
- Welcome messages and onboarding text the agents produce

**Operator-facing strings (lower priority):**

- Admin dashboard page titles
- Admin email subjects (notifications about flagged students, safety incidents)
- Internal Slack/Discord webhook usernames
- Sentry project name, PostHog project name (these are configuration changes in those tools, not code)
- Grafana dashboard titles

**Documentation:**

- Top-level README at repo root
- `docs/AGENTIC_OS.md`
- `docs/architecture/README.md`
- Any `docs/runbooks/*.md` that reference the brand
- Code comments that mention the brand (lower priority; sweep opportunistically when touching files)

### A.3 What does NOT get renamed (deliberately)

- **Receipt prefix `CF-` on existing receipts.** Pre-2026 receipts keep their prefix. New receipts use `AC-`. Documented in `billing_support`'s prompt (already done in Pass 3c E1) so the agent can reference both correctly when speaking to students.
- **Database tables, columns, foreign key names.** Renaming these is expensive (migration risk, downstream code references). Storage names like `users`, `course_entitlements`, `agent_actions` are internal. They don't surface to students. Leave alone.
- **Repo folder structure (`pae_platform/pae_platform/`).** Renaming the repo root requires updating every developer's local clone, every CI/CD path, every deployment pipeline. Not worth the disruption. Internal-only.
- **Python module paths within the repo.** Same reasoning — renaming `app.agents.foo_pae_helper` to `app.agents.foo_aicareeros_helper` produces churn for no user benefit. Module paths are internal.
- **Existing Git commit messages and PR titles.** History is history.
- **Environment variable names with `PAE_` prefix.** Renaming forces every deployment to update its env vars in lockstep with code. High risk for low payoff. Leave alone unless one specific variable surfaces to users (none currently do).
- **Historical Stripe customer references** (during the Razorpay migration period). If any legacy Stripe references remain in archived code paths, leave them; they're audit history.

### A.4 The support address

Per the locked-in choice: **`support@aicareeros.com`** going forward.

Implementation:

1. Configure the address itself in your email infrastructure (out of scope for code; an ops task)
2. Update the constant in `backend/app/core/config.py` from `support@pae.dev` to `support@aicareeros.com`
3. Update email templates (typically in `backend/app/templates/emails/` or wherever they live) to use the constant rather than hardcoding
4. Update `billing_support`'s prompt to reference the new address (Pass 3c E1 already specifies this)
5. Configure `support@pae.dev` to forward to the new address for at least 12 months — students with old emails will still try the old address
6. Update DNS, MX records, SPF, DKIM, DMARC for the new address before cutover
7. Test deliverability before announcing

The forwarding period matters. Some emails saved in students' inboxes still have the old address. Forwarding prevents "I emailed support and never heard back" scenarios.

---

## Section B — The Deletion Inventory

Track 4's `dead-code-audit.md` produced the candidate list. Pass 3j confirms each, assigns to a deliverable, and specifies verification.

### B.1 Scaffolding folders (~14 from Track 4)

Empty placeholder folders left from prior phases. Track 4's audit listed exact paths; here's the disposition pattern.

**Verification before deleting any scaffolding folder:**

```bash
# 1. Confirm folder is genuinely empty (no .py files, no __init__.py with content)
find <folder_path> -type f -not -name '__init__.py' | head
test -s <folder_path>/__init__.py && echo "WARNING: __init__.py has content"

# 2. Search for imports that reference the folder path
grep -r "from app\.agents\.<folder_name>" backend/
grep -r "import app\.agents\.<folder_name>" backend/

# 3. Search for string references (e.g., dynamic loading)
grep -r "<folder_name>" backend/ --include="*.py"
grep -r "<folder_name>" frontend/ --include="*.ts" --include="*.tsx"

# 4. If all three return clean: safe to delete
# 5. If any return references: investigate before deleting
```

**Sequencing:** scaffolding deletion lands in **D17 (final cleanup)** as a single batch commit. Bundling them into one commit makes review easier and rollback trivial if anything breaks.

### B.2 Stale test runners (~18 `run_3*_tests.py` files)

Track 4 found `run_3*_tests.py` style files left from the platform's earlier-phase test runs. These predate the current pytest setup and are not invoked by CI.

**Verification:**

```bash
# 1. Confirm none are referenced in CI
grep -r "run_3.*\.py" .github/ .circleci/ Makefile

# 2. Confirm none are imported anywhere
grep -r "from run_3" backend/ frontend/
grep -r "import run_3" backend/ frontend/

# 3. Confirm they aren't documented anywhere as the canonical test entry point
grep -r "run_3.*\.py" docs/
grep -r "run_3.*\.py" backend/README.md frontend/README.md

# 4. If clean: safe to delete
```

**Sequencing:** D17 batch.

### B.3 Retired agents (per Pass 3a Addendum + Pass 3c §F)

These agents are retired entirely. Each is deleted as part of its replacement deliverable, NOT in D17:

| Retired agent | Retired by | Files to delete | Where deletion happens |
|---|---|---|---|
| `cover_letter` | Pass 3a Addendum | `backend/app/agents/cover_letter.py`, `backend/app/agents/prompts/cover_letter.md` | D17 (no replacement; just gone) |
| `job_match` | Pass 3a Addendum | `backend/app/agents/job_match.py`, `backend/app/agents/prompts/job_match.md`, frontend `_agents-grid.tsx` entry | D17 (deferred until job board integration is committed; the embarrassing TODO is removed earlier) |
| `peer_matching` | Pass 3a Addendum | `backend/app/agents/peer_matching.py`, prompt | D17 |
| `deep_capturer` | Pass 3a Addendum | `backend/app/agents/deep_capturer.py`, prompt | D17 |
| `community_celebrator` | Pass 3a Addendum | `backend/app/agents/community_celebrator.py`, prompt | D17 (proactive celebration moves to interrupt_agent in D16; reactive celebration becomes a tone the Supervisor instructs specialists to use) |
| `disrupt_prevention` | Replaced by `interrupt_agent` | `backend/app/agents/disrupt_prevention.py`, prompt | D16 (after interrupt_agent ships) |
| `knowledge_graph` | Replaced by `MemoryStore` (D2 primitive) | `backend/app/agents/knowledge_graph.py`, prompt | D9 cleanup or D17 (whichever is convenient) |
| `curriculum_mapper` | Merged into `content_ingestion` | `backend/app/agents/curriculum_mapper.py`, prompt | D15 (after content_ingestion absorbs the mapping job) |
| `code_review` | Merged into `senior_engineer` | `backend/app/agents/code_review.py`, prompt | D11 (after senior_engineer migration ships) |
| `coding_assistant` | Merged into `senior_engineer` | `backend/app/agents/coding_assistant.py`, prompt | D11 |
| `student_buddy` | Absorbed by Learning Coach (D8) | `backend/app/agents/student_buddy.py`, prompt | D9 cleanup or D17 |
| `socratic_tutor` | Absorbed by Learning Coach (D8) | `backend/app/agents/socratic_tutor.py`, prompt | D9 cleanup or D17 |
| `adaptive_path` | Absorbed by Learning Coach (D8) | `backend/app/agents/adaptive_path.py`, prompt | D9 cleanup or D17 |
| `spaced_repetition` | Absorbed by Learning Coach (D8) | `backend/app/agents/spaced_repetition.py`, prompt | D9 cleanup or D17 |

**Verification before deleting any retired agent:**

```bash
# 1. Confirm AGENT_REGISTRY does not register this agent
grep -r "AGENT_REGISTRY" backend/app/agents/ | grep <agent_name>

# 2. Confirm MOA keyword routing does not point at it
grep "<agent_name>" backend/app/agents/moa.py
grep "<agent_name>" backend/app/agents/prompts/moa.md

# 3. Confirm no Celery task invokes it
grep -r "<agent_name>" backend/app/tasks/

# 4. Confirm no API route is dedicated to it
grep -r "<agent_name>" backend/app/api/

# 5. Confirm no frontend page or component invokes it
grep -r "<agent_name>" frontend/src/

# 6. Confirm no test imports it
grep -r "<agent_name>" backend/tests/

# 7. If anything found: that caller must be updated FIRST per Pass 3c §F
# 8. Only then delete the agent module + prompt
```

The verification protocol is what prevents deletion-by-accident-breaks-prod incidents.

### B.4 Dead dependencies

Track 4 flagged dependencies that aren't used. Common candidates:

- **Stripe SDK** — platform migrated to Razorpay; Stripe references should be archive-only. If `stripe` package is still in `pyproject.toml`, candidate for removal once the migration is fully verified clean.
- **Redundant scaffolding libraries** — anything imported by deleted scaffolding folders becomes orphan if that's the only usage.
- **Deprecated frontend deps** — frontend is frozen, but `package.json` may still list deps not actually imported.

**Verification:**

```bash
# Backend
pip-check-reqs backend/  # finds installed packages not imported
# OR
deptry backend/  # alternative; both work

# Frontend (frozen — defer until unfreeze)
npx depcheck frontend/  # finds package.json deps not imported
```

**Sequencing:** D17 batch for backend. Frontend deferred until unfrozen.

### B.5 Two main.py investigation (from Track 1 follow-up)

Track 1 noted there are two `main.py` files in the repo. Disposition unclear — could be one is dead, or both are intentional (e.g., one for dev, one for prod). D17 includes a 30-minute investigation to determine which:

```bash
# Find the two main.py files
find backend/ -name "main.py"

# For each, check what imports it
grep -r "from .* import.*main" backend/
grep -r "from app.main" backend/
# etc.

# Check Procfile, Dockerfile, deployment configs for which main.py is the entry point
cat Procfile 2>/dev/null
cat Dockerfile 2>/dev/null
grep -r "main:app" .
```

Outcome of investigation lands in `docs/followups/two-main-py-investigation.md`. If one is dead: delete it. If both are intentional: document why.

### B.6 Other Track 1 follow-ups absorbed into Pass 3j

Some Track 1 follow-up items are cleanup-flavored and land in D17:

- **`interview_service.py` deprecation** — if mock_interview migration (D13) replaced its callers, the legacy service file is deletable
- **T6-F1 return-type drift** — small (~3 LOC) fix; D17 sweep
- **Alembic 0050 gap** — already RESOLVED per the prior follow-up audit
- **Alembic upgrade-from-base broken at 0023** — needs investigation; might be deferred beyond D17 if it's structural

---

## Section C — Per-Category Sweep Procedures

### C.1 Code string sweep

Approach: grep-driven, file-by-file, with explicit verification.

**For each user-facing string (e.g., a default platform name in a config or template):**

```python
# Identify the canonical constant
PLATFORM_NAME = "AICareerOS"  # was: "PAE Platform"

# Replace in all identified locations
# Manual review of each replacement (don't sed-script blind global replace)
# Run tests after each batch of replacements
# Commit per logical group, not all at once
```

A single bad sed replace ("PAE" → "AICareerOS" globally) would break things — `pae_platform` directory references, `PAE_DATABASE_URL` env vars, Python imports, etc. The discipline is: identify the *user-facing* surfaces, replace those specifically, leave internal identifiers alone.

### C.2 Email template sweep

Templates typically live in `backend/app/templates/emails/` or wherever the email infrastructure stores them.

**Per-template checklist:**

- [ ] "From" name uses `{PLATFORM_NAME}` template var, not hardcoded
- [ ] Subject lines reference AICareerOS where the platform is named
- [ ] Footer block uses canonical name + canonical URL + canonical address
- [ ] Logo references point to AICareerOS asset (not legacy)
- [ ] Any in-body mentions are AICareerOS
- [ ] Unsubscribe link footer mentions AICareerOS in compliance text
- [ ] CTA buttons say "Open AICareerOS" not "Open PAE Platform"

**Templates to review (typical set):**

- Welcome / signup
- Email verification
- Password reset
- Receipt / order confirmation
- Refund confirmation
- Course enrollment confirmation
- Course completion / certificate
- Weekly progress report (the `progress_report` agent's output template)
- Interrupt nudges (the `interrupt_agent`'s email channel template, after D16)
- Re-engagement campaigns
- Admin notifications

### C.3 Frontend string sweep (deferred)

The frontend is frozen. This subsection lists what would change when it unfreezes:

**Frontend files where the brand likely appears:**

- `frontend/src/app/layout.tsx` (root metadata, OG tags)
- `frontend/src/app/page.tsx` (homepage)
- `frontend/src/components/layout/header.tsx`
- `frontend/src/components/layout/footer.tsx`
- `frontend/src/app/(public)/about/page.tsx`
- `frontend/src/app/(public)/pricing/page.tsx`
- `frontend/src/app/(public)/contact/page.tsx`
- `frontend/src/app/(public)/agents/_agents-grid.tsx` (and child files)
- `frontend/public/favicon.ico` (asset replacement)
- `frontend/public/og-image.png` (asset replacement)
- `frontend/src/lib/seo.ts` or equivalent metadata constants

**Approach when unfreezing:**

1. Centralize the platform name into a single TS constant (`SITE_NAME = "AICareerOS"`)
2. Sweep references to import from the constant instead of hardcoding
3. Replace assets in `frontend/public/`
4. Update next.js metadata exports across pages
5. Visual review across all public pages before merge

**Pass 3j action:** queue these as `docs/followups/frontend-naming-sweep.md` for whenever the frontend unfreezes.

### C.4 Doc sweep

**Documents to update:**

- Repo root `README.md` — fully rewrite to reflect AICareerOS
- `docs/AGENTIC_OS.md` — already written for AICareerOS in Track 3
- `docs/architecture/README.md` — already updated through prior passes
- `docs/runbooks/*.md` — update brand references
- `CONTRIBUTING.md` (if exists) — brand references
- `LICENSE` — typically no brand mention; verify
- `SECURITY.md` (if exists) — brand mention in security contact

**Approach:** opportunistic — when touching a doc for any reason, update brand references in the same commit. Standalone doc-only sweeps only for top-of-funnel docs (root README).

D17 includes a final pass through `docs/` to catch any lingering legacy mentions.

### C.5 Config sweep

**Config files to update:**

- `backend/app/core/config.py` — platform name constants, support email
- `pyproject.toml` — project name (may already be `pae_platform`; cosmetic, low priority)
- `frontend/package.json` — name field (cosmetic when frontend unfreezes)
- `.env.example` — variable names with `PAE_` prefix flagged but generally left alone (renaming env vars is high-risk; only rename if a specific variable surfaces to users)
- `docker-compose.yml` — service names referencing brand (low priority; internal)
- Deployment configs (Procfile, Dockerfile) — typically internal, leave alone

### C.6 Schema sweep

**Decision: minimize schema renames.**

The few cases worth investigating:

- Any column literally named with brand reference (highly unlikely in a well-designed schema; verify with `grep` over `backend/migrations/`)
- Any enum value with brand reference (e.g., a `platform_source` enum with value `pae_platform`)

**Procedure if schema rename is needed:**

1. Add new column / enum value alongside old
2. Backfill data
3. Update application code to use new
4. Wait one deployment cycle to verify
5. Remove old column / enum value in subsequent migration

This is the standard zero-downtime schema-change pattern. Don't rush it.

**Pass 3j expected outcome:** zero schema renames identified as necessary. Storage layer is internal; brand lives in display layer.

---

## Section D — Verification Protocols

### D.1 Pre-deletion verification

For every deletion action, three checks:

1. **Static reference search:** grep for the deleted symbol across the entire repo
2. **Test suite run:** full test suite passes after deletion
3. **Smoke deployment:** if the deletion is non-trivial, deploy to staging and run E2E tests

The sequence matters: never delete in production code without staging verification.

### D.2 Post-rename verification

For every rename action:

1. **Visual verification:** for user-facing changes, view the affected page/email/dashboard and confirm the new name renders correctly
2. **Email deliverability:** for support address change, send test emails through the new address and verify they arrive in the right inbox
3. **DNS/MX verification:** before cutover of email domain, verify SPF, DKIM, DMARC are configured for the new domain

### D.3 The "rollback plan" requirement

Every cleanup commit has an explicit rollback plan in the commit message. Examples:

- "Rollback: revert this commit and restore the deleted file from `<commit_sha>`"
- "Rollback: revert this commit; previous email constant was `support@pae.dev`"

For multi-commit cleanup batches, the rollback plan is "revert these N commits in reverse order."

This discipline doesn't add much overhead and saves significant time when something goes wrong.

---

## Section E — Sequencing Across Deliverables

The sweep is distributed, not concentrated. Each deliverable owns its share.

### E.1 D9 cleanup actions

- Update `backend/app/core/config.py`: support email constant
- Update Supervisor's prompt with AICareerOS brand (Pass 3b §4.2 already specifies AICareerOS)
- Optionally delete `student_buddy`, `socratic_tutor`, `adaptive_path`, `spaced_repetition`, `knowledge_graph` legacy files (since Learning Coach absorbs them and these have no callers in the new architecture)
- Update repo root `README.md` to AICareerOS

### E.2 D11 cleanup actions

- Delete `code_review.py`, `coding_assistant.py`, and prompts (after senior_engineer migration completes)
- Verify no callers per the §B.3 protocol
- Update any docs that reference the merged agents

### E.3 D12 cleanup actions

- Update career-bundle agent prompts with AICareerOS brand
- Update career-related email templates
- No agent retirements in this deliverable

### E.4 D13 cleanup actions

- Update mock_interview's prompt with AICareerOS brand
- Investigate and possibly delete `interview_service.py` if mock_interview migration replaces all its callers
- Update interview-related email templates if any

### E.5 D15 cleanup actions

- Delete `curriculum_mapper.py` after content_ingestion absorbs it
- Update content_ingestion's prompt with AICareerOS brand
- Update any content-related admin pages (deferred frontend)

### E.6 D16 cleanup actions

- Delete `disrupt_prevention.py` after interrupt_agent ships
- Update interrupt_agent's email templates with AICareerOS brand
- Update progress_report's email template

### E.7 D17 standalone cleanup

The dedicated cleanup deliverable. Scope:

- Scaffolding folder deletion batch (the ~14 from Track 4)
- Stale test runner deletion batch (the ~18 `run_3*_tests.py`)
- Remaining retired agent deletions (`cover_letter`, `peer_matching`, `deep_capturer`, `community_celebrator`, `job_match` if not earlier)
- Backend dead dependency removal (Stripe et al)
- Two-main.py investigation outcome
- T6-F1 return-type drift fix
- Final doc sweep across `docs/`
- Verification protocols runs across the cleanup

### E.8 Distributed work across deliverables

The bulk of brand string replacement happens **opportunistically** within deliverables that touch the relevant files anyway. When D11 modifies `senior_engineer`'s prompt, it updates the brand section in the same commit. When D12 modifies email templates, it updates brand references in the same commit.

Rationale: this minimizes commits-touching-many-files, makes review easier, and means the sweep finishes when the implementation work finishes — no separate "cleanup phase" at the end.

---

## Section F — The Frozen-Frontend Treatment

Frontend code changes are deferred until the frontend unfreezes. Until then:

### F.1 What ships before unfreeze

Backend strings and templates served to the frontend can be updated freely:

- API response strings (error messages, decline messages, etc.)
- Email content (rendered server-side)
- Server-rendered metadata (if any)

The frontend will display these new strings without code changes because the frontend just renders what the backend serves.

### F.2 What waits for unfreeze

- Static HTML strings (page titles in `<title>`, OG tags)
- Hardcoded brand mentions in TS files
- Asset replacements (favicon, OG image, logo)
- Component-level brand references

### F.3 The unfreeze checklist

When the frontend unfreezes, the queued work in `docs/followups/frontend-naming-sweep.md` is the checklist. Items:

1. Asset replacement: favicon, logo, OG image
2. Centralize brand constant: `frontend/src/lib/site.ts` exports `SITE_NAME = "AICareerOS"`
3. Sweep references using the central constant
4. Update all next.js metadata exports
5. Visual QA across all public pages
6. Verify with Lighthouse / PageSpeed that meta tags render correctly
7. Update OG card image
8. Remove the embarrassing TODO from agents-grid (the `job_match` "TODO: Adzuna / LinkedIn integration" entry)

This work is contained and can ship as a single deliverable after unfreeze.

---

## Section G — Risk And Rollback

### G.1 What could go wrong

Three specific risk patterns:

**Risk 1: Brand replacement breaks search-engine reputation**
- If you have any organic search traffic, sudden bulk changes can hurt rankings temporarily
- Mitigation: redirect old URLs to new ones permanently (301), update OG tags carefully, monitor Search Console

**Risk 2: Email deliverability tanks during domain switch**
- New domain has no sender reputation
- Mitigation: warmup period for the new address; forward old to new; gradual cutover

**Risk 3: Deletion of "scaffolding" turns out to be load-bearing**
- A folder that looks empty might be referenced via dynamic import
- Mitigation: the verification protocol in §B.1 catches this; test suite run after each deletion

### G.2 Rollback per category

| Category | Rollback |
|---|---|
| Code string rename | Revert commit |
| Folder deletion | Revert commit; folder restored from git history |
| Agent retirement | Revert deletion; restore module + prompt; re-add to AGENT_REGISTRY |
| Dependency removal | Revert poetry/pip lock; reinstall |
| Email address change | Update DNS back; re-route; old address still works during forwarding period |
| Schema rename | This is why §C.6 says minimize schema renames; rollback is non-trivial |

### G.3 The "12-month forwarding" insurance

Keep `support@pae.dev` forwarded to `support@aicareeros.com` for at least 12 months. Optional: forever. Cost is near-zero; benefit is "students using cached emails still reach you."

---

## Section H — What This Pass Earns

When the cleanup completes:

**For students:**
- Single consistent platform identity (AICareerOS everywhere)
- No more confusion about whether they signed up for "PAE" or "CareerForge" or "AICareerOS"
- Email from a brand-aligned address
- Clean public-facing surface (no embarrassing TODOs in the agents grid)

**For the operator:**
- Smaller codebase (less to maintain)
- No retired-agent confusion in logs/dashboards
- No dead dependencies updating risk
- Doc references that match reality
- Clean baseline to grow from

**For future contributors:**
- One canonical name to learn
- No "wait, why is this called PAE here?" moments
- Empty scaffolding doesn't pollute autocomplete or grep results
- The agents directory matches the documented roster

This is the layer that makes AICareerOS feel like *a finished platform*, not a platform under construction.

---

## Section I — What's Deferred

- **Frontend code changes** — until unfreeze
- **Frontend asset replacements** — until unfreeze
- **`pae_platform/` folder rename** — deemed not worth the disruption
- **Internal Python module renames** — same
- **Environment variable renames** — same
- **OLAP database for analytics** — flagged in Pass 3i
- **Multi-region** — flagged in Pass 3i

---

## What's NOT covered by Pass 3j

- **Implementation roadmap synthesis** → Pass 3k/3l (final architecture pass)

After Pass 3j, only the implementation roadmap synthesis remains. That pass sequences everything from Pass 3b through 3j into D9-D17 as Claude Code-ready prompts.
