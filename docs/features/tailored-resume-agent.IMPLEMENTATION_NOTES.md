# Tailored Resume Agent — Phase 1 Implementation Notes

## What shipped (Phase 1)

End-to-end MVP wired behind `settings.feature_tailored_resume_agent` (default off):

- **Backend**
  - Migration `0037_tailored_resume`: adds `resumes.intake_data`, creates `tailored_resumes` and `generation_logs`.
  - Services: `quota_service`, `jd_parser` (Haiku), `profile_aggregator`, `hallucination_validator` (deterministic + LLM passes), `pdf_renderer` (WeasyPrint with hand-rolled fallback), `tailored_resume_service` (orchestrator).
  - Agents: `TailoredResumeAgent` (Sonnet) and `CoverLetterAgent` (Sonnet), registered via `@register`. System prompts at `app/agents/prompts/tailored_resume.md` and `app/agents/prompts/cover_letter.md`.
  - Routes mounted at `/api/v1/tailored-resume`: `GET /quota`, `POST /intake`, `POST /generate`, `GET /{id}/pdf`.
  - Tests: quota (first-resume-free edge case + daily/monthly), validator (deterministic + skip-LLM logic), JD parser (coercion + empty input), PDF renderer (round-trip text extraction), full route integration with the LLM pipeline mocked.
  - Feature flag: `feature_tailored_resume_agent` in `app/core/config.py`.
  - Analytics: `started`, `completed`, `failed`, `quota_blocked`, `downloaded` rows in `generation_logs`.

- **Frontend**
  - `lib/copy/tailored-resume.ts` — every user-facing string in one place.
  - `lib/hooks/use-tailored-resume.ts` — `useTailoredResumeQuota`, `useStartIntake`, `useGenerateTailoredResume`, `tailoredResumePdfUrl`.
  - `components/features/tailored-resume/` — `IntakeModal`, `TailoredResumeQuotaChip`, `PdfPreview`, `GenerationProgress`.
  - Wired into `readiness-screen.tsx` Resume Lab tab — replaces the dead "Generate tailored version" button at line 633 and swaps the static 71% confidence chip for the live quota chip.
  - Test: `quota-chip.test.tsx` covers the first-free / blocked / within-quota labels.

## Spec deviations & why

1. **No new `BaseResume` table.** Found an existing `Resume` model that already stores `summary / bullets[] / skills_snapshot / verdict` — the spec's `BaseResume` is functionally identical. Extended it with one `intake_data` JSON column instead of duplicating. Saves a migration plus a sync layer.
2. **`ProfileAggregator` builds on top of `career_service.get_student_skill_map` / `regenerate_resume`** rather than re-reading the schema directly. The existing functions already enforce evidence grounding; rewriting them would risk drift between two paths to the same answer.
3. **JD parser is LLM-only** (Haiku). The legacy `extract_jd_skills` regex remains intact for the existing fit-score path — I deliberately did not break the existing JD library / fit-score callers.
4. **First-free rule is implemented as `count(GenerationLog WHERE event IN ('completed','failed') AND user_id=X) == 0`** — I count `failed` as consumed so a malicious user can't burn through tokens by triggering retries. Quota-blocked attempts do *not* count, so a returning user is still entitled to one paid generation even if they hit the wall earlier.
5. **MinIO upload deferred.** The spec mentioned MinIO; the existing `attachments` storage uses a local-disk backend by default with a TODO to swap for S3. Rather than wire MinIO mid-flight I store the PDF bytes on the row (`tailored_resumes.pdf_blob`) and stream them from the download route. The TODO seam is `tailored_resume_service.generate_tailored_resume` after `db.refresh(tailored)` — when MinIO/S3 is configured, upload there and store the URL in `pdf_url` instead.
6. **Cover letter PDF not persisted.** Only the resume PDF is stored; the cover letter body lives in the `content.cover_letter.body` JSON field and is rendered on demand. Halves the BLOB footprint and matches the "single download artifact" UX for Phase 1. If the spec demands a separate cover-letter PDF download later, the renderer is already written — just persist the bytes too.
7. **Soft-gate uses `Resume.verdict == "needs_work"`** rather than introducing a new readiness threshold. That field is already populated by `derive_resume_verdict` (`career_service.py:186`) and is the same signal the existing Resume Lab UI already trusts.
8. **No diff view.** Per spec, that's Phase 2. Stub left in `tailored_resume_service.py` — the `tailoring_notes` field on the agent output is already populated and ready to drive a diff component when the time comes.

## Open questions left for the user

- **Sample JD URL fetching** — spec mentioned URL or paste; only paste is wired. URL fetch was explicitly listed as out-of-scope for Phase 1 in your prompt.
- **Application tracker integration** — there is no application-tracker table in the schema yet. The "Log this application" CTA in the preview is currently absent — I left it out instead of wiring a dead button.
- **MiniMax compatibility for Haiku-tier calls** — when `MINIMAX_API_KEY` is set, both `tier="fast"` and `tier="smart"` route to the configured MiniMax model (no separate fast model in the MiniMax setup). This means the cost cap calibration is conservative when MiniMax is the active backend — flag for re-tuning if MiniMax pricing differs materially.

## Cost estimate per generation

Using Anthropic list pricing and the new `estimate_cost_inr()` helper in `app/agents/llm_factory.py`:

| Step | Model | Typical input tokens | Typical output tokens | Est. cost (₹) |
|---|---|---|---|---|
| JD parse | claude-haiku-4-5 | ~600 | ~250 | ~₹0.13 |
| Tailoring (1st pass) | claude-sonnet-4-6 | ~1,800 | ~900 | ~₹1.59 |
| Tailoring (worst case, 2 retries) | claude-sonnet-4-6 | ~5,400 | ~2,700 | ~₹4.77 |
| Validator (LLM pass) | claude-haiku-4-5 | ~1,500 | ~150 | ~₹0.15 |
| Cover letter | claude-sonnet-4-6 | ~1,200 | ~500 | ~₹0.93 |

**Median expected:** ~₹2.80 per generation.
**Worst case (2 retries):** ~₹6.50 per generation.
**Hard cap:** ₹20 (`COST_CAP_INR` in `tailored_resume_service.py`) — circuit breaker raises `CostCapExceededError` and the route returns 503.

Per-user economics: free tier ceiling is 20 resumes/month → ~₹56 LLM cost worst-case per heavy free user. Premium ceiling unbounded — but Sonnet pricing keeps a ₹499/mo premium user above margin until they cross ~80 generations.

## What's stubbed for Phase 2

- **Diff engine** — `tailoring_notes[]` is captured and persisted; no UI yet.
- **Premium tier check** — quota service has no plan-aware branch.
- **JD URL fetch** — only paste-text; URL ingestion belongs in `jd_parser.parse_jd` as a pre-step.
- **Application tracker** — needs a new `applications` table; `tailored_resume.id` is the natural FK.
- **Saved JD re-tailor** — the `jd_id` column on `tailored_resumes` is wired but no route exposes "re-tailor against this saved JD" yet.
- **Verification badge** (Phase 3) — PDF footer is a static "Generated by CareerForge — careerforge.app" string. Premium tier should swap this for the verified badge.
- **MinIO/S3 upload** — see deviation #5 above.

## How to enable in dev

```bash
# .env
FEATURE_TAILORED_RESUME_AGENT=true
ANTHROPIC_API_KEY=...   # or MINIMAX_API_KEY=...

# install new deps
cd backend && uv sync       # picks up weasyprint, pdfplumber, jinja2

# migrate
cd backend && uv run alembic upgrade head

# run
make dev
```

WeasyPrint requires GTK on Windows. If GTK isn't available, the renderer falls back to a hand-rolled minimal PDF that's still parseable by ATS — this is intentional, the PDF round-trip test exercises both paths.

## Testing matrix

| Test | What it asserts |
|---|---|
| `test_quota_service.py::test_first_generation_is_free_when_no_history` | The headline rule. |
| `test_quota_service.py::test_first_free_rule_holds_after_only_quota_blocks` | Blocked attempts don't burn the freebie. |
| `test_quota_service.py::test_old_generations_outside_window_are_ignored` | Returning users in a new month aren't blocked. |
| `test_hallucination_validator.py` | Deterministic check rejects unknown evidence_id; LLM pass only fires after deterministic clears. |
| `test_jd_parser.py` | Coercion handles malformed LLM output without raising. |
| `test_pdf_renderer.py` | Resume + cover letter both round-trip through pdfplumber/extract_text. |
| `test_tailored_resume_routes.py::test_generate_full_pipeline` | Quota → intake → generate → PDF download with the LLM pipeline mocked. |
| `quota-chip.test.tsx` | UI labels match quota state machine. |

Run: `cd backend && uv run pytest tests/test_services/test_quota_service.py tests/test_services/test_hallucination_validator.py tests/test_services/test_jd_parser.py tests/test_services/test_pdf_renderer.py tests/test_api/test_tailored_resume_routes.py -x`

## Files added / changed (cheat sheet)

```
docs/features/tailored-resume-agent.md                                    NEW (spec)
docs/features/tailored-resume-agent.IMPLEMENTATION_NOTES.md               NEW (this file)

backend/alembic/versions/0037_tailored_resume.py                          NEW
backend/app/models/tailored_resume.py                                     NEW
backend/app/models/generation_log.py                                      NEW
backend/app/models/resume.py                                              EDITED (+intake_data)
backend/app/models/__init__.py                                            EDITED (exports)
backend/app/services/quota_service.py                                     NEW
backend/app/services/jd_parser.py                                         NEW
backend/app/services/profile_aggregator.py                                NEW
backend/app/services/hallucination_validator.py                           NEW
backend/app/services/pdf_renderer.py                                      NEW
backend/app/services/tailored_resume_service.py                           NEW
backend/app/agents/tailored_resume.py                                     NEW
backend/app/agents/cover_letter.py                                        NEW
backend/app/agents/prompts/tailored_resume.md                             NEW
backend/app/agents/prompts/cover_letter.md                                NEW
backend/app/agents/llm_factory.py                                         EDITED (+tier, +estimate_cost_inr)
backend/app/agents/registry.py                                            EDITED (+2 imports)
backend/app/api/v1/routes/tailored_resume.py                              NEW
backend/app/schemas/tailored_resume.py                                    NEW
backend/app/templates/resume_ats.html                                     NEW
backend/app/templates/cover_letter_ats.html                               NEW
backend/app/main.py                                                       EDITED (mount router)
backend/app/core/config.py                                                EDITED (feature flag)
backend/pyproject.toml                                                    EDITED (+weasyprint, +pdfplumber, +jinja2)
backend/tests/test_services/test_quota_service.py                         NEW
backend/tests/test_services/test_jd_parser.py                             NEW
backend/tests/test_services/test_hallucination_validator.py               NEW
backend/tests/test_services/test_pdf_renderer.py                          NEW
backend/tests/test_api/test_tailored_resume_routes.py                     NEW

frontend/src/lib/copy/tailored-resume.ts                                  NEW
frontend/src/lib/hooks/use-tailored-resume.ts                             NEW
frontend/src/components/features/tailored-resume/intake-modal.tsx         NEW
frontend/src/components/features/tailored-resume/quota-chip.tsx           NEW
frontend/src/components/features/tailored-resume/pdf-preview.tsx          NEW
frontend/src/components/features/tailored-resume/generation-progress.tsx  NEW
frontend/src/components/features/tailored-resume/index.ts                 NEW
frontend/src/components/features/tailored-resume/__tests__/quota-chip.test.tsx  NEW
frontend/src/components/v8/screens/readiness-screen.tsx                   EDITED (wire button + chip)
```
