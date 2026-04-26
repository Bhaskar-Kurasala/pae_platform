# Page Strategy: Job Readiness

**Status:** Living document
**Page:** Job Readiness
**Last updated:** April 25, 2026

---

## 1. Page Purpose (One Line)

The page where a student gets an honest answer to *"Am I actually ready to apply — and if not, exactly what to fix?"* — and then takes the next action without leaving the platform.

---

## 2. The Student's Mental State on Arrival

Students arrive at Job Readiness carrying two opposing fears simultaneously:

- *"Am I behind?"* — the anxiety of not having done enough
- *"Am I ready and just stalling?"* — the anxiety of avoidance dressed up as preparation

This is the **highest-stakes page emotionally** in the entire product. Get it wrong and students bounce — either feeling crushed by a wall of gaps, or falsely reassured into stalling longer. Get it right and they feel **seen**: the page reflects reality back to them with warmth and routes them to the next action with clarity.

The page must defuse anxiety, not amplify it. A wall of features amplifies. A coach defuses.

---

## 3. The Six Sub-Goals Every Student Carries In

Every visit, the student is implicitly asking for one or more of these:

1. **Verdict** — A clear yes/no/almost on whether they can apply *today*. Not vibes — evidence.
2. **Gap diagnosis** — Which specific skills, projects, or signals are weak vs. strong, with sources.
3. **Proof of readiness** — Something they can show a recruiter (resume, portfolio, mock score) — not just internal progress.
4. **Rehearsal** — Safe place to practice the scary parts (interviews, coding rounds, behavioral Qs) before it counts.
5. **Market reality check** — What employers *currently* ask for, not generic advice. Salary, demand, JD-fit.
6. **Next action** — One unambiguous thing to do next, sized for today.

Every feature on the page must trace to one or more of these. Features that don't map get cut.

---

## 4. The Page's Core Insight

> **You don't have a "Job Readiness page with a resume agent and a mock tool." You have a Job Readiness Coach — and the agents are its tools.**

This reframe is the difference between a feature graveyard and a coherent product.

The page is anchored by the **Diagnostic Agent**, which acts as the conversational front door. From the diagnostic's verdict, students are routed to the right tool: resume tailoring, mock interview, JD decoder, or a specific lesson/lab. The student doesn't choose which tool to talk to — the diagnostic does the routing.

This collapses 5 agents into one *experience*. One front door, many rooms.

---

## 5. The Stickiness Lever

Job Readiness is the **only page in the product where a well-built experience earns daily returns** — because the gap shrinks visibly. It is to CareerForge what:

- The recovery score is to Whoop
- The streak is to Duolingo
- The fitness score is to Strava

The unifying principle: **tools that answer "where do I stand today?" produce daily returns.** Tools that produce visible artifacts (resumes, certificates) feel high-value but are used rarely. The diagnostic is the daily-stand-check. Everything else is episodic.

This insight should govern build order and feature prioritization.

---

## 6. Build Priority Order

Ranked by **actual impact on student outcomes and product retention**, not perceived feature value:

### Tier 1 — Anchor and core agents

1. **"Am I Ready?" Diagnostic Agent** — the conversational anchor. Highest frequency, highest emotional impact, lowest build cost. Spec: `diagnostic-agent.md`.
2. **JD Decoder Agent** — paired with diagnostic, ships together. Tactical but high "aha" moments. Spec: `jd-decoder-agent.md`.
3. **Mock Interview Agent** — deepest impact when used; routed to by diagnostic. Spec: `mock-interview-agent.md`.
4. **Tailored Resume + Cover Letter Agent** — most defensible (verified data moat); used episodically during active job search. Spec: `tailored-resume-agent.md`.

### Tier 2 — Build after Tier 1 ships and retention proves out

- **Question Predictor Agent** — natural extension of mock interview infra (~70% reuse). Reduces interview surprise.
- **Salary Negotiation Coach** — high emotional value, low frequency (1-2 uses per student lifetime). Build when first cohort hits offer stage.
- **Interview Post-Mortem Agent** — closes the feedback loop after real interviews. Reuses mock evaluation infra.

### Tier 3 — Defer or kill

- **LinkedIn Profile Optimizer** — useful but lives on a Profile page, not Job Readiness.
- **Recruiter Outreach Agent** — quality bar too high for v1; bad outreach hurts brand and student.
- **Referral Finder** — needs network graph data we don't have yet.
- **Application Tracker** — feature, not an agent. Build as CRUD if needed.
- **Portfolio Storyteller** — belongs on Capstone or Profile page.
- **Offer Comparison** — niche, low frequency. One-off content piece is enough.

---

## 7. The Routing Logic

The diagnostic's verdict produces one next action. The action map:

| If the verdict says...                      | Route to...                                  |
| ------------------------------------------- | -------------------------------------------- |
| "Skills gap in X"                           | The relevant lesson or lab in the curriculum |
| "Projects don't tell your story"            | Resume agent                                 |
| "Interview rehearsal is the gap"            | Mock interview (with mode pre-selected)      |
| "You don't know what employers want"        | JD decoder, with a curated JD                |
| "You're ready, what's stopping you is fear" | Apply flow + mock interview as warm-up       |
| "Not enough data yet to tell"               | Today page / lesson recommendation           |

The routing is built once; every new agent just registers itself in the `NextActionCatalog` with its trigger conditions.

---

## 8. Anti-Patterns to Avoid

These are the failure modes the page must explicitly resist:

- **Feature menu masquerading as a page.** A row of cards that says "Try our 5 AI tools!" is a dashboard, not a coach. The diagnostic must be the unmistakable anchor.
- **Sycophantic feedback.** "You're doing great!" trains delusion and produces failed interviews and churn. Calibrated honesty is non-negotiable across every agent on this page.
- **Decision menus.** "Here are 3 options for next steps" is decision fatigue. One next action, surfaced confidently. Alternatives are hidden behind a "what else?" affordance, not pushed.
- **Streak pressure on emotional features.** Daily streaks work for lessons. They do not work for mock interviews or diagnostics — they create burnout and shallow practice. Cadence is implicit and gentle.
- **Leaderboards on private prep.** Mock interview scores and diagnostic verdicts are private. Comparing creates anxiety, not improvement.
- **Hallucinated evidence.** Every claim across every agent on this page must trace to verified platform data. One fabricated claim destroys trust permanently.
- **High-stakes paywalls mid-flow.** A returning student blocked by "upgrade to continue" on their first action is a churn event. First-action-free rules apply across all premium agents.

---

## 9. Shared Infrastructure Across the Page

The agents share more than they differ. Build the foundation once:

- **`StudentSnapshot`** — denormalized verified platform data, used by every agent
- **`WeaknessLedger`** — rolling per-student record of identified gaps; written to by diagnostic and mock interview, read by all agents
- **Evidence validator pattern** — every agent that makes claims about the student must trace claims to source; reject and regenerate if unsourced
- **Anti-sycophancy eval set** — shared across all agents on the page
- **Cost cap and circuit breaker pattern** — every LLM call wrapped uniformly
- **`NextActionCatalog`** — registry of all routable actions; every agent registers as both a "router" (sends students to actions) and "destination" (can be routed to)

---

## 10. North-Star Metric for the Page

> **% of Job Readiness visits that produce a completed next action within 24 hours.**

This is the single metric that tells you the page works.

A student who lands, gets a verdict, clicks the recommended action, and completes it — that's the loop. Every feature on the page either contributes to this or doesn't earn its place.

Sub-metrics:

- % of visits that open the diagnostic
- % of diagnostics that produce a verdict (vs. abandoned)
- % of verdicts where next action is clicked
- % of clicked actions completed within 24h

Watch all four. If the funnel breaks at a specific stage, fix that stage.

---

## 11. The Voice of the Page

Across every surface — diagnostic verdict copy, JD decoder framing, mock interview interruptions, resume agent prompts — the voice is consistent:

- **Warm but direct.** Like a senior friend in the industry who actually wants you to get the job.
- **Evidence-grounded.** Every claim cites a source. No vibes.
- **One thing at a time.** Single next action. Decision fatigue is the enemy.
- **Honest about uncertainty.** When the agent doesn't know, it says so. Confident-but-wrong is worse than humble.
- **Calm.** This page is anxious by default; the voice should not amplify the anxiety. Pace, white space, and tone all matter.

`copy.ts` should be a single shared file across all Job Readiness agents to enforce voice consistency.

---

## 12. Open Strategic Questions

- Should the page have a default "today's nudge" surface above the diagnostic (e.g., a streak-style daily prompt), or does that compete with the diagnostic for attention?
- How does Job Readiness relate to the Today page? Does Today recommend the student visit Job Readiness, or vice versa?
- Should premium features (unlimited resumes, mock interview at scale) be cross-page or page-local?
- Long-term: can the diagnostic be a top-of-funnel tool — used pre-signup as a "where do you stand?" hook?
- How do we handle students who *are* ready and the diagnostic says so? Do they "graduate" from the page, or does the page evolve to support active job search and post-offer life?

---

## 13. Related Specs

- `diagnostic-agent.md` — the page's anchor
- `jd-decoder-agent.md` — paired with diagnostic
- `mock-interview-agent.md` — deepest-impact rehearsal tool
- `tailored-resume-agent.md` — verified-data resume generator

All four specs assume this strategy doc as their parent context.

---
