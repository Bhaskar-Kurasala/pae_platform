-- Catalog tracks: the 5 career tracks rendered by CatalogScreen (catalog-screen.tsx).
-- Slugs MUST match CARDS[].cta.courseSlug — frontend looks up price + availability by slug.
-- Idempotent via slug ON CONFLICT; safe to re-run.
--
-- Apply locally:
--   docker compose exec -T db psql -U postgres -d platform < backend/scripts/seed_catalog_tracks.sql

INSERT INTO courses (id, title, slug, description, difficulty, price_cents, is_published, estimated_hours, created_at, updated_at)
VALUES
  (gen_random_uuid(), 'Python Developer',  'python-developer',  'Clean functions, async I/O, error handling. The base every role ahead depends on.',                                                  'beginner',     0,     true, 45,  now(), now()),
  (gen_random_uuid(), 'Data Analyst',      'data-analyst',      'SQL joins that feel natural, pandas that scales, and dashboards a stakeholder reads without a walkthrough.',                       'beginner',     8900,  true, 60,  now(), now()),
  (gen_random_uuid(), 'Data Scientist',    'data-scientist',    'Statistics you trust, experiments you run, and models that actually ship — not just notebooks.',                                   'intermediate', 14900, true, 90,  now(), now()),
  (gen_random_uuid(), 'ML Engineer',       'ml-engineer',       'Production ML — training pipelines that don''t break on Monday, features that are versioned, models that are monitored.',         'advanced',     19900, true, 120, now(), now()),
  (gen_random_uuid(), 'GenAI Engineer',    'genai-engineer',    'Agentic systems, production RAG, evals that catch real regressions, and LLMOps. Build what ships in 2026.',                       'advanced',     24900, true, 140, now(), now())
ON CONFLICT (slug) DO NOTHING;
