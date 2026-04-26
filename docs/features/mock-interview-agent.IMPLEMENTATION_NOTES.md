# Mock Interview Agent — Implementation Notes (Phase 1 MVP)

**Date shipped:** 2026-04-25
**Spec:** [mock-interview-agent.md](mock-interview-agent.md)
**Companion:** [tailored-resume-agent.IMPLEMENTATION_NOTES.md](tailored-resume-agent.IMPLEMENTATION_NOTES.md)

---

## What was built

Phase 1 MVP of the **Mock Interview Agent** — a memory-aware, calibrated, voice-capable mock interview platform with three modes (Behavioral, Technical Conceptual, Live Coding), a four-sub-agent backend architecture, cost-capped LLM orchestration, and a full post-mortem report flow.

The default Job Readiness → Interview Coach screen now embeds the new workspace; the prior demo coach UI has been removed.

---

## File layout (additions)

### Backend

```
backend/
├── alembic/versions/0038_mock_interview_v3.py        # migration
├── app/
│   ├── models/mock_interview.py                      # 5 new models
│   ├── models/interview_session.py                   # extended (target_role, level, jd_text, voice_enabled, total_cost_inr, share_token)
│   ├── schemas/mock_interview.py                     # request/response schemas
│   ├── agents/mock_sub_agents.py                     # 4 sub-agent classes
│   ├── agents/prompts/
│   │   ├── mock_question_selector.md
│   │   ├── mock_interviewer.md
│   │   ├── mock_scorer.md
│   │   └── mock_analyst.md
│   ├── services/
│   │   ├── mock_interview_service.py                 # MockSessionOrchestrator
│   │   ├── mock_memory_service.py                    # WeaknessLedger
│   │   ├── mock_pattern_detector.py                  # filler/hedge/evasion analysis
│   │   └── mock_rubric_engine.py                     # mode-specific rubrics
│   └── api/v1/routes/mock_interview.py               # /api/v1/mock/...
└── tests/test_services/test_mock_interview_service.py
```

### Frontend

```
frontend/src/
├── lib/hooks/use-mock-interview.ts                   # React Query hooks
├── components/features/mock-interview/
│   ├── index.ts                                      # public surface + feature flag
│   ├── copy.ts                                       # all user-facing strings
│   ├── analytics.ts                                  # mockAnalytics wrapper
│   ├── use-voice-layer.ts                            # Web Speech API STT + TTS
│   ├── use-pyodide.ts                                # Live coding sandbox
│   ├── mode-picker.tsx
│   ├── pre-session-setup.tsx
│   ├── session-chat.tsx                              # Behavioral / Conceptual UI
│   ├── live-coding.tsx                               # Live Coding split view
│   ├── report.tsx                                    # post-mortem
│   └── workspace.tsx                                 # stage orchestrator
└── app/(public)/mock-report/[token]/page.tsx         # public read-only share page
```

### Docs

```
docs/features/
├── mock-interview-agent.md                           # spec
└── mock-interview-agent.IMPLEMENTATION_NOTES.md      # this file
```

---

## Voice provider chosen + latency profile

| Decision | Choice | Reason |
|---|---|---|
| **STT** | Web Speech API (browser native, `webkitSpeechRecognition` shim) | Free, ~0ms streaming, Chrome / Edge / Safari coverage. Whisper deferred to Phase 2 if accent accuracy complaints arise. |
| **TTS** | `window.speechSynthesis` (browser native) | Zero server cost. Quality acceptable for MVP. Optional path for OpenAI TTS / ElevenLabs Flash via `NEXT_PUBLIC_USE_SERVER_TTS=true` is documented in `use-voice-layer.ts` but not wired. |

**Latency budget — per-turn breakdown (target & profile method):**

| Stage | Target | Where measured |
|---|---|---|
| Student finishes speaking → final transcript ready | <100ms | `useVoiceLayer.timeToFirstWordMs` recorded; final transcript fires on `recognition.onend` |
| API roundtrip → Scorer + Interviewer reply | <1.5s | `latency_ms` logged on `/sessions/{id}/answer` (route writes one `MockCostLog` per sub-agent) |
| TTS playback start | <300ms | browser-native, instant |
| **End-to-end first sound from interviewer** | **<2.0s P50, <2.5s P95** | derived from cost-log latency_ms + voice playback |

The orchestrator runs Scorer (Sonnet, ~3s) and Interviewer (Haiku, ~600ms) **sequentially** because the Interviewer's reply depends on a freshly-scored answer. Net per-turn LLM time ≈ 3.5–4s; the next-question selector runs only on `move_on` and runs in parallel-friendly fashion at the orchestrator boundary.

**Voice fallback** is automatic and announced: if `webkitSpeechRecognition` is missing or `mic_denied` is raised, the analytics event `mock.voice.fallback_to_text` fires and the chat surface switches to text input with no further user action.

---

## Cost per session — estimates

| Mode | Avg cost (₹) | P95 cost (₹) | Notes |
|---|---|---|---|
| Behavioral (voice, ~12 min, ~5 questions) | 18 | 28 | Sonnet × QuestionSelector + Sonnet × Scorer + Haiku × Interviewer + Sonnet × Analyst |
| Technical Conceptual (voice, ~15 min, ~5 questions) | 22 | 33 | longer answers → more Sonnet input tokens on Scorer |
| Live Coding (text, ~20 min, ~3 questions) | 16 | 24 | code submissions are dense but fewer turns |

Hard cap: **₹40/session**. Circuit breaker fires in `submit_answer` after every LLM call updates `session.total_cost_inr`. When tripped, the orchestrator:
- skips the next-question selector call
- returns `cost_cap_exceeded: true` in the response
- the frontend hides the input and shows the "End session" CTA

The `MockCostLog` row per sub-agent call drives a future cost dashboard — same pattern as `GenerationLog` in tailored-resume.

---

## Memory — verified behavior

The single most important property of this feature.

| Behavior | Where enforced |
|---|---|
| Every session reads open weaknesses on start | `start_session` → `get_open_weaknesses` |
| Greeting cites the highest-severity unaddressed weakness | `memory_recall_greeting` (returns `None` when nothing severe — silence > generic warmth) |
| Weakness severity blends EMA on recurrence | `record_weakness_signals` — `0.6 × old + 0.4 × new` |
| Concepts scored ≥7 by Analyst flip to `addressed_at` | `complete_session` → `mark_addressed` |
| Stale entries auto-prune | `_prune_stale` runs lazily on each read; 90 days open / 60 days addressed |
| QuestionSelector receives the ledger as input | `start_session` and `submit_answer` build `weakness_ledger` payload before each invoke |

Test coverage: `test_memory_records_and_surfaces`, `test_memory_blends_severity_on_recurrence`, `test_memory_mark_addressed`, `test_memory_recall_silent_without_high_severity`, `test_memory_surfaces_in_next_session_greeting`.

---

## Anti-sycophancy + confidence guardrails — enforcement points

These are duplicated **on purpose** so a refactor that drops one fails visibly:

1. **In every system prompt** ([mock_question_selector.md](../../backend/app/agents/prompts/mock_question_selector.md), [mock_interviewer.md](../../backend/app/agents/prompts/mock_interviewer.md), [mock_scorer.md](../../backend/app/agents/prompts/mock_scorer.md), [mock_analyst.md](../../backend/app/agents/prompts/mock_analyst.md)) — the literal forbidden phrases appear in the prompt and a self-check requires the model to scan its own output before emitting.
2. **In the orchestrator** — `submit_answer` re-checks Scorer confidence and forces `needs_human_review: true` plus prepends *"I'd recommend a human review on this one."* to feedback when below 0.6, even if the Scorer JSON didn't already do it.
3. **In the route layer** — the API exposes `needs_human_review` as an explicit field. The frontend hides numeric scores and shows the qualitative banner instead.
4. **In tests** — `test_anti_sycophancy_bad_answer_flags_would_not_pass`, `test_confidence_threshold_marks_human_review`, `test_analyst_low_confidence_marks_report_for_review`, plus prompt-content checks (`test_scorer_prompt_explicitly_forbids_flattery`, etc.).

---

## Adaptive difficulty — how it actually adapts

`QuestionSelector` receives a `rolling_overall` field on each call (averaged Scorer overall across answered questions in the current session). The prompt instructs:

- rolling ≥ 7 for two consecutive answers → bump difficulty by ≥0.15
- rolling ≤ 4 → drop by ≥0.15 AND emit a probe-style follow-up
- If a WeaknessLedger entry has severity ≥0.6 and matches the current mode, it must appear in one of the first three core questions (`source: "adaptive_followup"`).

Test: `test_adaptive_difficulty_scales_with_rolling_overall` — feeds two scored-8.5 answers and asserts the third QuestionSelector call sees `rolling_overall ≥ 7.0` and `is_warmup: false`.

---

## Sub-agent split — why we paid this cost up front

| Sub-agent | Model | When |
|---|---|---|
| QuestionSelector | Sonnet | Pre-session + after each `move_on` |
| Interviewer | Haiku | Every answer turn |
| Scorer | Sonnet | Every answer turn |
| Analyst | Sonnet | Once on `complete_session` |

Could MVP have crammed all four into one big prompt? Yes. Why we didn't:
- **Cost ratio.** Interviewer fires every turn; Sonnet would 4–6× the per-session bill.
- **Latency profile.** Interviewer must reply in <1s for voice; Sonnet doesn't deliver that consistently. Scorer and Analyst can take 3–5s — fine.
- **Calibration.** A single prompt that does conversation + scoring tends to over-flatter (the model wants to "be a good conversation partner"). Splitting them means the Scorer sees only the question + answer + rubric, with no conversational pressure to soften.

---

## Spec deviations & why

| Deviation | Reason |
|---|---|
| **OpenAI TTS not wired in MVP** — used browser SpeechSynthesis | Avoids a server-side TTS dependency for MVP. The hook exposes a `speak(text)` API that an OpenAI/ElevenLabs implementation can drop into. |
| **Web Speech API only — no Whisper** | Phase 2. Web Speech covers ≥85% of expected English-speaking users at zero infra cost. Whisper is the right answer when accent / non-English support becomes a constraint. |
| **Live coding tests are synthetic stdout-only** — no test harness in MVP | The Scorer evaluates submission text including stdout/stderr; a structured test runner (Judge0 or similar) is Phase 2. |
| **No real PostHog wiring** — `mockAnalytics` no-ops in dev | The platform doesn't have PostHog-the-frontend wired anywhere yet (despite a `posthog/` config folder). The wrapper is ready to flip when PostHog is added. |
| **No automatic deprecation of legacy `/api/v1/interview/*` routes** | The legacy Redis-based interview path and v2 sessions remain functional. Decision: mark deprecated in code comments; fold into v3 in Phase 1.5 once we have prod traffic data. The new `/api/v1/mock/*` is the canonical path. |

---

## What's stubbed / deferred

| Item | Where | Phase |
|---|---|---|
| **System Design mode** | Orchestrator raises `ValueError` on `mode: "system_design"`; mode picker tile is disabled with a "Phase 2" badge | Phase 2 |
| **Case mode (PM-flavor)** | Not implemented; spec mentions it as Phase 2 explicitly | Phase 2 |
| **Mentor share** | `share_token` issues a public read-only link; no human reviewer comment thread | Phase 2 |
| **Multi-language live coding** | Pyodide is Python-only | Phase 2 (Judge0) |
| **Real PostHog events** | `analytics.ts` no-ops without `window.posthog` | When platform adds PostHog |
| **Audio blob storage for replay** | Only the transcript is stored — `audio_ref` column is nullable and unused in MVP | Phase 2 (consent UX needed first) |
| **Voice quality upgrade (ElevenLabs / OpenAI TTS)** | browser SpeechSynthesis is the default | Phase 2 |
| **Whisper STT fallback** | Web Speech API is the only path | Phase 2 |
| **Cost dashboard** | `MockCostLog` rows are written, but no admin UI surfaces them yet | Phase 2 |

---

## Backwards compatibility

- The legacy `interview_sessions` table gains 6 new columns; all are nullable or have server defaults — no breaking change for existing v2 sessions.
- The legacy v2 endpoints (`/api/v1/interview/sessions/*`) still work and read/write the same table.
- The new v3 endpoints (`/api/v1/mock/sessions/*`) write to the same `interview_sessions` rows but populate `target_role`, `level`, etc., and write child rows to `mock_questions` / `mock_answers` / `mock_session_reports`.
- The frontend `useStartSession`/`useSubmitAnswer` hooks (legacy v2) are untouched; the new feature uses `useStartMockSession`/`useSubmitMockAnswer`. The readiness screen no longer imports the legacy hooks.

---

## Open questions for next milestone

1. **First-question pre-warming.** Right now the QuestionSelector blocks the start handshake. Could we pre-generate a likely first question on `/mock/sessions/preview` (background) and adopt it on actual start? Saves ~2s on session entry. Requires session-staging table.
2. **Adaptive vs. user override.** Should the student be able to say "ask me a harder one" mid-session? Cheap to add (`force_difficulty` on submit), but it's also an honesty concern — strong students often *think* they want harder, then fall apart.
3. **Cross-mode memory.** Currently the WeaknessLedger doesn't filter by mode when surfacing greetings. Is "you struggled with STAR-Result last time" relevant to a Conceptual session? Probably not. Plan: tag concepts with mode and only surface matching ones in the greeting.
4. **Cost cap UX.** The cap is currently a hard stop. Should we let the user "buy more" via a single click that bumps the cap to ₹80? (Phase 2 if monetization arrives.)
5. **Voice consent.** We're currently not storing audio. If we add Phase 2 replay, we need a clear consent ramp + an "delete my audio" path (GDPR/DPDP).

---

## Test coverage map

```
tests/test_services/test_mock_interview_service.py
├── test_pattern_detector_counts_fillers
├── test_pattern_detector_aggregate_confidence_score
├── test_memory_records_and_surfaces
├── test_memory_blends_severity_on_recurrence
├── test_memory_mark_addressed
├── test_memory_recall_silent_without_high_severity
├── test_start_session_creates_session_and_question
├── test_memory_surfaces_in_next_session_greeting              ← memory + adaptation
├── test_adaptive_difficulty_scales_with_rolling_overall       ← adaptive difficulty
├── test_confidence_threshold_marks_human_review               ← confidence threshold
├── test_cost_cap_circuit_breaker                              ← cost cap
├── test_anti_sycophancy_bad_answer_flags_would_not_pass       ← anti-sycophancy
├── test_complete_session_writes_report_and_addresses_weaknesses
├── test_analyst_low_confidence_marks_report_for_review
├── test_system_design_mode_is_phase_2_stub
├── test_scorer_prompt_explicitly_forbids_flattery             ← prompt-level guardrail
├── test_interviewer_prompt_forbids_flattery_phrases
├── test_analyst_prompt_requires_strengths_with_evidence
└── test_selector_prompt_documents_adaptive_rule
```

All five mandatory test categories from the brief are covered:
- Adaptive difficulty ✓
- Memory across sessions ✓
- Anti-sycophancy ✓
- Confidence threshold honoring ✓
- Cost cap circuit breaker ✓
