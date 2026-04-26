# Feature Spec: Tailored Resume & Cover Letter Agent

**Status:** Proposed
**Page:** Job Readiness
**Tier:** Freemium (free quota + ₹499/mo unlimited)
**Logged:** 2026-04-25

---

## 1. One-line Pitch

The only resume tool that already knows what the student has built — converting verified platform activity (lessons, capstones, code, mock scores) into JD-tailored resumes and cover letters, generated as ATS-safe PDFs ready to submit.

---

## 2. Strategic Rationale

**Moat:** Generic resume tools (ChatGPT, Rezi, Teal) ask users to *remember and self-report* their wins. CareerForge already holds primary evidence: completed projects, code repos, peer reviews, mock interview scores, time-on-task. This is data competitors structurally cannot access.

**Retention play:** Job Readiness currently ends with a readiness score, then the student leaves the app to apply elsewhere. This feature keeps the highest-intent moment (active job search) inside the product, where engagement compounds.

**Emotional reframe:** Shifts the page narrative from *"go fix your gaps"* to *"let's apply today, optimized."* Stickier, more agentic.

---

## 3. User Flow (Happy Path)

1. Student lands on Job Readiness → sees "Tailored Resume" CTA.
2. Pastes JD (URL or text) OR uploads a saved JD from their tracker.
3. Agent runs intake: 4–7 dynamic questions filling gaps the platform data doesn't cover (e.g., "Why this company?", "Salary expectation?", non-platform work experience).
4. Agent generates: tailored resume + cover letter (bundled, default-on).
5. Diff view shown: base resume vs. tailored, with 5–8 changes highlighted and reasoned. *(Phase 2)*
6. Student previews PDF → downloads → optionally logs the application in tracker.
7. Quota counter visible throughout; soft upsell appears when 1 free remaining.

---

## 4. Free vs. Premium

| | Free | Premium (₹499/mo) |
|---|---|---|
| Resumes/day | 5 | Unlimited |
| Resumes/month | 20 | Unlimited |
| Cover letters | Bundled | Bundled |
| First resume | Always free, even past limits | — |
| JD save & re-tailor | 3 saved | Unlimited |
| Resume version history | Last 5 | Unlimited |
| ATS score check | ✓ | ✓ |
| Recruiter signal verification badge | ✗ | ✓ |
| Priority generation queue | ✗ | ✓ |

**Pricing rationale:** Market comparables charge ₹999–1,499/mo for thinner products. ₹499 undercuts while keeping margin once unit cost (LLM + PDF render) lands ~₹15–25 per resume. Break-even at ~25 paid users covers ~5,000 free generations/month.

---

## 5. Architecture & Components

### 5.1 Frontend
- **Entry point:** Job Readiness page → existing Resume Lab tab → "Generate tailored version" button (already in v8 markup at `readiness-screen.tsx`, currently a no-op).
- **Intake modal:** Multi-step form, dynamic questions (skip questions answered by platform data).
- **Diff viewer:** Side-by-side or inline diff, with hover tooltips on each change. *(Phase 2)*
- **PDF preview:** Embedded, with download + "Log this application" CTA.
- **Quota chip:** Persistent, shows X/5 today, Y/20 this month.

### 5.2 Backend Services

| Service | Responsibility |
|---|---|
| **JdParser** | Extracts must-haves, nice-to-haves, seniority, company stage, template-filler phrases. LLM-based (Haiku). |
| **ProfileAggregator** | Pulls verified platform data: skill confidences, exercise counts, cached `Resume.bullets[]`, intake_data. |
| **TailoringAgent** | LLM orchestration (Sonnet): matches profile evidence to JD requirements, drafts content. Outputs structured JSON. |
| **CoverLetterAgent** | Shares context with resume agent; generates aligned tone. |
| **PdfRenderer** | HTML/Jinja → ATS-safe PDF via WeasyPrint (single column, embedded fonts, parseable). |
| **QuotaService** | Tracks usage per user/day/month. Honors first-resume-free rule. |
| **HallucinationValidator** | Two-pass check: deterministic evidence_id allowlist + Haiku verifier. Triggers regenerate (max 2 retries). |
| **DiffEngine** | Computes structured diff between base and tailored. *(Phase 2)* |

### 5.3 Data Model

**Reuses existing models** where possible:
- `Resume` — extended with new `intake_data: JSON` column. *This is the BaseResume.*
- `JdLibrary` — already exists, used as-is for saved JDs.

**New tables:**
- `TailoredResume` — versioned, links to JD + base, stores parsed JD, intake answers, structured content, validation result.
- `GenerationLog` — usage, cost, model, latency, validation outcome. Drives quota + analytics + cost tracking.

### 5.4 LLM Strategy

| Step | Model | Notes |
|---|---|---|
| JD parsing | `claude-haiku-4-5` | Cheap, structured |
| Intake question selection | `claude-haiku-4-5` | Picks 4–7 from a fixed bank |
| Tailoring | `claude-sonnet-4-6` | Reasoning quality matters |
| Cover letter | `claude-sonnet-4-6` | Tone alignment with resume |
| Validation | `claude-haiku-4-5` | Cheap verifier pass |

**Hallucination guardrail:** Tailoring agent can ONLY cite skills/projects present in `BaseResume` (verified profile) or `intake_data.non_platform_experience` (self-attested). Hard constraint in system prompt + post-generation validator that flags any claim not traceable to source. Self-attested entries are tagged `verified: false` for future UI signaling.

**Cost cap:** ~₹20 max per generation; circuit breaker if exceeded. Estimated baseline cost ~₹9 per generation.

---

## 6. Critical Design Decisions & Tradeoffs

### Decision 1: Bundle cover letters by default
- **Tradeoff:** Slightly higher LLM cost per generation (+30%).
- **Why:** Cover letter is the friction that kills application completion. Bundling = perceived 3x value at 1.3x cost. Worth it.

### Decision 2: Single-column ATS-safe PDF only (no "pretty" templates at launch)
- **Tradeoff:** Loses the visual wow factor of competitors like Canva/Rezi.
- **Why:** Pretty multi-column resumes fail ATS parsers ~40% of the time. Our promise is *interview calls*, not *good-looking files*. Templates are a v2 add for premium.

### Decision 3: Verification badge on PDF footer (*"Projects verified by CareerForge"*) — Phase 3
- **Tradeoff:** Looks like marketing in year 1; only valuable if recruiters recognize it.
- **Why:** Long-game brand bet. Costs nothing to add now, compounds if even a handful of hiring partners adopt it. Premium-only to preserve scarcity signal.

### Decision 4: Soft-gate on low readiness scores
- **Tradeoff:** Slightly hurts conversion in the moment; students can override.
- **Why:** A 40%-ready student blasting 30 resumes fails interviews, blames the product, churns, and badmouths. The nudge ("rehearse first?") protects the brand and the user. Override is one click.
- **Implementation:** triggered when `Resume.verdict == "needs_work"`.

### Decision 5: First resume always free, regardless of quota
- **Tradeoff:** Costs ~₹9 even from churned/returning users.
- **Why:** A returning student blocked by paywall on their first action will never come back. Friction at re-entry is far more expensive than the LLM cost.
- **Implementation:** quota check passes when `count(GenerationLog where status='completed' and user_id=X) == 0`.

### Decision 6: Generous free tier (5/day, 20/month)
- **Tradeoff:** Higher CAC absorption, more free generations to fund.
- **Why:** Conversion philosophy — students who succeed on free upgrade out of love. Students who hit walls mid-job-hunt churn and hate the product. Generosity is cheaper than a bad NPS.

### Decision 7: Show the diff — Phase 2
- **Tradeoff:** Engineering complexity (diff engine, tooltips, reasoning capture).
- **Why:** Trust. Without the diff, students assume the AI hallucinates. With it, they learn resume craft AND develop confidence in the output. Doubles as a teaching moment.

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| LLM hallucinates skills/experience student doesn't have | Hard constraint: agent can only cite from verified `BaseResume` or self-attested `intake_data`. Two-pass post-gen validator. |
| Resume looks pretty but fails ATS | WeasyPrint single-column template + `pdfplumber` text extraction test in CI. |
| Students spam-apply with low readiness, fail interviews, blame product | Soft-gate at `verdict == "needs_work"`; one-click override; track outcome data. |
| Cost spirals on free tier | Per-generation cost cap (₹20) + monthly budget alarm; `GenerationLog` powers cost dashboards. |
| Premium feels too cheap, attracts low-LTV users | Reassess pricing at 3-month mark with cohort data. ₹499 is a launch number, not permanent. |
| Indian market is price-sensitive | Consider student-verified discount (₹299) via .edu email or platform tenure. |

---

## 8. Success Metrics

**Activation:** % of Job Readiness page visitors who generate ≥1 resume.
**Quality:** Interview-call rate reported by students (self-reported, optional survey post-application).
**Retention:** % of free users who return within 7 days for a 2nd resume.
**Conversion:** Free → Premium rate; benchmark target 4–7%.
**Trust:** % of generated resumes downloaded vs. abandoned at preview.
**Stickiness:** Resumes generated per active premium user per month.

Analytics events: `resume.generation.started`, `resume.generation.completed`, `resume.generation.failed`, `resume.downloaded`, `resume.quota.blocked`.

---

## 9. Build Phases

**Phase 1 (MVP, this PR):** JD paste → tailored resume PDF. Bundled cover letter. Free quota with first-free rule. Single ATS-safe template. Hallucination validator. Feature flag.

**Phase 2:** Diff view. Application tracker integration. JD save & re-tailor. Premium tier launch. JD URL fetch.

**Phase 3:** Verification badge. ATS score check. Recruiter-facing landing page for verified profiles. Premium templates.

---

## 10. Open Questions

- Should the base resume be auto-generated on platform onboarding, or only when student first opens the resume tool? *(Already auto-generates on first `/career/resume` GET — keeping this behavior.)*
- Do we let students edit the tailored output, or keep it agent-only to preserve quality? *(Recommendation: editable in Phase 2, but track what they change — that's gold for improving the agent.)*
- Where does the resume live? Inside CareerForge only, or do we offer Google Drive / email export? *(Phase 1 = download only. Drive/email = Phase 3.)*
- Long-term: should we offer one-click apply to LinkedIn / Naukri via API, or stay platform-agnostic?
