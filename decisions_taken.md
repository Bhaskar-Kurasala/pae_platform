# Decisions Taken — PAE Platform

Running ADR log for all architecture decisions, conflict resolutions, and scope choices.
Updated automatically whenever ambiguity is resolved. Format: Context → Decision → Rationale → Simple path chosen.

---

## ADR-001 — 2026-04-17: Full Platform Scope

**Context:** Platform audit revealed 5 stub agents, missing payments/email/OAuth integrations, generic UI, no E2E tests, and no observability.

**Decision:** Execute all 4 pillars in parallel (Design + Platform Completion + Quality + Docs).

**Rationale:** User confirmed enterprise-scale ambition. Parallel workstreams minimize total time while maintaining quality. Each workstream owns disjoint file paths to prevent conflicts.

**Simple path chosen:** 6 parallel workstreams with explicit file ownership. Conflicts resolved by ADR entry + simplest implementation.

---

## ADR-002 — 2026-04-17: Design Aesthetic

**Context:** Landing page is functional but visually generic. Dashboard has no premium feel.

**Decision:** Mixed aesthetic — Linear/Vercel for portal/dashboard, Stripe/Notion for marketing pages, Claude.ai for agent chat.

**Rationale:** Target audience is technical engineers (Linear/Vercel aesthetic resonates). Marketing needs warmth to drive conversions (Stripe feel). Chat is the product's core UX (Claude.ai feel is natural).

**Simple path chosen:** Keep shadcn/ui as foundation. Add framer-motion for micro-animations. Use existing recharts (already installed) over Tremor. No new component library added.

---

## ADR-003 — 2026-04-17: Live Agent Demo on Landing Page

**Context:** Visitor conversion depends on showing product value immediately.

**Decision:** Add a public `/api/v1/demo/chat` endpoint, rate-limited to 5 msgs per IP per hour, calling the SocraticTutor agent.

**Rationale:** Single biggest conversion driver — visitors experience the product before signing up.

**Simple path chosen:** Reuse existing `AgentOrchestratorService`. Rate limit via slowapi (already installed). No auth required for demo endpoint.

---

## ADR-004 — 2026-04-17: Deployment Target

**Context:** Need to choose between local, staging, and full production deploy.

**Decision:** Local + staging. Docker Compose runs everything locally; staging deploy scripts are ready but cloud choice deferred.

**Rationale:** Getting a cloud deployment working before the platform is feature-complete wastes time. Staging scripts (GitHub Actions workflow) are production-equivalent.

**Simple path chosen:** docker-compose.yml for local, GitHub Actions CI/CD workflow for staging. No cloud provider locked in.

---

## ADR-005 — 2026-04-17: Pinecone RAG vs. Local Fallback

**Context:** Pinecone is configured but not in pyproject.toml. Requires API key that may not be present.

**Decision:** Implement RAG service with graceful degradation — real Pinecone when API key present, in-memory stub when absent. Add `pinecone[grpc]` to pyproject.toml.

**Rationale:** Pinecone free tier exists and is production-ready. Graceful fallback ensures platform works without the key during local dev.

**Simple path chosen:** `RagService` class checks `settings.pinecone_api_key` at init. If empty, returns mock results with a log warning. Zero breaking changes.

---

## ADR-006 — 2026-04-17: main.py Route Registration

**Context:** Multiple workstreams (agents, stripe, oauth, demo) need to register new routes in `backend/app/main.py`. Parallel agents would conflict editing the same file.

**Decision:** Parallel agents create their route files and return the `include_router()` calls they need. Coordinator agent updates `main.py` after all workstreams complete.

**Rationale:** Prevents merge conflicts in the most critical file. Each agent can verify their routes are wired up in the integration phase.

**Simple path chosen:** Each agent includes a comment block `# ADD TO main.py: router.include_router(X)` at the top of new route files.

---

## ADR-007 — 2026-04-17: SSE Streaming Architecture

**Context:** Agent responses need to stream token-by-token for good UX. Current `/chat` endpoint returns a full response.

**Decision:** Add `/api/v1/agents/stream` endpoint using FastAPI's `StreamingResponse` with `text/event-stream`. Frontend uses `EventSource` with a custom `useStream` hook.

**Rationale:** SSE is simpler than WebSockets for one-directional streaming. Native browser support. No additional infrastructure.

**Simple path chosen:** Add `stream()` method to `BaseAgent` that wraps the Claude `stream()` API. New route reuses `AgentOrchestratorService`. Old `/chat` endpoint unchanged.

---

## ADR-008 — 2026-04-17: New Agents Scope

**Context:** User asked to add new agents or source from agent ecosystems.

**Decision:** Add 3 new agents: `career_coach`, `resume_reviewer`, `billing_support`. Keep them within the existing `BaseAgent` + registry pattern.

**Rationale:** 
- `career_coach`: Combines job_match + portfolio_builder insights for holistic career planning — high student value.
- `resume_reviewer`: Analyzes resume text for AI engineering roles — directly solves a student need.
- `billing_support`: Handles subscription queries — reduces support overhead.

**Simple path chosen:** Each agent follows existing pattern (BaseAgent → @register → prompt MD file → test). No new frameworks.

---
