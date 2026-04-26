# Feature Spec: Mock Interview Agent

**Status:** In implementation (Phase 1 MVP)
**Page:** Job Readiness → Interview Coach
**Tier:** Free with cost-cap (₹40/session hard cap, ~₹15–25 typical)
**Logged:** 2026-04-25

---

## 1. One-line Pitch

The only mock interview agent that already knows what the student has built. Voice-first behavioral, live-coding technical, and conceptual modes that read from verified platform activity (lessons, capstones, code, peer reviews, prior mocks) and use that history to ask sharper questions, score honestly, and remember weaknesses across sessions.

---

## 2. Strategic Rationale

**Moat:** Generic AI mock interview tools (Pramp, Interviewing.io's AI, ChatGPT prompts) sit at zero context — every session is cold-start, every score is generic. CareerForge holds primary evidence (skill confidences, exercise submissions, peer reviews, prior mock transcripts), and the only platform that uses that primary evidence to **drive** the interview is the platform that owns it.

**Retention play:** Job Readiness Step 4 (Interview Coach) is currently a static demo. Replacing it with a real, calibrated mock changes the page's emotional arc from *"go practice elsewhere"* to *"rehearse with the only tool that knows what you've actually built."*

**The single defensible property:** memory and adaptation. Mock #5 must feel different from mock #1. Without it, this is parity. With it, it's a moat.

---

## 3. User Flow (Happy Path)

1. Student lands on Job Readiness → Interview Coach.
2. **Mode picker:** Technical Conceptual · Live Coding · Behavioral. (System Design + Case = Phase 2.)
3. **Pre-session setup:** target role (default = current goal_contract), level (junior/mid/senior), optional JD paste, voice-or-text toggle, voice-mode permission.
4. **Live session:**
   - Warm-up question (1–2 min) — never the hardest one.
   - Core questions (3–5 depending on time) — adaptive: nail one → next gets harder; fumble → hint, then re-test the concept later.
   - Mid-answer follow-ups + interruptions when student rambles or makes a claim that needs probing.
   - **Behavioral mode mandatory phase:** at the end, agent invites the student to ask *their* questions — and grades the *quality* of those questions.
   - Live Coding: split view with editor + agent chat; agent watches and probes mid-coding.
5. **Post-mortem report** (~30s async after session ends):
   - Per-criterion rubric scores with confidence
   - Pattern detection (filler words, time-to-answer, evasion, strengths)
   - Replay (transcript + audio if voice)
   - One specific next action with deep link
   - Strength surfacing — what they did well
   - Shareable read-only URL
6. **Cross-session memory write:** weaknesses, strengths, and patterns persist into the WeaknessLedger so the next session opens with *"Last time, hashing tripped you up — let's see how it lands now."*

---

## 4. Non-Negotiable Constraints

| Constraint | Reason |
|---|---|
| **Calibrated honesty over sycophancy** | The agent must tell a student their answer would not pass. Tone: tough but warm senior engineer. No "Great answer! Just a small suggestion…" patterns. Anti-sycophancy is in every system prompt + an eval that asserts honest feedback on deliberately bad answers. |
| **No bluffing — confidence scores everywhere** | Every evaluation has a `confidence` field (0.0–1.0). Below 0.6 → agent says "I'd recommend a human review on this one" instead of fabricating a score. |
| **Memory + adaptation across sessions** | Each session must surface ≥1 prior insight when relevant. Stored in `weakness_ledger`. |
| **Voice is first-class for Behavioral + Technical Conceptual** | Filler words, pace, and pauses are measured and surfaced. Text-only voice prep is half the product. |
| **Adaptive difficulty mid-session** | No static question lists. Difficulty floats with the rolling rubric overall score. |
| **Realistic interview structure** | Warm-up → core → student-asks-back (Behavioral mandatory) → wrap-up. |
| **Cost cap: ₹40/session** | Hard. Per-turn cost logged; circuit-break if exceeded. |
| **No streak pressure on mocks** | Lessons get streaks; mocks do not. Weekly cadence is implicit, never enforced. |
| **Design fidelity** | Match v8 readiness aesthetic — `--forest`, `--gold`, `--ink`, Fraunces serif + Inter sans, `.match-card` patterns. |

---

## 5. Architecture

The agent is **not one model** — it's a coordinated system. Build with internal separation; expose as a single user experience.

### 5.1 Sub-agents

| Sub-agent | Role | Model tier | Latency requirement | Avg tokens (in/out) |
|---|---|---|---|---|
| **QuestionSelector** | Picks next question from role + level + JD + platform history + WeaknessLedger | `claude-sonnet-4-6` (smart) | Async, pre-session OK; mid-session ≤3s | 1500 / 250 |
| **Interviewer** | Real-time conversation: asks, probes, reacts, interrupts | `claude-haiku-4-5` (fast) | <1s response; voice-streaming preferred | 1200 / 180 |
| **Scorer** | Rubric-based per-answer evaluation with confidence | `claude-sonnet-4-6` (smart) | Per-answer ~3–5s acceptable | 800 / 400 |
| **Analyst** | Post-session post-mortem: patterns, trends, next action | `claude-sonnet-4-6` (smart) | Async after session, 30–60s | 4000 / 800 |

Each sub-agent has its own system prompt at [backend/app/agents/prompts/mock_interview_*.md](../../backend/app/agents/prompts/). Anti-sycophancy + confidence requirements appear in **every** prompt — not centralized — so a refactor that drops the system prompt drops the guardrail visibly.

### 5.2 Backend services

| Service | Responsibility | File |
|---|---|---|
| **MockSessionOrchestrator** | Session lifecycle, sub-agent routing, state. Cost-cap circuit breaker. Writes WeaknessLedger on completion. | `services/mock_interview_service.py` |
| **RubricEngine** | Mode-specific rubrics (correctness, communication, edge cases, depth, etc.) with per-criterion scoring + confidence | `services/mock_rubric_engine.py` |
| **PatternDetector** | Runs over full transcript: filler word counts, time-to-answer, evasion patterns, strength patterns | `services/mock_pattern_detector.py` |
| **MemoryService** | Loads + writes WeaknessLedger for QuestionSelector and report greetings | `services/mock_memory_service.py` |
| **CostTracker** | Per-turn cost accumulator; raises CostCapExceeded when over ₹40 | inline in orchestrator |
| **SandboxService (Pyodide adapter)** | Executes student Python code submitted in Live Coding mode, browser-side. Backend stores submissions only. | reuses `services/sandbox_service.py` |

### 5.3 Data model

**Reuses existing:**
- `interview_sessions` — extended with `target_role`, `level`, `jd_text`, `total_cost_inr`, `report_id`, `share_token`, `voice_enabled`. The existing `mode` enum widens from `behavioral|technical|system_design` to add `live_coding` and `technical_conceptual` (the existing `technical` becomes `technical_conceptual`; `system_design` is a Phase 2 stub).

**New tables (migration `0038_mock_interview_v3`):**

| Table | Purpose |
|---|---|
| `mock_questions` | Per-session questions: text, mode, difficulty (0.0–1.0), rubric_id, source (`generated`/`library`/`adaptive_followup`), parent_question_id |
| `mock_answers` | Per-question answer: text (or audio_ref), evaluation JSON (rubric scores + confidence), latency_ms, filler_word_count, time_to_first_word_ms |
| `mock_session_reports` | Post-mortem analysis: rubric_summary, patterns JSON, strengths[], next_action, share_token |
| `mock_weakness_ledger` | Per-student rolling: skill_or_concept, severity (0.0–1.0), evidence_session_ids[], last_seen_at, addressed_at |
| `mock_cost_log` | Per-turn LLM cost: session_id, sub_agent, model, in/out tokens, cost_inr, latency_ms |

UUID PKs, timestamps, soft delete where appropriate. JSON columns use `sa.JSON` for SQLite test compatibility (per `lessons.md`).

### 5.4 LLM strategy

| Stage | Model | Why |
|---|---|---|
| QuestionSelector (pre-session + adaptive) | Sonnet | Reasoning over history matters |
| Interviewer (live turns) | Haiku | Fast + cheap; voice-streaming friendly |
| Scorer (per answer) | Sonnet | Calibration + confidence accuracy |
| Analyst (post-mortem) | Sonnet | Synthesis quality |

**Cost cap:** ₹40/session hard. Estimated baseline ₹15–22 per full session (10 min Behavioral, voice mode).

**Anti-sycophancy enforcement (in every prompt):**
> *"You will not flatter. You will not soften unjustified praise. If the answer would not pass a real interview, you say so plainly — warm in tone, ruthless in honesty. The phrase 'Great answer!' is forbidden. The phrase 'I'd recommend human review' is required when your confidence is below 0.6."*

### 5.5 Frontend

New section on Job Readiness `InterviewCoachView` — replaces the mock UI in [readiness-screen.tsx:878-1053](../../frontend/src/components/v8/screens/readiness-screen.tsx#L878-L1053). The route `/career/mock` houses the in-session UI and post-mortem.

| Component | Path |
|---|---|
| Mode picker tiles | `components/features/mock-interview/mode-picker.tsx` |
| Pre-session setup | `components/features/mock-interview/pre-session-setup.tsx` |
| In-session chat (Behavioral / Conceptual) | `components/features/mock-interview/session-chat.tsx` |
| Voice waveform + STT/TTS | `components/features/mock-interview/voice-layer.tsx` |
| Live coding split view | `components/features/mock-interview/live-coding.tsx` |
| Post-mortem report | `components/features/mock-interview/report.tsx` |
| Shareable report page | `app/(public)/mock-report/[token]/page.tsx` |

---

## 6. Critical Design Decisions & Tradeoffs

### Decision 1: Sub-agents are separated even though MVP could be one big prompt
- **Tradeoff:** ~3 days of upfront structure cost.
- **Why:** Cost (Haiku for live turns; Sonnet for scoring + analysis) and latency profiles are too different to conflate. Worth it from week 1.

### Decision 2: Voice mode in MVP
- **Tradeoff:** STT/TTS infra + latency budget.
- **Why:** Behavioral text-only is a writing exercise, not interview prep. Half-product.

### Decision 3: Cross-session memory in MVP
- **Tradeoff:** New table + ledger maintenance + report-greeting wiring.
- **Why:** Without it, the product is parity. With it, mock #5 feels custom — that's the moat.

### Decision 4: Web Speech API for STT, OpenAI TTS for output
- **Tradeoff:** Browser-only STT (no server-side transcription); voice quality good but not ElevenLabs-level.
- **Why:** Web Speech API is free, browser-native, ~0ms (live streaming), and works in Chrome / Edge / Safari. OpenAI TTS streams in <500ms with passable quality at ₹0.5–1 per turn. ElevenLabs Flash + Whisper move to Phase 2 if quality complaints arise.

### Decision 5: Pyodide for Live Coding sandbox
- **Tradeoff:** Python-only at MVP.
- **Why:** Pyodide loads ~10MB once, runs entirely browser-side, zero server cost. Multi-language via Judge0 deferred.

### Decision 6: Confidence score required on every evaluation
- **Tradeoff:** Adds 1 token + 1 prompt requirement per call.
- **Why:** "I don't know — recommend human review" is the most credibility-positive thing this agent can do. Bluffing once destroys trust.

### Decision 7: Replace existing `interview_service.py` (Redis path) and consolidate into v3
- **Tradeoff:** Frontend touches; `/api/v1/interview/start`, `/api/v1/interview/stream`, `/api/v1/interview/{id}/debrief` get deprecated and redirected to `/api/v1/mock/sessions/*`.
- **Why:** Two parallel paths (Redis + v2 DB) drift. The prompt's required architecture supersedes both.

### Decision 8: First mock free regardless of cost-cap state; subsequent throttled by cost-cap only
- **Tradeoff:** ~₹15 of cost on the first mock from any user, including bots.
- **Why:** Friction at re-entry is far more expensive than the marginal LLM cost. Mirrors tailored-resume's first-resume-free rule (which proved out).

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Agent hallucinates platform-specific facts (e.g., "you struggled with hashing") | QuestionSelector + Analyst can only cite from `weakness_ledger`, `interview_sessions`, `exercise_submissions`. Hard constraint in prompt + post-generation validator. |
| Voice latency >1.5s ruins flow | Web Speech API streams partial transcripts; Interviewer streams via SSE; OpenAI TTS streams. Profile every turn; circuit-break to text if latency exceeds 2.5s consistently. |
| Cost explodes on a 30-min session | Hard ₹40 cap with per-turn check. Voice traffic auto-routes to Haiku for Interviewer. |
| Sycophancy regression | Eval suite feeds 5 deliberately bad answers per mode and asserts the agent says "would not pass" or equivalent. CI-gated. |
| Confidence threshold not honored | Test that low-confidence Scorer outputs are not surfaced as numeric scores in the UI. |
| "Memory" becomes annoying ("you said this 3 sessions ago") | WeaknessLedger has `addressed_at` — once a weakness is addressed in a later session with score ≥7, it stops surfacing. |

---

## 8. Success Metrics

**Activation:** % of Job Readiness visitors who complete ≥1 mock session.
**Retention:** % of users who return for a 2nd mock within 14 days.
**Quality (instrumented):**
- Average rubric overall score across sessions (per user, trend-tracking).
- "Memory recall" hit-rate: did the next session reference a prior weakness when one existed? Target ≥80%.
- Confidence-honoring rate: low-confidence Scorer outputs that did NOT surface a fabricated score. Target 100%.
**Cost:** P95 cost per session < ₹30; mean < ₹22.
**Voice:** P95 first-token latency < 1.8s, P50 < 1.0s.

Analytics events: `mock.session.started`, `mock.session.completed`, `mock.session.abandoned`, `mock.report.viewed`, `mock.report.shared`, `mock.next_action.clicked`, `mock.voice.fallback_to_text` (when latency forced fallback), `mock.confidence.below_threshold` (when agent declined to score).

---

## 9. Build Phases

**Phase 1 (MVP, this spec):**
- 3 modes (Technical Conceptual, Live Coding, Behavioral)
- Voice for Conceptual + Behavioral (Web Speech STT + OpenAI TTS)
- Adaptive difficulty + mid-answer probes
- Cross-session memory (WeaknessLedger)
- Post-mortem report with patterns, replay, share
- Cost cap circuit breaker
- Anti-sycophancy + confidence guardrails
- Feature flag `features.mockInterviewAgent`

**Phase 2:**
- System Design mode (whiteboard or structured component canvas)
- Case mode (product / business cases for PM-flavor roles)
- ElevenLabs Flash voice (better quality)
- Whisper STT fallback (better non-English accuracy)
- Multi-language Live Coding (Judge0)
- Mentor-share (live human review of a recorded session)

**Phase 3 (anti-features — explicitly never building):**
- ❌ Leaderboards. Mock interview anxiety is the problem; ranking it is the anti-product.
- ❌ Streaks on mocks. Rehearsal cadence should be implicit and gentle.
- ❌ "Your friends took this mock!" social pressure.

---

## 10. Open Questions

- Should target role default from `goal_contract.success_statement`, or always require explicit input? *(Recommendation: pre-fill from goal_contract, allow override.)*
- How long should `weakness_ledger` entries persist before auto-pruning? *(Phase 1: 90 days OR `addressed_at IS NOT NULL` for 60 days, whichever first.)*
- Voice consent: should we store the audio blob, or just the transcript? *(Phase 1: transcript only. Blob storage is an explicit Phase 2 opt-in for replay UX.)*
- Should the report be public-by-default-anonymous or private-by-default-shareable? *(Recommendation: private-by-default. `share_token` is generated only when student clicks "Share read-only link.")*
