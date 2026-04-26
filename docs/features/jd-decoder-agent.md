# Feature Spec: JD Decoder Agent

**Status:** Proposed
**Page:** Job Readiness (paired with Diagnostic Agent)
**Tier:** Free
**Logged:** April 25, 2026

---

## 1. One-line Pitch

A brutal, honest read on any Job Description — separates real must-haves from wishlist and template filler, flags culture risk, and scores the student's match using verified platform data.

---

## 2. Strategic Rationale

**JD literacy is a teachable skill.** Most students treat a JD as a checklist to fear — every "5 years required" reads as a hard wall. The decoder reframes JDs as documents to *read critically*, which changes how students apply forever. After 3-4 decodings, the skill transfers and the student no longer needs the tool. This is intentional — the decoder is a learning aid disguised as a tool.

**Standalone value, but moat is in pairing.** Generic JD parsers exist (Teal, Jobscan). The decoder's edge is **per-student match scoring using verified platform data** — something competitors structurally cannot offer. Standalone, it's a useful utility. Bundled with the diagnostic, it's the workflow that produces the page's most actionable moment: "here's a JD you should apply to *today*."

**Friction-reducer for the resume agent.** Once a JD is decoded, tailoring a resume to it is one click away. The decoder is the natural upstream of the resume tool.

---

## 3. User Flow

### Standalone use

1. Student opens Job Readiness → sees "Decode a JD" card.
2. Pastes JD text (URL fetch deferred to Phase 2).
3. Decoder runs → renders structured analysis: must-haves, wishlist, culture signals, match score.
4. Match score has CTAs: "Tailor a resume to this JD" (resume agent) and "Mock interview for this role" (mock interview agent).

### Bundled use (via diagnostic)

1. Student is in a diagnostic conversation, mentions a target JD or has one saved.
2. Diagnostic auto-invokes the decoder.
3. Decoded analysis renders inline within the diagnostic conversation.
4. Diagnostic uses the match score as evidence in the final verdict.

---

## 4. Output Structure

Every decode produces:

### Real must-haves (3-7 items)

The skills, experiences, or credentials that genuinely gate consideration. Stripped of buzzword inflation. Example: a JD listing 12 "required" skills usually has 3-4 actual must-haves; the rest are wishlist.

### Wishlist (3-8 items)

Skills that strengthen but don't gate. Example: "Kubernetes experience preferred" is wishlist for most data roles even when listed prominently.

### Template filler (flagged, not listed verbosely)

Phrases that mean nothing: "fast-paced startup," "rockstar," "wear many hats," "competitive salary." Decoder names them and explains what they usually mean. Educational moment.

### Seniority signal

Does the title match the asks? Examples:

- *"Title says Senior, asks are Mid-level — likely flexible on years if skills match."*
- *"Title says Junior, asks are Senior-level — red flag, expect underleveling."*

### Culture signals (honest read)

- Burnout language ("hard-charging," "ownership mentality," "comfortable with ambiguity") — flagged with what it usually means
- Compensation transparency or absence
- Growth/learning specificity vs. vagueness
- Diversity and inclusion language quality (specific commitments vs. boilerplate)

This section is the decoder's most differentiated output. Generic parsers don't do this.

### Match score (the moat)

Per-student score using verified platform data. Format:

- Single visual element (gauge or wheel, matching the existing `--forest`/`--gold` design)
- 3-5 evidence chips supporting the score, mixing strengths and gaps
- Each chip cites a source from the student's snapshot
- One next action: tailor a resume, prep for X, close gap Y

---

## 5. Architecture & Components

### 5.1 Sub-agents

| Sub-agent             | Role                                                                 | Model tier                 | Latency |
| --------------------- | -------------------------------------------------------------------- | -------------------------- | ------- |
| **JDParser**    | Extracts structured data from raw JD text                            | Cheap model + regex hybrid | 2-3s    |
| **JDAnalyst**   | Classifies must-haves vs. wishlist vs. filler; flags culture signals | Reasoning model            | 4-6s    |
| **MatchScorer** | Compares student snapshot against decoded JD                         | Reasoning model            | 3-5s    |

These can run in parallel after parsing completes.

### 5.2 Backend services

- `JDParser` — extraction service: requirements, skills, seniority indicators, comp info, location, company info
- `CultureSignalDetector` — pattern library of culture flags (burnout language, vague growth, etc.) + LLM classification for nuance
- `MatchEngine` — uses `StudentSnapshot` (shared with diagnostic) + decoded JD; produces score + evidence
- `JDCache` — hash-based cache so the same JD isn't re-decoded across students or sessions

### 5.3 Data models

- `JobDescription` — raw text, hash, parsed object, decoded analysis, source (paste/URL/upload), timestamp
- `JDAnalysis` — must-haves, wishlist, filler flags, seniority read, culture signals
- `MatchScore` — student × JD, score (0-100), evidence array with source IDs
- `JDDecodeLog` — usage tracking, cost

### 5.4 LLM strategy

- **JDParser:** Cheap model. Output is structured JSON. Regex handles obvious patterns (years, salary ranges) before LLM runs.
- **JDAnalyst:** Reasoning model. System prompt includes the "real must-haves vs. wishlist" framework with examples. Culture signal detection runs as a sub-step.
- **MatchScorer:** Reasoning model. Hard-grounded: every evidence chip must cite a source from `StudentSnapshot`. Same validator as the diagnostic and resume agent.

---

## 6. Critical Design Decisions & Tradeoffs

### Decision 1: Honest culture-signal flagging

- **Tradeoff:** Companies might object if their JD gets flagged. Reputation risk.
- **Why:** This is the decoder's most differentiated output. Generic parsers don't do this. Students need it. We frame as "patterns commonly seen in JDs," not accusations against specific employers. Educational tone.

### Decision 2: Match score uses verified data only

- **Tradeoff:** Students with thin platform data get less useful match scores.
- **Why:** Same hallucination guardrail as resume and diagnostic. A confident-but-wrong match score is worse than no score. For thin-data students, the agent says so honestly: "Not enough activity yet to score this match."

### Decision 3: URL fetching deferred to Phase 2

- **Tradeoff:** Students must paste JD text manually.
- **Why:** Job sites are a swamp — auth walls, paywalls, dynamic JS rendering, anti-scraping. 90% of value at 10% of complexity comes from paste-text. Defer URL fetching until the rest of the product is proven.

### Decision 4: JD cache is hash-based, shared across students

- **Tradeoff:** Privacy consideration — JDs are technically public, but students might want their searches private.
- **Why:** Massive cost savings. Same JD posted on multiple sites or shared between students gets decoded once. Match scoring is per-student; the JD analysis itself is universal. Hash the JD text, not the student.

### Decision 5: Decoder is free, no quota

- **Tradeoff:** Higher LLM cost on free tier.
- **Why:** JD literacy is a teachable skill. After 3-4 decodings, students stop needing it. Self-limiting usage means no quota needed. Quotas would feel petty for a learning aid.

### Decision 6: Output is analysis, not regurgitation

- **Tradeoff:** Some students want a clean reformatted JD.
- **Why:** Reformatting is what generic tools do. The decoder's value is the *interpretation*. Quoting the JD minimally and only to anchor a point is enforced via system prompt.

---

## 7. Risks & Mitigations

| Risk                                                         | Mitigation                                                                                                                        |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| Decoder mis-classifies must-haves vs. wishlist               | Eval set of 100+ real JDs with ground-truth classifications; CI test against accuracy threshold                                   |
| Culture signal flags are wrong or over-aggressive            | Conservative system prompt; "patterns commonly seen" framing; manual sample review weekly                                         |
| Match score feels arbitrary                                  | Every score includes 3-5 evidence chips with sources. Score without evidence is forbidden.                                        |
| Companies object to culture flags being applied to their JDs | Educational framing; never name specific companies in pattern descriptions; flags are at the*language* level, not company-level |
| Cache pollution from junk JDs                                | Hash + length checks before caching; minimum-quality threshold                                                                    |
| Cost on long JDs (5000+ words)                               | Truncation at parser level; flag if JD is unusually long                                                                          |

---

## 8. Success Metrics

**Activation:** % of Job Readiness visitors who decode at least one JD.
**Repeat usage:** Decodes per student in first 30 days. Watch for a healthy distribution (3-5 is ideal — too low means low value, too high means students aren't learning the skill).
**Downstream conversion:** % of decodes that lead to a tailored resume generation within 24h. North-star pairing metric.
**Quality:** Manual eval — weekly sample of 30 decodes scored for must-have accuracy, culture signal accuracy, match score reasonableness.
**Cost efficiency:** Cache hit rate; cost per unique JD (should drop steeply with cache).

---

## 9. Build Phases

**Phase 1 (MVP, 2-3 weeks):** Paste-text input, full structured output (must-haves, wishlist, filler, seniority, culture signals), match score with verified-data grounding, cache, integration with diagnostic agent.

**Phase 2 (4-6 weeks post-launch):** URL fetching for top job sites (LinkedIn, Naukri, Indeed), JD save & re-decode (track changes over time on the same role), batch comparison (decode 3 JDs side-by-side).

**Phase 3:** Recruiter-facing JD review tool (write better JDs); JD trend reports across roles ("here's what 'Data Analyst' means in 2026").

---

## 10. Open Questions

- Should the decoder's output be sharable? (Students might want to send a friend a "here's why this JD is sus" link.)
- How do we handle non-English JDs? (Defer to Phase 3 likely.)
- Match score: 0-100 or descriptive ("Strong match," "Stretch role," "Aspirational")? Numeric is precise but invites obsession; descriptive is warmer.
- Should low-match scores discourage applying, or reframe? ("Match is 40%, but you've been working on the gap — 8 weeks of focused prep would change this.")
- Long-term: can decoded JDs feed back into the platform's curriculum? (Trending skills detected across decodes → new lessons recommended.)

---
