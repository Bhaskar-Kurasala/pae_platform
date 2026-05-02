---
title: Pass 3h — Interrupt Agent + Proactive Engagement Loop
status: Final — implementation contract for the proactive layer
date: After Pass 3g sign-off, before D16 implementation
authored_by: Architect Claude (Opus 4.7)
purpose: Close Pass 2's "agents and background jobs are parallel systems with no closed loop" finding. Design the interrupt_agent that reads student_risk_signals (written by existing risk-scoring-nightly), decides when and how to nudge proactively, picks channels (in-app DM vs. email), and respects frequency caps, quiet hours, and student preferences. Folds in the PG-1 FastAPI lifespan loader fix and the EscalationLimiter Redis blocker.
supersedes: nothing — implements Pass 3a Addendum's interrupt_agent specification
superseded_by: nothing — this is the canonical proactive layer design
informs: D16 (interrupt_agent + progress_report ship together), D9 (PG-1 fix gates the entire proactive layer), and indirectly all future deliverables that emit risk signals or memory writes
implemented_by: D16 (primary build), D9 (PG-1 fix prerequisite)
depends_on: D6 (proactive primitive — @proactive decorator and webhook signature verification), D7 (AgenticBaseAgent), Pass 3a Addendum (interrupt_agent in canonical roster), Pass 3b (Supervisor; interrupt_agent is invokable through it for ad-hoc triggers), Pass 3c E11 (interrupt_agent capability sketch), Pass 3d Section F.8 (interrupt_agent tools), Pass 3e (curriculum graph for context-aware nudges), Pass 3f (cost ceilings — proactive runs are platform cost, not student-charged), Pass 3g (safety wrapping applies to nudge content)
---

# Pass 3h — Interrupt Agent + Proactive Engagement Loop

> Pass 2 found that AICareerOS has parallel systems that don't talk to each other. Risk-scoring-nightly writes risk signals nobody reads. Outreach-automation sends emails nobody chose to send. The proactive layer exists in fragments. This pass makes it cohesive — one agent (the interrupt_agent) reads the signals and makes the calls.

> This pass also resolves two long-standing infrastructure gaps: PG-1 (the FastAPI lifespan loader bug that prevents proactive agents from subscribing in HTTP processes) and the EscalationLimiter Redis-only follow-up. Both ship in D9 prior to D16's interrupt_agent build.

---

## Section A — Why This Pass Exists

### A.1 The structural finding from Pass 2

Three observations:

1. **`risk-scoring-nightly` writes to `student_risk_signals`.** Computes who's struggling, plateauing, dropping off. Runs nightly via Celery beat.

2. **Existing `outreach_automation` infrastructure can send emails to students.** Has rate limits, content checks, unsubscribe handling. Triggered by various ad-hoc paths.

3. **No agent connects (1) and (2).** Nobody decides "this student is at risk according to (1), so let's send an outreach via (2) with this content." The proactive layer is a tool kit waiting for an orchestrator.

The Pass 3a Addendum named this orchestrator: `interrupt_agent`. Pass 3c E11 sketched its capability. This pass nails down the design.

### A.2 What "closed loop" means

A closed loop is one where the system's actions affect the system's inputs. Today:

- Risk signals → nothing (open loop)
- Engagement signals → risk signals (closed) → nothing (open again)
- Agent interactions → memory bank → nothing (open at the system level)

After Pass 3h:

- Risk signals → interrupt_agent decisions → nudges sent → student responds (or doesn't) → adherence tracked → fed back to risk signals
- The student's reaction to a nudge becomes input for the next nudge decision
- A student who consistently ignores nudges gets fewer of them
- A student who responds well to a particular tone or channel gets more of those

Closed loop also means: if the system makes a bad call (over-nudges, under-nudges, picks wrong channel), there's a measurable signal somewhere that lets us fix it.

### A.3 The boundary: what interrupt_agent IS NOT

To prevent scope creep:

- **Not the only proactive entry point.** `progress_report` (weekly Celery, sends summaries) and `content_ingestion` (webhook-triggered) are also proactive but aren't interrupts. They're scheduled deliverables. Interrupt_agent specifically handles **risk-driven interventions** outside normal cadence.

- **Not a chatbot.** It writes nudges; it doesn't carry conversations. When a student replies to a nudge, the reply enters the normal conversation flow and routes through the Supervisor like any other request.

- **Not a billing or marketing channel.** It does not send subscription expiry notices, course recommendations for upselling, or trial-conversion prompts. Those are billing/marketing concerns with their own infrastructure.

- **Not the risk-scoring system.** It consumes risk signals; it doesn't compute them. Risk-scoring stays a separate Celery job; if its logic needs improvement, that's a different deliverable.

- **Not a generic notification system.** It is one consumer of the notification infrastructure. Other consumers (transactional emails, payment receipts, course progress milestones) keep their own paths.

---

## Section B — The Interrupt Agent

### B.1 AgentCapability declaration

```python
CAPABILITY = AgentCapability(
    name="interrupt_agent",
    version=1,
    description=(
        "Proactive engagement specialist. Runs daily for each active student, reads "
        "their risk signals and recent activity, decides whether a nudge would help, "
        "composes the nudge message, and dispatches via the appropriate channel. "
        "Respects quiet hours, frequency caps, and per-student opt-outs. Not directly "
        "invoked by students; runs via Celery beat. Can also be invoked by the "
        "Supervisor for admin-triggered ad-hoc nudges."
    ),
    inputs_required=["student_id"],
    inputs_optional=["override_reason", "force_channel", "test_mode"],
    outputs_provided=["decision", "nudge_message", "channel", "delivery_outcome"],
    typical_latency_ms=5000,
    typical_cost_inr=Decimal("1.50"),
    requires_entitlement=False,  # platform-driven, not student-billed
    handoff_targets=[],
    model_used="claude-sonnet-4-6",
    minimum_tier="standard",  # only nudges paid students; free-tier students aren't enrolled deeply enough
)
```

### B.2 Primitive flags

```python
uses_memory = True       # reads what other agents wrote about this student
uses_tools = True        # reads risk signals, checks recent outreach, composes DMs/emails
uses_inter_agent = False # leaf agent; doesn't hand off
uses_self_eval = True    # nudge quality matters; sample with Critic
uses_proactive = True    # @proactive(cron=...) drives the daily run
```

### B.3 Memory access

**Reads:**

- `mastery:*` and `weak_concepts` — what the student has been working on
- `interaction:plan_adherence:*` — has the student been showing up to their planned sessions
- `feedback:weekly_report:*` — what `progress_report` last said
- `interaction:nudge_sent:*` — past nudges this agent sent (history of what's been tried)
- `interaction:nudge_response:*` — student response to past nudges (engagement / dismissal / pause)
- `pref:nudge_channel`, `pref:quiet_hours`, `pref:nudge_pause_until`, `pref:nudge_tone` — student preferences
- `goal:active` — current goal_contract for context (e.g., "you committed to 8 hours/week")

**Writes:**

- `interaction:nudge_sent:{date}` — what was sent, why, via which channel, with which tone
- `interaction:nudge_decision:{date}` — even when no nudge is sent, log the decision and reason (e.g., "skipped: quiet hours")

The `nudge_decision` log even for non-actions matters: it makes the agent debuggable. "Why didn't this struggling student get a nudge?" → answer is in memory.

### B.4 Tools needed

From Pass 3d Section F.8:

- `read_student_full_context(student_id)` — aggregator returning risk signals + recent activity + memory bank summary
- `check_recent_outreach(student_id)` — reads `outreach_log` to see if student was contacted recently (any channel, any reason)
- `compose_dm(student_id, body, dedup_key)` — writes to `student_inbox` as in-app DM
- `compose_email(student_id, template, vars, dedup_key)` — calls our Email MCP server (Pass 3d Section G.4)
- `schedule_followup(student_id, when, payload)` — writes a `scheduled_outreach` row for future Celery dispatch (deferred follow-ups, e.g., "nudge again in 3 days if still inactive")

Plus universal tools (memory_recall, memory_write, log_event).

### B.5 Output schema

```python
class InterruptAgentOutput(BaseModel):
    decision: Literal[
        "nudge_now",
        "skip_quiet_hours",
        "skip_frequency_cap",
        "skip_paused_by_student",
        "skip_low_severity",
        "skip_no_signal",
        "skip_recent_organic_engagement",
        "schedule_for_later",
    ]

    # If decision == "nudge_now"
    nudge_message: NudgeMessage | None = None
    channel: Literal["in_app_dm", "email"] | None = None
    tone: Literal["check_in", "encouragement", "concern", "milestone_reminder"] | None = None
    severity_basis: Literal["at_risk", "critical"] | None = None

    # If decision == "schedule_for_later"
    scheduled_for: datetime | None = None
    scheduled_reason: str | None = None

    # Always
    reasoning: str  # 2-3 sentences explaining the decision
    confidence: Literal["high", "medium", "low"]


class NudgeMessage(BaseModel):
    subject: str | None = None  # for email channel
    body: str  # the actual message; plain text or simple markdown
    cta_label: str | None = None  # e.g., "Let's pick up where we left off"
    cta_url: str | None = None  # deep link into AICareerOS
    pause_url: str  # always-included unsubscribe / pause link
    estimated_read_seconds: int  # ≤ 30 for nudges; longer = it's a report, not a nudge
```

The `pause_url` is mandatory for every nudge. It's the explicit one-click escape hatch.

### B.6 Decision logic (the prompt blueprint)

The prompt structure (full prompt at `backend/app/agents/prompts/interrupt_agent.md`):

```
[ROLE]
You are the Interrupt Agent in AICareerOS. Your job is to look at one student's
recent context and decide whether a proactive nudge would help. You are NOT a
chatbot. You produce one decision per call: nudge or don't, and if so, with
what message via what channel.

You exist to help students. Most days for most students, the right answer is
"no nudge." Nudge only when there's clear signal that intervention helps and
the timing/frequency rules permit it.

[CONTEXT YOU RECEIVE]
- The student's risk_state and underlying signals
- Their recent activity and engagement pattern
- Past nudges sent and how they were received
- Their preferences (quiet hours, tone, paused state)
- The current local time in the student's timezone
- Their goal_contract for context

[DECISION ORDER — short-circuit at first match]
1. Is the student paused by their own request? → skip_paused_by_student
2. Is it currently within the student's quiet hours? → skip_quiet_hours
3. Has there been a nudge or other outreach in the last N hours (frequency cap)?
   → skip_frequency_cap
4. Has the student organically engaged in the last 24 hours?
   → skip_recent_organic_engagement (no need to nudge a student who's already showing up)
5. Has the student ignored the last 3 nudges?
   → schedule_for_later (pause and try again in a week)
6. Does the risk_state warrant intervention?
   - "healthy" → skip_no_signal
   - "at_risk" or "critical" → continue to step 7
7. Compose nudge:
   - Pick tone based on risk_state and student preferences
   - Pick channel based on student preferences and message type
   - Write the message: short, specific, kind, never preachy
   - Include CTA when appropriate (return-to-AICareerOS link)
   - Always include the pause link

[TONE GUIDANCE]
- check_in: low-pressure curiosity. "Haven't seen you this week — anything blocking you?"
- encouragement: positive framing. "You've put in 6 hours this week. The next concept after RAG is..."
- concern: gentle direct, used only on "critical". "It's been 16 days since your last session — want to set a small goal together?"
- milestone_reminder: factual, non-emotional. "Your capstone deadline is 7 days away."

[CHANNEL GUIDANCE]
- in_app_dm: default. Lower-friction. Visible when student opens app.
- email: use when student hasn't opened the app in 7+ days, OR for milestone reminders that should land outside the app.

[HARD CONSTRAINTS]
- One nudge per student per day, total, across all channels. Cap is global.
- Never use guilt, shame, or comparison to other students.
- Never mention specific other students by name or compare metrics across students.
- Never imply that the student "is failing" or "won't make it."
- The pause link must always be present.
- If you're uncertain whether to nudge, default to NOT nudging.

[OUTPUT]
Return InterruptAgentOutput as strict JSON. The reasoning field is required and
read by ops; write it for them.
```

### B.7 The quiet-hours and timezone concern

The student's local time matters. Three sub-cases:

- **Student has explicit timezone in profile:** use it.
- **Student has no timezone but has IP/locale signal:** infer from past activity logs (pre-computed during the daily run).
- **No signal at all:** default to IST (your platform's primary geography). Conservative quiet hours (10 PM – 8 AM IST).

A student in the US might get a nudge at unfortunate times if we default to IST. v1 accepts this for the small US fraction; post-launch, we improve timezone inference if it becomes a real issue.

### B.8 The frequency cap (global, not per-channel)

"At most one nudge per student per day, across all channels" is enforced via `check_recent_outreach`. If a DM was sent at 9 AM, no email at 6 PM. If an email is scheduled for 8 PM and a DM was already sent, the email is canceled.

Cross-channel coordination uses a single `last_outreach_at` field on the student record (cached in Redis with 24h TTL, sourced from `outreach_log`).

The cap is **global** because students experience nudges across channels as one stream; "you sent me 2 things today" is the right unit.

---

## Section C — The Proactive Trigger Infrastructure

### C.1 The @proactive decorator (D6) and Celery beat

D6 shipped the `@proactive(cron=...)` decorator that makes an agent's method runnable on a schedule. The interrupt_agent uses it:

```python
class InterruptAgent(AgenticBaseAgent):
    name = "interrupt_agent"
    # ... fields ...

    @proactive(cron="0 9 * * *", name="daily_interrupt_check")  # 9 AM IST
    async def daily_interrupt_check(self, scheduler_ctx: SchedulerContext):
        """
        For each active paid student, decide whether to nudge.
        Runs once daily, fan out per student.
        """
        active_students = await self.get_active_students()
        for student_id in active_students:
            await self.run_for_student(student_id)
```

The fan-out per student is sequential within the beat run (rate-limited Celery dispatch) to prevent thundering-herd against the LLM provider.

For 1,000 students × ~3 seconds per run × maybe 30% requiring full LLM evaluation (the others short-circuit at quiet-hours / frequency-cap / no-signal) = ~15-20 minutes for the daily run. Acceptable.

### C.2 The PG-1 fix as prerequisite

PG-1 (Track 5 finding): `_agentic_loader.load_agentic_agents()` is called from Celery boot but NOT from FastAPI lifespan. Webhooks routed via FastAPI find no subscribers and silently drop.

This bug doesn't block daily Celery-driven proactive runs (Celery boots its own loader) but blocks **webhook-driven proactive runs** (e.g., GitHub push triggering content_ingestion).

For interrupt_agent specifically: the daily run works without the PG-1 fix. But interrupt_agent should also be invokable via the canonical `/api/v1/agentic/{flow}/chat` endpoint by admins for ad-hoc nudges (test mode, debugging, manual interventions). That path requires PG-1 to be fixed.

**PG-1 fix lands in D9.** ~5 LOC in FastAPI lifespan calling `_agentic_loader.load_agentic_agents()` before the app accepts requests. Test verifies that webhook-routed agents have subscribers in both Celery and FastAPI processes.

### C.3 The EscalationLimiter Redis follow-up

Track 2 swapped `EscalationLimiter` from in-memory to Redis-backed. The follow-up was: hot-recovery if Redis is down at boot. Today the limiter fails-open with logging, which means escalation rate-limiting is bypassed during Redis outages. Fine for emergency degradation; bad for long-term.

The fix: when Redis recovers, the limiter rebuilds state from `agent_escalations` table (which has timestamped escalation rows). Adds ~30 LOC; ships in D9 alongside the PG-1 fix.

This matters for Pass 3h because **interrupt_agent's "skip if too many recent outreaches" check uses the same EscalationLimiter pattern**. If the limiter is unreliable, interrupt_agent could over-nudge during Redis blips.

---

## Section D — Closed-Loop Measurement

How we know nudges are working.

### D.1 What we track per nudge

When a nudge is sent, we capture:

```python
class NudgeRecord(BaseModel):
    nudge_id: UUID
    student_id: UUID
    sent_at: datetime
    channel: Literal["in_app_dm", "email"]
    tone: str
    severity_basis: str
    nudge_text_hash: str  # for grouping similar nudges in analysis
    cta_url: str | None
```

When the student responds (or doesn't), we capture:

```python
class NudgeResponse(BaseModel):
    nudge_id: UUID
    response_window_hours: int  # 24, 72, 168 measurement windows
    opened: bool          # email open or in-app view
    cta_clicked: bool
    organic_session_started: bool  # student returned to AICareerOS after nudge
    paused_after_nudge: bool       # student clicked the pause link
    response_message: str | None   # if they replied to the DM with something substantive
```

These records live in a new `nudge_records` table (created by D16 migration). Joined with `student_risk_signals` to enable analysis like "students at_risk who got encouragement-tone nudges had a 32% session-return rate vs. 18% without nudges."

### D.2 The adherence loop

The interrupt_agent reads `interaction:nudge_response:*` on its next run. If the last 3 nudges were ignored, it pauses for 7 days. If the last 3 nudges had positive responses, it can be slightly more proactive (lower the threshold for next nudge by one severity step, but never below `at_risk`).

This adaptation is **per-student**, not global. Two students with similar risk signals can get different nudge frequencies based on their personal response history.

### D.3 The dashboards (deferred to Pass 3i)

Operational dashboards for the proactive layer:

- "Nudges sent per day, by channel, by tone, by severity_basis"
- "Response rates per channel/tone/severity combination"
- "Students paused via the pause link — count, reasons, recovery rate"
- "Cohort comparison: at_risk students who got nudged vs. who didn't (control via random hold-out group)"

These dashboards inform pruning and tuning. Pass 3i (scale + observability) builds them; Pass 3h just ensures the data is captured.

### D.4 The hold-out experiment

For the first 8 weeks post-launch, **5% of at_risk students are randomly excluded from nudges** (control group). Their recovery rate vs. the nudged 95% tells us whether nudging is actually working or just adding noise.

If the data shows nudging doesn't help, we recalibrate. If it shows nudging helps for some segments and not others, we segment more carefully. This is the difference between a thoughtful proactive layer and "we built a thing because we could."

The 5% control group is implemented as a deterministic hash on `student_id` so individual students stay in the same bucket consistently. Documented in code with the rollout strategy.

---

## Section E — Channels And Their Properties

### E.1 In-app DM (`student_inbox`)

The default channel for most nudges. Properties:

- **Latency:** delivery is instant; visibility depends on student opening the app
- **Cost:** essentially free (DB write + WebSocket push)
- **Cooldown:** zero — student sees it next time they open
- **Read rate:** high for students who open daily; near-zero for inactive students (which is exactly when they need a nudge most)
- **Reply path:** student can reply directly; reply enters the regular agent flow via the Supervisor

Use for: check-ins, encouragement, milestone reminders for active students.

### E.2 Email (via our own Email MCP server)

The fallback for inactive students. Properties:

- **Latency:** delivery within 1-5 minutes (queued)
- **Cost:** small per-send (transactional email service fees)
- **Cooldown:** subject to outreach_automation rate limits (existing); typically 3-7 days between marketing-class emails
- **Read rate:** ~25-40% open rate depending on segment
- **Reply path:** requires inbound email handling; v1 surfaces replies as `student_inbox` notifications for admin review (no auto-reply via Supervisor)

Use for: students inactive 7+ days, milestone reminders that should land outside the app, critical-severity nudges where multiple channels are warranted.

### E.3 The "future channels" placeholder

WhatsApp, SMS, push notifications are deferred. The architecture supports them via additional MCP servers (similar to email). Adding a channel later is:

1. Build/connect the MCP server
2. Add channel literal to `Channel` enum
3. Update interrupt_agent's prompt with new channel guidance
4. Update channel-selection rules in the decision logic

No deeper architectural changes. The rate-limit and frequency-cap infrastructure handles new channels uniformly.

### E.4 The unsubscribe / pause infrastructure

Every nudge includes a one-click pause link. Clicking it:

- For email: sets `pref:nudge_pause_until = now + 30 days` for that student
- For in-app DM: shows a confirmation dialog ("Pause check-ins for 30 days?"), then same effect

After the pause window, nudges resume. Students can also explicitly opt out forever via account settings (deferred frontend; backend supports the preference).

For email-specific compliance (CAN-SPAM, India's anti-spam laws), every email also includes the standard footer with the platform's address and a hard-unsubscribe link. The hard-unsubscribe sets `pref:nudge_pause_until = null + nudge_opted_out = true`, which is permanent.

---

## Section F — Edge Cases

### F.1 Student replies to a nudge with a substantive message

A student reads "Haven't seen you this week — anything blocking you?" and replies "yeah, I'm stuck on RAG fundamentals."

That reply enters the normal agent flow via the Supervisor. It does NOT go back to interrupt_agent. The Supervisor routes it as it would any tutoring question — likely to Learning Coach.

**Why:** interrupt_agent is a one-shot decider, not a conversational agent. Carrying state across turns would muddy its scope. The student's reply is just another normal request now.

The interrupt_agent's memory still gets updated: when the Supervisor handles the reply, it logs an `interaction:nudge_response` memory with `response_message = "yeah, I'm stuck..."` so the next interrupt_agent run knows the previous nudge succeeded.

### F.2 Multiple risk signals fire simultaneously

A student is plateauing on a concept AND has missed 3 days of planned sessions AND has a capstone deadline approaching. Interrupt_agent picks one to nudge about — the most actionable one, weighted by:

- Time-sensitivity (capstone deadline beats plateau)
- Recency (recent missed sessions beat older plateaus)
- Student preference (if they've responded better to encouragement than concern, prefer that tone)

The decision logic in the prompt picks one focus; the message addresses one thing well rather than three things shallowly.

### F.3 Student is paused but enters critical state

A student set their nudge_pause for 30 days. During that window, they enter `critical` risk state (e.g., 21 days inactive, refund window approaching).

**Default behavior: respect the pause.** The student explicitly asked for quiet. Overriding that breaks trust.

**Override via admin:** an admin can manually trigger an interrupt_agent run with `override_reason="critical_intervention_admin"`. This bypasses the pause but is logged with explicit attribution to the admin. Used sparingly.

### F.4 Multiple courses, conflicting signals

A student is doing great in Course A but struggling in Course B. Risk-scoring may aggregate to "healthy" while specific-course signals say "at_risk for B."

V1 simplification: interrupt_agent reads the aggregate `risk_state`, not per-course signals. If `risk_state="healthy"`, no nudge. The under-engagement on Course B will surface in `progress_report` (weekly summary) and via `study_planner`'s adherence tracking, both of which can prompt the student to refocus.

If post-launch data shows we're missing course-specific concerns, we extend interrupt_agent to read per-course risk signals. Tracked as a follow-up.

### F.5 Student in free tier (per Pass 3f)

Free-tier students aren't included in the daily interrupt_agent run. They're in onboarding/trial; nudges to them would feel like marketing. Their progression (placement quiz, demo chat) is handled by direct flows, not proactive nudges.

When a free-tier student converts to paid, they enter the daily run starting the next day.

### F.6 Webhook-triggered nudges (out of v1 scope)

Some events naturally suggest immediate proactive responses — student abandons a checkout flow, student fails a critical assessment, student's GitHub repo has a build failure on their submitted code. These are webhook-triggered and could warrant interrupt_agent invocation outside the daily cadence.

V1 does not implement event-driven nudges. They're harder to get right (deduplication, latency-sensitivity, channel-overlap with transactional flows). The daily cadence is the v1 contract.

If post-launch data shows event-driven nudges would meaningfully help, they're added in a later deliverable. The infrastructure supports it (webhook → @proactive runs are already in D6).

### F.7 Very new students (< 7 days)

Students with very short tenure shouldn't get risk-driven nudges. Risk-scoring for new students is unreliable; nudging them on day 3 with "you're at risk" would feel premature and creepy.

The interrupt_agent's daily run filters: only students with `tenure >= 7 days AND active_entitlement_age >= 7 days`. The first 7 days are handled by the existing onboarding flow (welcome series, placement quiz prompts), not by interrupt_agent.

---

## Section G — Safety And Cost

### G.1 Safety wrapping (Pass 3g)

Interrupt_agent is an `AgenticBaseAgent` and gets the standard safety wrapping. Specific concerns:

- **Output PII detection:** every nudge passes through `scan_output` before delivery. Hallucinated emails or phone numbers in the nudge body get caught.
- **Tone safety:** the prompt's hard constraints forbid guilt/shame/comparison language. Critic samples nudge outputs for tone deviations.
- **Charter violation:** nudge messages that drift into medical/legal/financial advice territory get caught by Pass 3g's drift detection.

### G.2 Cost — platform pays

Interrupt_agent runs are platform cost, not student cost. They don't decrement any student's daily ceiling. Capped via:

- Daily budget for proactive runs platform-wide (configurable; suggested 5,000 INR/day at 1k students = 5 INR per student per day budget for the proactive layer)
- Per-student cap as a sanity check (no student gets more than 1 interrupt_agent run per day; this is the same as the frequency cap)

At 1,000 students × 1.50 INR average per run × ~30% requiring full LLM (others short-circuit) = ~450 INR/day = ~13,500 INR/month. Modest.

### G.3 Failure modes

**Interrupt_agent itself fails (LLM error, tool error):**
- The student doesn't get a nudge that day
- Logged as a Critic-style escalation
- Doesn't retry within the same day (next day's run is the next chance)

**Channel delivery fails (DM write fails, email service down):**
- The nudge is queued for retry up to 3 attempts with exponential backoff
- After 3 failures, logged as an escalation; no further attempts that day
- Student state recorded as "nudge_attempted_failed" so the day's frequency cap is consumed (prevents accidentally double-nudging when delivery recovers)

**Risk-scoring is stale/down:**
- Interrupt_agent's `read_student_risk_signals` returns the last computed value
- If the last computed value is >48 hours old, treat as "no fresh signal" and skip
- Logged as a system-level concern for ops attention

---

## Section H — Implementation In D16 (And D9 Prerequisites)

### H.1 D9 prerequisite work (already implied; this pass formalizes)

**PG-1 fix:**
- `backend/app/main.py` lifespan adds `await _agentic_loader.load_agentic_agents()`
- Test: assert `webhook_subscribers` is non-empty in both FastAPI and Celery boot paths

**EscalationLimiter Redis-recovery:**
- On Redis reconnection, replay last 24h of `agent_escalations` rows to rebuild state
- Test: simulate Redis outage during agent run, verify limiter doesn't over-escalate when Redis returns

Both ship in D9 as small follow-ups.

### H.2 D16 scope

**New files:**
- `backend/app/agents/interrupt_agent.py` — the agent class
- `backend/app/agents/prompts/interrupt_agent.md` — full prompt
- `backend/app/schemas/agents/interrupt_agent.py` — `InterruptAgentOutput`, `NudgeMessage`
- `backend/app/agents/tools/agent_specific/interrupt_agent/*.py` — the 5 tools from §B.4
- `backend/app/mcp/email/` — Email MCP server (~300 LOC subapp)
- `backend/tests/test_agents/test_interrupt_agent.py` — unit tests
- `backend/tests/test_proactive/test_daily_interrupt_check.py` — proactive trigger tests

**New tables (in migration 0059):**
- `nudge_records` — per-nudge tracking (sent_at, channel, tone, severity_basis, etc.)
- `nudge_responses` — student response tracking (opened, clicked, organic_session_started, paused_after_nudge)
- `scheduled_outreach` — for `schedule_followup` tool (deferred future-time dispatch)

**Wired changes:**
- Celery beat config adds `daily_interrupt_check` cron
- Outreach automation extends to handle interrupt_agent-originated emails
- New admin route `/admin/proactive/recent-nudges` for operational visibility (deferred admin UI is small later addition)

**Tests:**
- All decision branches from the prompt's decision order
- Quiet-hours timezone correctness
- Frequency cap enforcement
- Pause-link respect
- Channel selection rules
- Failure-mode handling (channel delivery fails)
- Hold-out group exclusion

### H.3 Migration sequencing within D16

D16 ships in this order to keep things working at every step:

1. Email MCP server — built and tested in isolation
2. New schema (migration 0059) — runs in maintenance window
3. Tool implementations — readable tools first (read_student_risk_signals, check_recent_outreach), then writable (compose_dm, compose_email, schedule_followup)
4. Interrupt_agent class + prompt + schema
5. Unit tests passing
6. Daily Celery beat enabled in **dry-run mode** (logs decisions but doesn't actually send) for 3 days
7. Review dry-run logs for surprises
8. Switch to live mode with the 5% hold-out group
9. Monitor for first 2 weeks; tune thresholds

---

## Section I — Cost And Operational Impact

### I.1 Build cost

- ~1,200-1,500 LOC across interrupt_agent + Email MCP + tools
- 1 migration (0059), 3 new tables
- ~50 unit + integration tests
- D9 prerequisite work: ~50 LOC for PG-1 fix, ~30 LOC for limiter recovery

Material work but contained. Smaller than D11 (senior_engineer + sandbox) and D15 (curriculum graph + ingestion).

### I.2 Runtime cost

- Daily run: ~15-20 minutes for 1,000 students
- Per-run cost: ~1.50 INR average (most short-circuit cheaply)
- Email send cost: typical transactional email pricing (~1-3 INR per email)
- Total platform cost for proactive layer: ~13,500-25,000 INR/month at 1k students

Well within reasonable budget.

### I.3 Operational cost

- Weekly review of nudge outcomes (manual, ~30 minutes)
- Threshold tuning post-launch (variable; expect some adjustment in first 6 weeks)
- Hold-out experiment analysis (one-time at 8 weeks; informs whether to scale or rebuild)

---

## Section J — What This Pass Earns

When D16 ships:

**For students:**
- Their struggle gets noticed without them having to ask
- The platform feels like it cares (because it does)
- They're not spammed (frequency caps + quiet hours + pause links)
- Their pause requests are respected
- Nudges are kind and specific, not generic

**For the operator:**
- Closed-loop engagement: the system reacts to its own state
- Risk-scoring is no longer a write-only system
- Nudge effectiveness is measurable via the hold-out group
- Tuning happens via data, not guesswork
- The "agents and background jobs are parallel" finding from Pass 2 is closed

**For future contributors:**
- The proactive pattern is reusable: any agent can become proactive via @proactive
- Channel selection is centralized; new channels plug in
- Frequency cap and quiet-hours infrastructure is shared
- The hold-out experiment pattern can be reused for future product decisions

This is the layer that makes AICareerOS feel like an OS that *cares*, not just an OS that *responds*.

---

## Section K — What's Deferred

- **Event-driven nudges (webhooks)** — only daily cadence in v1
- **Per-course risk signals** — aggregate only in v1; revisit if data shows missing concerns
- **Student-segmented nudge experiments** — single A/B is the hold-out; richer segmentation post-launch
- **Multi-channel campaigns** — one channel per nudge in v1; "send DM, follow with email if unread" deferred
- **WhatsApp, SMS, push** — deferred channel additions
- **AI-generated subject lines** — using template-based subjects in v1; experiment with LLM-generated subjects later
- **Cross-student abuse detection** (e.g., one student trying to game adherence tracking) — basic guardrails only in v1
- **Interrupt_agent invokable by Supervisor for ad-hoc nudges** — backend ready (PG-1 fix enables it); admin UI deferred

---

## What's NOT covered by Pass 3h

- **Scale + observability + cost dashboards** → Pass 3i (which builds the dashboards consuming the data this pass captures)
- **Naming sweep + cleanup** → Pass 3j
- **Implementation roadmap synthesis** → Pass 3k/3l

Each builds on this layer without modifying it.
