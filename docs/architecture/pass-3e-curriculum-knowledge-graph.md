---
title: Pass 3e — Curriculum Knowledge Graph + Graph-Aware Retrieval
status: Final — implementation contract for the curriculum knowledge layer
date: After Pass 3d sign-off, before D15 implementation
authored_by: Architect Claude (Opus 4.7)
purpose: Design the curriculum knowledge graph and graph-aware retrieval. Locks in the hybrid memory strategy (structured tables + vector store + knowledge graph). Defines the schema, the content_ingestion pipeline that populates it, the retrieval patterns agents use, the student overlay layer, and the cost/complexity tradeoffs. Honest scoping — not full GraphRAG; the right level of GraphRAG for AICareerOS's domain.
supersedes: nothing
superseded_by: nothing — this is the canonical knowledge graph design
informs: D15 (content_ingestion + graph build), D14 (practice_curator queries the graph), D13 (mock_interview uses concept graph for question selection), every personalization-aware agent
implemented_by: D15 (primary build), D14 (initial agent integration), D17 (cleanup)
depends_on: D2 (MemoryStore + pgvector), Pass 3a Addendum (content_ingestion in roster), Pass 3c (content_ingestion specification), Pass 3d Section E.1 (curriculum domain tools)
---

# Pass 3e — Curriculum Knowledge Graph + Graph-Aware Retrieval

> AICareerOS needs a knowledge layer that knows how concepts relate, what prerequisites exist, what content teaches what, and how each student stands relative to the curriculum. This pass designs that layer using Postgres + pgvector + recursive CTEs — a knowledge graph with graph-aware retrieval, not full GraphRAG.

> Read alongside: Pass 3d (the curriculum domain tools that wrap this layer), Pass 3c E10 (content_ingestion specification), AGENTIC_OS.md (the D2 vector infrastructure this builds on).

---

## Section A — The Hybrid Memory Strategy, Locked In

Three memory layers, each with a clear scope and store. No overlap, no ambiguity.

### A.1 Layer 1 — Structured tables (Postgres relational)

**What lives here:** anything with a known schema and exact-match access patterns.

- Student state: `user_skill_states`, `student_misconceptions`, `student_risk_signals`, `goal_contracts`, `growth_snapshots`, `learning_sessions`
- Course catalog: `courses`, `lessons`, `lesson_resources`, `exercises`, `exercise_submissions`
- Payments and entitlements: `course_entitlements`, `orders`, `payment_attempts`, `refunds`
- Audit and operations: `agent_actions`, `agent_call_chain`, `agent_tool_calls`, `agent_evaluations`, `agent_escalations`, `agent_proactive_runs`, `student_inbox`

Access pattern: ORM queries, JOINs, indexed lookups. Latency: sub-100ms typical.

### A.2 Layer 2 — Vector store (pgvector, scope=user/agent/global)

**What lives here:** anything where semantic similarity matters more than exact match.

- `agent_memory` rows (D2's table) — student preferences, observed patterns, prior interactions, learned insights
- Embedded artifacts — student code submissions (semantic search "find similar prior submissions"), capstone artifacts, written reflections
- Cross-student insights — generalized observations agents have learned (scope=agent or scope=global)

Access pattern: HNSW vector index, cosine similarity, key-pattern filtering. Latency: sub-100ms typical via D2's existing infrastructure.

### A.3 Layer 3 — Curriculum knowledge graph (this pass)

**What lives here:** the *structure* of what's being taught — concepts, their relationships, what content covers them.

- Concepts (the atoms of the curriculum)
- Relationships between concepts (prerequisite, builds_on, contrasts_with, applies_to)
- Mappings from courses/lessons/resources to concepts
- Misconceptions associated with concepts
- Resource canonicality (which YouTube video is the best explainer for concept X)

Access pattern: graph traversals via recursive CTEs, semantic search on concept names and descriptions, hybrid queries combining structure + similarity. Latency: 100ms–500ms typical for traversals up to 5 hops.

### A.4 Why this split is right

The split follows access pattern, not content type:

- "What's the student's mastery of concept X?" → exact match on `(student_id, concept_id)` → **structured**
- "Find similar prior code submissions" → semantic similarity on embedded code → **vector**
- "What concepts must a student master before tackling RAG?" → traverse prerequisite edges → **graph**

A query that needs *all three* (e.g., "what should this student practice next?") joins across layers — a common pattern that the `query_curriculum_graph` tool handles internally so agents don't have to.

### A.5 What deliberately does NOT go in the graph

To prevent scope creep:

- **Per-student data** — mastery levels, completion status, misconceptions specific to a student. These are in structured tables; the graph carries the *concept of* a misconception, not which students have it.
- **Embedded representations of long content** — full lesson transcripts, full repo files. These go in vector store with concept tags.
- **Conversation history** — that's vector store, scope=user.
- **Audit trails** — structured tables.

The graph is small, slow-moving, and shared. Per-student fast-changing data lives elsewhere.

---

## Section B — The Knowledge Graph Schema

Postgres tables with explicit foreign keys for relationships. No graph-native database; graph queries via recursive CTEs.

### B.1 Core entities

```sql
-- A concept is the atomic unit of curriculum knowledge.
CREATE TABLE concepts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT UNIQUE NOT NULL,           -- human-readable: "rag_fundamentals"
    name TEXT NOT NULL,                  -- display name: "RAG Fundamentals"
    description TEXT NOT NULL,           -- 2-4 sentence definition
    canonical_explanation TEXT,          -- 1-2 paragraph "best" explanation
    domain TEXT NOT NULL,                -- "ai_engineering" | "python" | "data_analytics" | ...
    difficulty_tier INT NOT NULL CHECK (difficulty_tier BETWEEN 1 AND 5),
    typical_hours_to_master FLOAT,       -- estimate; null if unknown
    embedding VECTOR(1536),              -- semantic search across concepts
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_concepts_slug ON concepts (slug);
CREATE INDEX idx_concepts_domain ON concepts (domain);
CREATE INDEX idx_concepts_embedding ON concepts USING hnsw (embedding vector_cosine_ops);
```

### B.2 Relationships between concepts

```sql
CREATE TABLE concept_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_concept_id UUID NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    to_concept_id UUID NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL CHECK (relationship_type IN (
        'prerequisite_of',      -- A must be known before B
        'builds_on',            -- B extends A (looser than prerequisite)
        'contrasts_with',       -- A and B are commonly confused; learning both clarifies each
        'applies_to',           -- A is a technique used in domain B
        'specialization_of',    -- A is a specific case of more general B
        'co_occurs_with'        -- A and B are typically taught together
    )),
    strength FLOAT NOT NULL DEFAULT 0.5 CHECK (strength BETWEEN 0.0 AND 1.0),
    rationale TEXT,             -- human-readable why
    source TEXT NOT NULL,       -- "manual" | "ingested" | "ai_inferred"
    confidence FLOAT NOT NULL DEFAULT 0.8 CHECK (confidence BETWEEN 0.0 AND 1.0),
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (from_concept_id, to_concept_id, relationship_type)
);

CREATE INDEX idx_rel_from ON concept_relationships (from_concept_id, relationship_type);
CREATE INDEX idx_rel_to ON concept_relationships (to_concept_id, relationship_type);
```

The six relationship types cover the curriculum-modeling vocabulary I need without exploding into ontology purity. If an actual relationship doesn't fit one of these, it's probably noise.

### B.3 Mapping content to concepts

The graph layer needs to know which course/lesson/resource teaches which concept.

```sql
CREATE TABLE concept_resource_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id UUID NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    resource_type TEXT NOT NULL CHECK (resource_type IN (
        'lesson',           -- references lessons.id
        'lesson_resource',  -- references lesson_resources.id
        'exercise',         -- references exercises.id
        'external_video',   -- YouTube etc., URL stored
        'external_repo',    -- GitHub repo, URL stored
        'external_text'     -- arbitrary text content stored
    )),
    resource_id UUID,                  -- FK lookup based on resource_type
    resource_url TEXT,                 -- for external_*
    resource_excerpt TEXT,             -- for external_text or to summarize content
    is_canonical BOOLEAN DEFAULT FALSE,-- the "best" resource for this concept
    coverage TEXT NOT NULL DEFAULT 'partial' CHECK (coverage IN ('intro', 'partial', 'full', 'advanced')),
    quality_score FLOAT CHECK (quality_score BETWEEN 0.0 AND 1.0),
    embedding VECTOR(1536),            -- for semantic search of "find resources covering X"
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_crl_concept ON concept_resource_links (concept_id);
CREATE INDEX idx_crl_canonical ON concept_resource_links (concept_id) WHERE is_canonical = TRUE;
CREATE INDEX idx_crl_embedding ON concept_resource_links USING hnsw (embedding vector_cosine_ops);
```

`is_canonical` matters: when an agent needs to point a student at "the best resource for concept X," it queries for canonical resources, not all resources. Multiple resources can cover the same concept; only one (or zero) is canonical at any time.

### B.4 Misconceptions

Misconceptions are concepts in their own right — they have prerequisites, they relate to canonical concepts, students hold them in identifiable ways.

```sql
CREATE TABLE misconceptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT UNIQUE NOT NULL,           -- "embeddings_are_one_hot"
    description TEXT NOT NULL,           -- "the false belief that embeddings encode semantic identity 1:1"
    associated_concept_id UUID NOT NULL REFERENCES concepts(id),
    typical_symptoms TEXT[],             -- observable indicators
    correction_explanation TEXT NOT NULL,-- how to address it
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ DEFAULT now(),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_misconceptions_concept ON misconceptions (associated_concept_id);
CREATE INDEX idx_misconceptions_embedding ON misconceptions USING hnsw (embedding vector_cosine_ops);
```

Note: `student_misconceptions` (Layer 1, structured) tracks which students hold which misconceptions. `misconceptions` (Layer 3, this table) carries the misconception itself as a curriculum entity.

### B.5 The student overlay (lives in Layer 1, not the graph)

To answer "what's the student's mastery of every concept in their course?" cheaply, the existing `user_skill_states` table maps `(user_id, concept_id) → mastery_score`. This is structured, not graph.

When a query needs to combine graph structure with student state ("which prerequisites of concept X has this student NOT mastered?"), the application code joins across layers:

```python
# Pseudocode for the join pattern
prereqs = await query_graph(
    "concepts where there is a prerequisite_of edge to X"
)
student_mastery = await query_structured(
    "user_skill_states where user_id = ? and concept_id IN ?",
    student_id, [p.id for p in prereqs]
)
return [p for p in prereqs if student_mastery.get(p.id, 0) < 0.7]
```

The `query_curriculum_graph` tool from Pass 3d handles this pattern internally so individual agents don't write join code.

### B.6 What this schema deliberately omits

- **Versioning of concepts** — when a concept's definition changes, we update in place. No version history. Acceptable because curriculum rarely changes; full audit log is via `agent_tool_calls` if needed.
- **Concept variants per course** — if "RAG Fundamentals" means slightly different things in two courses, that's modeled as one shared concept with course-specific resources, not two separate concepts. Forces curriculum coherence.
- **Hierarchical communities** — full GraphRAG would auto-detect concept clusters and summarize them at multiple levels. Out of scope per the architect's lock-in. If we ever expand into massive corpus ingestion, revisit.
- **Concept embedding refresh policy** — initial embedding on insert; re-embed only on description changes. Not worth a re-embedding pipeline.

---

## Section C — Population: How Content Gets Into The Graph

Three sources populate the graph: manual seeding, content_ingestion (the agent), and admin curation.

### C.1 Manual seeding (the bootstrap)

Before the first agent runs, the graph needs a baseline. AICareerOS courses already have curriculum mappings in their `course_content/`. The bootstrap migration:

1. Extract concept declarations from the existing course content
2. For each declared concept: insert a `concepts` row with manual description and difficulty
3. For each declared prerequisite chain: insert `concept_relationships` rows
4. Embed concept descriptions via Voyage-3 (existing infrastructure from D2)
5. Map existing `lessons` rows to concepts via `concept_resource_links`

This seeding produces the v1 graph: ~50-200 concepts, ~100-500 relationships. Hand-curated. High quality. Slow to update but trustworthy.

### C.2 Content ingestion (ongoing, automated)

When `content_ingestion` (Pass 3c E10) processes a new GitHub repo or YouTube video, it produces three outputs:

- **Concept hits** — which existing concepts does this content cover?
- **Concept candidates** — what new concepts are implied by this content that aren't yet in the graph?
- **Resource links** — `concept_resource_links` rows mapping the content to concepts it covers

For concept hits and resource links, content_ingestion writes directly. For concept candidates, it writes to a `concept_candidates` staging table for admin review:

```sql
CREATE TABLE concept_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposed_slug TEXT NOT NULL,
    proposed_name TEXT NOT NULL,
    proposed_description TEXT NOT NULL,
    proposed_relationships JSONB,      -- list of {to_slug, relationship_type, rationale}
    source_resource_id UUID NOT NULL,  -- which ingestion produced this
    source_evidence TEXT,              -- excerpt that led to the proposal
    confidence FLOAT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'merged')),
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    merged_into_concept_id UUID REFERENCES concepts(id),
    created_at TIMESTAMPTZ DEFAULT now()
);
```

**Why staging:** the graph is small and load-bearing. Letting agents auto-create concepts produces noise (synonym duplicates, granularity drift, hallucinated concepts). Admin review keeps the graph clean.

**Admin review surface:** an `/admin/curriculum/candidates` page (deferred to a small frontend addition in D15 or post-D15 — not blocking for graph functionality).

### C.3 Admin curation

Admins can:
- Add concepts directly via admin UI
- Add or edit relationships
- Re-canonicalize resources (mark a different YouTube video as canonical for a concept)
- Merge concept candidates into existing concepts (for synonyms)
- Reject candidates

These are direct writes — no agent involvement.

### C.4 The ingestion pipeline (D15 detail)

When content_ingestion processes a source:

```
1. Fetch raw content
   - GitHub: via GitHub MCP → file tree + key files + README
   - YouTube: via our YouTube MCP → metadata + transcript
   - Free text: provided directly

2. Extract candidate concepts (LLM-assisted)
   Input: raw content + existing concept list (for matching)
   Output: list of {concept_slug, confidence, evidence_excerpt}
   - If concept_slug matches existing: hit
   - If not: candidate

3. For each hit:
   - Insert concept_resource_links row
   - Update is_canonical if quality_score is higher than current canonical

4. For each candidate:
   - Insert concept_candidates row for admin review

5. For each hit, also infer relationships:
   - LLM-assisted: "given this content covers concept X and concept Y,
     what relationship between X and Y does this content evidence?"
   - Insert into concept_relationships with source='ingested', confidence=...
   - High-confidence inferred relationships can be auto-applied;
     medium-confidence go to a candidate review queue

6. Update embeddings for affected resources
```

LLM-assisted concept extraction is itself a tool (`extract_concepts` from Pass 3d Section F.7). The prompt for that tool emphasizes faithfulness — extract concepts the source actually covers, don't hallucinate adjacency.

### C.5 Cost of ingestion

Per source:
- 1 LLM call (Sonnet) for concept extraction: ~10-30 INR per medium-length source
- N LLM calls for relationship inference: depends on number of hits, typically 1-5 calls
- Embedding calls: ~0.5 INR per resource

Total per ingestion: ~15-50 INR for a typical YouTube video or medium repo. At a manageable volume (10-50 ingestions per week as the platform grows), monthly cost is bounded.

Long content (full repos with many files, hour-long videos) costs more. For very long content, the pipeline chunks before extracting. Chunk size capped at LLM-friendly windows.

---

## Section D — Querying The Graph

Five canonical query patterns. Each is implemented in the `query_curriculum_graph` tool (Pass 3d E.1.3).

### D.1 Pattern 1 — Exact concept lookup

```sql
SELECT * FROM concepts WHERE slug = $1;
```

Latency: <10ms. Used when an agent has a specific concept reference.

### D.2 Pattern 2 — Semantic concept search

```sql
SELECT id, slug, name, description, 1 - (embedding <=> $1) AS similarity
FROM concepts
WHERE 1 - (embedding <=> $1) > $2  -- threshold
ORDER BY embedding <=> $1
LIMIT $3;
```

Latency: <50ms via HNSW. Used when an agent has a free-form student question and needs to find relevant concepts.

### D.3 Pattern 3 — Prerequisite traversal (recursive CTE)

```sql
-- All concepts that are prerequisites of a target concept (transitively)
WITH RECURSIVE prereq_chain AS (
    SELECT to_concept_id AS target_id, from_concept_id AS prereq_id, 1 AS depth
    FROM concept_relationships
    WHERE to_concept_id = $1 AND relationship_type = 'prerequisite_of'

    UNION

    SELECT pc.target_id, cr.from_concept_id AS prereq_id, pc.depth + 1
    FROM prereq_chain pc
    JOIN concept_relationships cr ON cr.to_concept_id = pc.prereq_id
    WHERE cr.relationship_type = 'prerequisite_of' AND pc.depth < $2  -- max depth
)
SELECT DISTINCT prereq_id, MIN(depth) AS depth
FROM prereq_chain
GROUP BY prereq_id
ORDER BY depth;
```

Latency: depends on graph density. For a curriculum with ~200 concepts and average 3 prerequisites each, full traversal up to depth 5 returns in <100ms. Indexed appropriately.

This is the workhorse pattern. Used by:
- `find_concepts_at_mastery_edge` (which prereqs has the student not mastered)
- adaptive_path / Learning Coach (what to teach next)
- mock_interview (calibrating difficulty)

### D.4 Pattern 4 — Hybrid graph + structured query (the cross-layer join)

"What concepts in the student's current course are at the edge of their mastery?"

```sql
-- Combines: graph (course → concepts), structured (mastery), graph (prereqs)
SELECT
    c.id, c.slug, c.name, c.difficulty_tier,
    uss.mastery_score, uss.last_assessed_at
FROM concepts c
JOIN concept_resource_links crl ON crl.concept_id = c.id
JOIN lessons l ON l.id = crl.resource_id AND crl.resource_type = 'lesson'
LEFT JOIN user_skill_states uss
    ON uss.concept_id = c.id AND uss.user_id = $1
WHERE l.course_id = $2
  AND COALESCE(uss.mastery_score, 0) BETWEEN 0.3 AND 0.7  -- "edge" definition
  AND NOT EXISTS (
    -- Exclude concepts whose own prereqs the student hasn't mastered
    SELECT 1 FROM concept_relationships cr
    JOIN user_skill_states uss2
        ON uss2.concept_id = cr.from_concept_id AND uss2.user_id = $1
    WHERE cr.to_concept_id = c.id
      AND cr.relationship_type = 'prerequisite_of'
      AND COALESCE(uss2.mastery_score, 0) < 0.7
  )
ORDER BY uss.mastery_score DESC, c.difficulty_tier ASC
LIMIT $3;
```

This is the kind of query that would be ugly in a graph DB and is straightforward in SQL. Validates the Postgres choice.

Latency: <500ms for typical graphs and student datasets. Indexed.

### D.5 Pattern 5 — Natural-language query (LLM-augmented retrieval)

The Pass 3d `query_curriculum_graph` tool accepts a natural-language query and routes it to one of the four patterns above (or a composition).

The implementation in D15:

```python
async def query_curriculum_graph(input: QueryGraphInput) -> QueryGraphOutput:
    # 1. Classify the query type using a small LLM call (Haiku)
    classification = await classify_query(input.query)
    # → one of: "exact", "semantic", "prereq_traversal", "hybrid", "narrative"

    # 2. Route to appropriate retrieval pattern
    if classification.kind == "exact":
        results = await pattern_exact_lookup(classification.concept_ref)
    elif classification.kind == "semantic":
        results = await pattern_semantic_search(input.query)
    elif classification.kind == "prereq_traversal":
        results = await pattern_prereq_traversal(classification.target_concept)
    elif classification.kind == "hybrid":
        results = await pattern_hybrid(classification.params)
    else:  # narrative
        # Multi-hop narrative: "explain how X relates to Y"
        results = await pattern_narrative(input.query)

    # 3. If the caller wants narrative, synthesize with Sonnet
    if input.synthesize_narrative:
        narrative = await synthesize_narrative(results, input.query)
    else:
        narrative = None

    return QueryGraphOutput(
        answer=narrative,
        relevant_concepts=results.concepts,
        relationship_paths=results.paths,
    )
```

The narrative synthesis path (Pattern 5b) is the closest this system gets to "GraphRAG" — an LLM is given graph-derived structured context and asked to produce a narrative answer. But the LLM doesn't search the graph itself; it gets pre-computed graph traversal results and synthesizes over them. This is cheaper, faster, and more controllable than letting the LLM construct graph queries directly.

### D.6 Caching policy

The graph is mostly read-only at runtime. Caching strategy:

- **Exact lookups** — cached in Redis with 1-hour TTL keyed by concept slug. Invalidated on update.
- **Semantic searches** — not cached (query strings are too varied).
- **Prerequisite traversals** — cached in Redis with 1-hour TTL keyed by target concept. Invalidated when any relationship to/from that concept changes.
- **Hybrid queries with student state** — not cached (student state changes frequently).
- **Narrative queries** — not cached at the synthesized-answer level; the underlying graph traversals follow the rules above.

Cache invalidation hooks fire from any write to `concepts` or `concept_relationships`. Conservative — invalidates more than strictly needed but graph writes are rare.

---

## Section E — Graph-Aware Retrieval In Practice

How specific agents use the graph.

### E.1 Learning Coach (the heaviest user)

The Learning Coach uses the graph for:

- **What to teach next** — query: "concepts in student's course where mastery is 0.5-0.7 AND all prereqs are >=0.7" (Pattern 4)
- **Resource recommendation** — query: "canonical resource for concept X" → returns the YouTube video or lesson the student should engage
- **Misconception diagnosis** — query: when student's response indicates confusion, semantic search misconceptions table for matches → present `correction_explanation`
- **Concept explanation** — query: "concept X with description" + "related concepts within 2 hops" → assemble teaching context

Per-call: 2-4 graph queries typical. Latency budget: 500ms total for graph operations within a single agent invocation.

### E.2 career_coach

Uses the graph for:

- **Skill gap analysis** — given target role, what concepts does it require? Compare against student mastery.
- **Path estimation** — given current state and target role, traverse prerequisite chains to estimate hours-to-competence.

Lower frequency than Learning Coach but heavier per call (broader traversals).

### E.3 study_planner

Uses the graph for:

- **Session topic selection** — "given student has 90 minutes, what's a coherent set of concepts to cover?" Queries for concepts at the edge of mastery + their immediate prereqs/dependents to keep sessions thematically tight.

### E.4 practice_curator

Uses the graph for:

- **Exercise targeting** — "generate an exercise on concept X that requires applying concept Y and concept Z" — concept Y and Z are sourced via traversal.
- **Anti-repetition** — "exercises this student has done covering this concept" → don't generate duplicates.

### E.5 mock_interview

Uses the graph for:

- **Question selection** — given target role and student weaknesses, find concepts at appropriate difficulty.
- **Difficulty calibration** — using `difficulty_tier` and concept relationships, pick questions one tier above current mastery.

### E.6 content_ingestion

Special role — both reader AND writer:

- Reads existing concepts to disambiguate (does this content cover existing X or propose new candidate?)
- Writes hits, candidates, and inferred relationships.

---

## Section F — The Student Overlay

Per-student data layered on top of the shared graph. Lives in Layer 1 (structured tables), not in the graph itself.

### F.1 What's tracked

Already-existing tables that overlay the graph:

- `user_skill_states (user_id, concept_id, mastery_score, last_assessed_at, ...)` — mastery per concept
- `student_misconceptions (user_id, misconception_id, observed_at, addressed_at?)` — per-student misconceptions
- `srs_cards (user_id, concept_id, ...)` — spaced repetition scheduling per concept
- `learning_sessions (user_id, ...) ` with `concept_ids[]` — session participation per concept

### F.2 New table: `student_concept_engagement`

To track engagement metrics not covered above (time spent, attempts, breakthroughs):

```sql
CREATE TABLE student_concept_engagement (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    concept_id UUID NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    minutes_engaged FLOAT NOT NULL DEFAULT 0,
    attempt_count INT NOT NULL DEFAULT 0,
    last_engagement_at TIMESTAMPTZ,
    breakthrough_at TIMESTAMPTZ,           -- when mastery crossed 0.7
    plateau_at TIMESTAMPTZ,                -- if stuck for 7+ days at <0.5
    metadata JSONB DEFAULT '{}'::jsonb,
    UNIQUE (user_id, concept_id)
);

CREATE INDEX idx_sce_user ON student_concept_engagement (user_id);
CREATE INDEX idx_sce_plateau ON student_concept_engagement (plateau_at) WHERE plateau_at IS NOT NULL;
```

This table is updated by:
- Learning Coach (after lessons/explanations)
- senior_engineer (after code reviews tagged with concepts)
- adaptive_quiz / mcq_factory (after MCQ attempts)
- Background `engagement_recompute` job (recomputes plateau_at and breakthrough_at on schedule)

### F.3 The "concept network for this student" view

When the Supervisor builds `StudentSnapshot`, the part it needs from the graph is a *student-overlaid* slice:

```sql
-- Pseudocode for the snapshot query
SELECT
    c.slug, c.name,
    uss.mastery_score,
    sce.minutes_engaged,
    sce.last_engagement_at,
    sce.plateau_at,
    -- frontier marker: is this at the edge?
    CASE
        WHEN COALESCE(uss.mastery_score, 0) BETWEEN 0.3 AND 0.7 THEN 'edge'
        WHEN COALESCE(uss.mastery_score, 0) >= 0.7 THEN 'mastered'
        WHEN sce.plateau_at IS NOT NULL THEN 'stuck'
        ELSE 'ahead'
    END AS state
FROM concepts c
LEFT JOIN user_skill_states uss ON uss.concept_id = c.id AND uss.user_id = $1
LEFT JOIN student_concept_engagement sce ON sce.concept_id = c.id AND sce.user_id = $1
WHERE c.id IN (
    -- Concepts in the student's enrolled courses
    SELECT DISTINCT crl.concept_id
    FROM concept_resource_links crl
    JOIN lessons l ON l.id = crl.resource_id AND crl.resource_type = 'lesson'
    JOIN course_entitlements ce ON ce.course_id = l.course_id AND ce.user_id = $1
    WHERE ce.revoked_at IS NULL
)
ORDER BY state, mastery_score DESC;
```

Cached in `student_snapshot_service` (per Pass 3b §3.1) with 5-minute TTL. Recomputed lazily.

---

## Section G — Cost And Complexity Analysis

Honest accounting of what this layer costs to build and run.

### G.1 Build cost (one-time, mostly D15)

- Schema migrations: 1 migration (`0056_curriculum_graph.py`), small
- ORM models: ~6 new models (concepts, concept_relationships, concept_resource_links, misconceptions, concept_candidates, student_concept_engagement)
- The `query_curriculum_graph` tool implementation: 5 patterns + classifier + narrative synthesis ≈ 500 LOC
- The bootstrap seeding script: extract from existing course content, populate ~200 concepts + relationships ≈ 300 LOC + manual curation effort
- content_ingestion graph integration: enhance Pass 3c E10's specs ≈ 400 LOC
- Admin candidate review UI: deferred (functional graph doesn't need it on day 1)
- Tests: ~50 unit tests across the patterns and ingestion logic

**Effort:** D15 is one of the larger implementation deliverables — likely 2-3x the size of D10 (billing_support). Manageable but real.

### G.2 Storage cost (runtime, ongoing)

For a curriculum of ~200 concepts:
- `concepts` table: <1 MB (with embeddings: ~2.5 MB)
- `concept_relationships` table: <1 MB
- `concept_resource_links` table: scales with content; ~100 KB per 100 ingested resources
- `misconceptions` table: <1 MB
- `concept_candidates` table: bounded (small staging area, periodically pruned)
- `student_concept_engagement`: 200 concepts × 1000 students = 200K rows, ~50 MB

Total: well under 1 GB even at full scale. Negligible Postgres footprint.

### G.3 Query cost (runtime, ongoing)

- Pattern 1 (exact): <1ms compute, sub-ms with cache hit
- Pattern 2 (semantic): ~50ms compute via HNSW
- Pattern 3 (traversal, depth ≤5): ~50-200ms depending on graph density
- Pattern 4 (hybrid): ~200-500ms
- Pattern 5 (narrative): ~500ms graph + 1-3s LLM synthesis

LLM cost for narrative queries: ~0.5-2 INR per query depending on context size. At 1k students × 5 graph queries/day average × 30% needing narrative = ~1500 narrative queries/day = ~50k INR/month worst case. Well within the per-student cost ceilings from Pass 3b.

### G.4 Maintenance cost (ongoing)

The graph is mostly static. Maintenance work is:

- **Concept candidate review** — admin reviews accumulate, ~5-15 minutes per week of human attention as the platform grows
- **Canonicality re-decisions** — when better resources appear, admin re-canonicalizes (rare)
- **Misconception bank growth** — new misconceptions are added as agents observe them in students; admin curates from `student_misconceptions` patterns

This is the kind of curation an education platform does anyway. Not new work, just where it gets concentrated.

### G.5 What this layer DOES NOT cost

- **No new infrastructure operational burden** — runs on existing Postgres
- **No new monitoring concerns** — Postgres metrics already monitored
- **No new backup procedures** — included in existing Postgres backups
- **No new security surface** — same auth, same network policies

This is the payoff for picking Postgres over a separate graph database.

---

## Section H — Migration And Rollout

The graph is built once and then maintained. Rollout sequence:

### H.1 Phase 0 — Schema (early in D15)

Migration `0056_curriculum_graph.py` adds the 6 new tables. Idempotent. No data yet.

### H.2 Phase 1 — Bootstrap (D15 mid)

Run the bootstrap script: extract concepts from existing `course_content/`, manually curate, populate the graph.

After Phase 1, the graph has ~200 concepts and is queryable.

### H.3 Phase 2 — Tool wiring (D15 mid)

`query_curriculum_graph` tool implementation. Patterns 1-4 functional. Pattern 5 (narrative) functional.

After Phase 2, agents that have `read_curriculum_concept`, `find_concepts_at_mastery_edge`, and `query_curriculum_graph` declared in their capabilities can use them.

### H.4 Phase 3 — Ingestion integration (D15 late)

content_ingestion enhanced with graph writes (hits, candidates, inferred relationships). YouTube MCP and GitHub MCP wired.

After Phase 3, the graph grows automatically as content is ingested.

### H.5 Phase 4 — Student overlay (D15 late, blends with D14)

`student_concept_engagement` table created. Background `engagement_recompute` job scheduled. The Supervisor's `StudentSnapshot` includes graph-overlay data.

### H.6 Phase 5 — Agent integration (ongoing through D14, D16)

Agents start using their declared graph tools. practice_curator (D14) is a heavy user; mock_interview (D13) uses it lightly; Learning Coach (already on AgenticBaseAgent from D8) gets enhanced to use graph queries.

---

## Section I — What This Pass Earns

When the curriculum graph ships:

**For students:**
- Learning Coach actually knows what they should learn next, grounded in concept structure
- Recommendations are concrete ("watch this video on X then try this exercise") not generic
- Their practice exercises target the right edge of their knowledge
- Career advice can map "where you are" to "where you want to be" through real prerequisite chains
- The platform feels like it understands the *shape* of what's being taught

**For the operator:**
- Curriculum coverage is enumerable — admin can see "what concepts exist, which have canonical resources, which have gaps"
- Content gaps surface — "concept X has no canonical resource" becomes a visible TODO
- Misconception patterns emerge — when many students hit the same misconception, it surfaces in admin
- Adding new courses extends the graph without requiring a re-architecture

**For future contributors:**
- The graph schema is small and Postgres-native (familiar tooling)
- Adding a new concept is a row insert
- New retrieval patterns are added to the `query_curriculum_graph` tool, not new infrastructure
- The split between graph (concept structure) and student overlay (per-student state) is clear
- Migration to a graph database, if ever needed, is a contained backend change

This is the layer that turns "a registry of agents" into "an OS that knows what's being learned and by whom."

---

## Section J — What's Deferred

- **Admin candidate review UI** — backend writes to `concept_candidates`; the admin frontend to review them is a small frontend addition not blocking graph functionality. Add when admin has time.
- **Cross-concept analytics dashboards** — "which concepts have the most students stuck" — Pass 3i (scale + observability) covers operational dashboards.
- **Full GraphRAG techniques** — community detection, hierarchical summarization. Not designed here. Revisit only if AICareerOS expands into massive unstructured corpus ingestion.
- **Versioning of concepts** — out of scope per §B.6.
- **Concept variants per course** — out of scope per §B.6.
- **Curriculum sharing across courses (e.g., licensing curriculum to others)** — way out of scope; comes back if that ever becomes a product direction.

---

## What's NOT covered by Pass 3e

- **Entitlement schema per tier** → Pass 3f
- **Output-side safety, prompt injection, content moderation** → Pass 3g
- **Interrupt agent specifics** → Pass 3h
- **Scale and observability** → Pass 3i
- **Naming sweep + cleanup** → Pass 3j
- **Implementation roadmap synthesis** → Pass 3k/3l

Each builds on this layer without modifying it.
