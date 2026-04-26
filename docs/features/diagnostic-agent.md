# Feature Spec: "Am I Ready?" Diagnostic Agent

**Status:** Proposed
**Page:** Job Readiness (anchor feature)
**Tier:** Free for all students (core to product value)
**Logged:** April 25, 2026

---

## 1. One-line Pitch

The conversational front door of the Job Readiness page — answers the two questions every student arrives with ("Am I behind?" / "Am I ready and just stalling?") with evidence-grounded honesty, and routes them to the single most leveraged next action.

---

## 2. Strategic Rationale

**The daily-return engine.** Resume tools are used ~10 times per student lifetime. Mock interviews ~weekly. The diagnostic is used **every time the student opens Job Readiness** — which makes it the single highest-frequency, highest-intent surface on the page. It is to CareerForge what the recovery score is to Whoop and the daily streak is to Duolingo: the question that pulls the student back.

**The page's coherence layer.** Without the diagnostic, Job Readiness is a menu of five tools the student must self-route through. With it, the page feels like one coach with multiple rooms. The diagnostic does the routing; the student doesn't have to guess what they need.

**The emotional anchor.** Job Readiness is the most anxious page in the product. Two opposing fears — "I'm behind" and "I'm ready and stalling" — collide here. A wall of features amplifies the anxiety. A coach who *sees* them defuses it. The diagnostic is the only feature that addresses the anxiety directly.

**Defensibility.** Generic AI tools can answer "am I ready?" with vibes. Only CareerForge can answer it with verified evidence (lessons completed, capstone shipped, mock scores, peer reviews, time-on-task) plus longitudinal memory across sessions. This is the same moat as the resume agent, applied to a higher-frequency surface.

---

## 3. User Flow (Happy Path)

### First-time use

1. Student opens Job Readiness page → sees diagnostic conversational card above the fold.
2. Opens with empathetic prompt: *"Tell me where you're at — I'll tell you where you stand."*
3. Student types or speaks naturally. Agent asks 3-6 well-placed follow-up questions, conditioned on what platform data already reveals (skips redundant questions).
4. Agent delivers structured verdict: **headline + evidence + one next action**.
5. Student clicks the next action → deep-linked into the right tool (lesson, lab, mock interview, resume agent, JD decoder).

### Returning use (where the magic compounds)

1. Student returns days/weeks later.
2. Agent opens with continuity: *"Last time I said your SQL was the gap. You closed it — three labs in. Here's what's next."*
3. Conversation is shorter; agent already knows context.
4. New verdict reflects progress: explicit acknowledgment of what changed, what's now the bottleneck.

---

## 4. The Verdict Structure

Every diagnostic ends with three components, in this order:

### Headline (one sentence, serif, large)

Examples:

- *"You're 2 weeks of focused interview prep from ready."*
- *"Your projects are strong; your story isn't telling them."*
- *"You're ready — what's stopping you is fear, not skill, and that's worth naming."*
- *"You're applying too early. Two more capstone projects will change everything."*
- *"You've been busy, not effective. Let's fix that."*

The headline must be **specific, falsifiable, and warm**. Generic ("Keep working hard!") is a failure.

### Evidence (3-5 chips, each linked to source)

Mix of strengths and gaps. Examples:

- ✓ "Shipped 4 capstones in the last 60 days" → links to capstone gallery
- ✓ "Mock interview score up 31% over last 3 sessions" → links to mock history
- ⚠ "No system design exposure yet" → links to recommended path
- ⚠ "Resume hasn't been updated since your last project" → links to resume agent

Each chip cites a source. Unsourced chips are forbidden.

### Next Action (single primary button)

**One** action. Not a list. Not "here are 3 options." The agent picks the most leveraged thing and commits.

The button is deep-linked: clicking it routes the student to the exact lesson, lab, mock setup, or tool — pre-configured if possible.

---

## 5. Architecture & Components

### 5.1 Sub-agents

| Sub-agent                       | Role                                                                   | Model tier                | Latency                 |
| ------------------------------- | ---------------------------------------------------------------------- | ------------------------- | ----------------------- |
| **DiagnosticInterviewer** | Conversational layer — opens, listens, probes, follows up             | Fast model, streaming     | <1.5s/turn              |
| **DataReader**            | Pulls verified platform data into structured snapshot                  | Deterministic service     | Pre-conversation, async |
| **VerdictGenerator**      | Synthesizes conversation + snapshot into headline/evidence/next-action | Strong reasoning model    | 3-5s, runs once at end  |
| **ActionRouter**          | Maps verdict to the single best next action with deep link             | Rule-based + LLM fallback | <500ms                  |
| **MemoryService**         | Stores prior diagnoses, surfaces relevant context                      | DB + retrieval            | <200ms                  |

### 5.2 Backend services

- `DiagnosticOrchestrator` — manages session lifecycle, routes between sub-agents, handles state.
- `StudentSnapshotBuilder` — aggregates verified platform data: lessons, capstones, code submissions, mock scores, peer reviews, time-on-task, resume freshness, JD targets.
- `EvidenceValidator` — for every claim in the verdict, traces to source. Rejects and regenerates if a claim has no source. Hard guardrail.
- `AntiSycophancyEvaluator` — runs sample verdicts against an eval set; flags overly positive or hedging language. CI-integrated.
- `NextActionCatalog` — registry of all routable actions across the product (lessons, labs, mocks, tools) with metadata for matching.

### 5.3 Data models (key entities)

- `DiagnosticSession` — turns, snapshot ref, verdict, next action, timestamps, total cost, model used
- `Verdict` — headline, evidence list (each with source), next action ref
- `StudentSnapshot` — denormalized cache of verified data at session start
- `WeaknessLedger` — shared with mock interview agent. Per-student rolling record of identified weaknesses, dates surfaced, dates resolved.
- `NextActionLog` — verdict's recommended action, whether the student clicked it, whether they completed it within 24h (north-star metric).

### 5.4 LLM strategy

- **DiagnosticInterviewer:** Fast streaming model. Sonnet-tier or equivalent. System prompt loaded with student snapshot, prior session memory if any, conversational style guide.
- **VerdictGenerator:** Strongest reasoning model available. Runs once. Outputs structured JSON (headline, evidence array with source IDs, next action ID). Schema-enforced.
- **Anti-sycophancy:** Hard-coded into all system prompts. Eval set includes deliberately weak student profiles; agent must give honest verdicts, not reassurance.
- **Evidence grounding:** VerdictGenerator can only cite from `StudentSnapshot`. Validator checks every evidence chip's source ID exists in the snapshot. Reject + regenerate (max 2 retries) if validation fails.

---

## 6. Critical Design Decisions & Tradeoffs

### Decision 1: Conversation, not form

- **Tradeoff:** Forms convert better short-term; conversation has higher abandonment risk.
- **Why:** The whole point is the page feels like a coach. A multi-step form turns the diagnostic into a quiz, which kills the emotional anchor and undermines every downstream feature. The page's coherence depends on this feeling.

### Decision 2: One next action, not a list

- **Tradeoff:** Some students want options; we're removing them.
- **Why:** Decision fatigue is the dominant failure mode. Across learning products, single-CTA flows convert 2-3x better than menu flows for next-action prompts. Students can ask "what else?" — but the *default* surface is one action.

### Decision 3: Memory in MVP, not Phase 2

- **Tradeoff:** Significant additional complexity; longitudinal data models from day one.
- **Why:** Without memory, the diagnostic feels generic — no different from ChatGPT with platform data plugged in. With memory, the agent feels like a coach who knows the student. That's the moat. Memory is not a polish feature; it's the product.

### Decision 4: Calibrated honesty over reassurance

- **Tradeoff:** Some students will be uncomfortable. We accept this.
- **Why:** Sycophantic AI trains delusion. A student who's been told "you're doing great!" for 3 months and then bombs interviews blames the platform, churns, and badmouths it. Honest-but-warm tone is harder to engineer but produces better outcomes and higher trust. Tone target: a senior friend in the industry, not a cheerleader.

### Decision 5: Evidence-grounded verdicts, no exceptions

- **Tradeoff:** Engineering effort for the validator + occasional regeneration cost.
- **Why:** The agent's authority comes from being right. One hallucinated claim ("you've completed 6 capstones" when they've completed 2) destroys trust permanently. Hard guardrail required.

### Decision 6: Diagnostic ships before resume agent and mock interview

- **Tradeoff:** Reverses the original specification order.
- **Why:** Resume and mock are used episodically. Diagnostic is used every visit. Building the high-frequency anchor first ensures every subsequent agent has a router pointing students to it at the right moment. Reverse order leaves the page incoherent for months.

### Decision 7: No voice in MVP

- **Tradeoff:** Voice would feel premium; we're shipping text-only first.
- **Why:** The diagnostic is short-form and primarily about reflection — voice adds cost and latency without much value at this conversation length. Mock interview is where voice matters. If the mock voice layer ships first and is trivial to reuse, revisit.

---

## 7. Risks & Mitigations

| Risk                                                       | Mitigation                                                                                                                                                                 |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent gives inaccurate verdicts based on hallucinated data | EvidenceValidator hard guardrail; reject unsourced claims; regenerate up to 2x; alert on repeated failures                                                                 |
| Tone reads as harsh instead of warm                        | Anti-sycophancy eval set + tone eval set; weekly sample review by team; dedicated `copy.ts` for opening lines                                                            |
| Students dislike "one action" and feel restricted          | A/B test: single action vs. single + "show alternatives" link. Measure follow-through rate, not satisfaction                                                               |
| Memory feels surveillance-like rather than supportive      | Tone of memory references is warm, never reproachful. ("You closed that gap — well done" not "Last time you failed at SQL"). Eval the memory phrasing.                    |
| Cost spirals if students chat extensively                  | Soft cap conversation at 8 turns. Agent gracefully wraps and delivers verdict. Hard cost cap at ₹15.                                                                      |
| Verdict generator output schema drift                      | Strict JSON schema validation. Reject malformed outputs and regenerate.                                                                                                    |
| Cold start for first-time users with thin platform data    | Special prompt mode for low-data students. Verdict acknowledges uncertainty: "I don't have enough yet to tell you where you stand. Let's start with one week of activity." |

---

## 8. Success Metrics

**North-star:** `% of diagnostic sessions where the suggested next action is completed within 24h`. Build the dashboard for this on day one.

**Activation:** % of Job Readiness page visits that open the diagnostic.
**Engagement:** Average sessions per active student per week.
**Trust:** % of verdicts where the next action is clicked.
**Retention proxy:** % of students who return for a 2nd diagnostic within 7 days.
**Quality (manual):** Weekly sample review (50 sessions) for honesty calibration, evidence accuracy, tone fit. Score 1-5; track median.
**Honesty signal:** % of verdicts that surface gaps explicitly (vs. all-positive). Watch for sycophancy drift.

---

## 9. Build Phases

**Phase 1 (MVP, 4-6 weeks):** Conversational text interface, snapshot builder, verdict generator, evidence validator, action router, memory service, anti-sycophancy evals, north-star instrumentation.

**Phase 2 (post-launch, 4-6 weeks):** Voice input/output (if mock interview voice layer exists), richer memory surfacing UI ("your journey" view), shareable verdict (mentor view), low-data cold-start prompts refined.

**Phase 3 (3+ months):** Multi-session pattern detection (e.g., "you've stalled 3 weeks in a row — let's talk"), proactive nudges (push notification when verdict suggests urgent action), integration with calendar for time-blocked next actions.

---

## 10. Open Questions

- Should the diagnostic auto-trigger after major platform events (capstone shipped, lesson streak broken), or stay pull-based?
- How do we handle conflicting student input vs. platform data? (Student says "I'm ready" but data says no — does the agent push back, ask why, or accept and recalibrate?)
- Do we surface memory references opt-in or default-on? (Some students might find it intrusive on session 2.)
- Should the verdict be shareable with mentors/parents/peers? Privacy implications.
- Long-term: can the diagnostic be used pre-platform (free trial) as a top-of-funnel hook?

---
