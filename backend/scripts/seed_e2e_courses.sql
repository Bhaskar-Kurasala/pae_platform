-- E2E test fixture: 4 courses covering free/paid × beginner/intermediate/advanced.
-- Used by the Courses suite (C1-C8) in docs/E2E-TEST-TRACKER.md.
-- Idempotent via slug ON CONFLICT; safe to re-run.
--
-- Apply locally:
--   docker compose exec -T db psql -U postgres -d platform < backend/scripts/seed_e2e_courses.sql

INSERT INTO courses (id, title, slug, description, difficulty, price_cents, is_published, estimated_hours, created_at, updated_at)
VALUES
  (gen_random_uuid(), 'Intro to AI Engineering',             'intro-ai-engineering',          'Ship your first RAG prototype end-to-end.',              'beginner',     0,    true, 8,  now(), now()),
  (gen_random_uuid(), 'Production RAG Systems',              'production-rag',                'Build retrieval pipelines that survive prod traffic.',   'intermediate', 4900, true, 14, now(), now()),
  (gen_random_uuid(), 'Agent Orchestration with LangGraph',  'agent-orchestration-langgraph', 'Stateful multi-agent workflows.',                        'advanced',     9900, true, 20, now(), now()),
  (gen_random_uuid(), 'Evaluating LLM Outputs',              'llm-evaluation',                'Design rubrics and eval harnesses.',                     'intermediate', 0,    true, 10, now(), now())
ON CONFLICT (slug) DO NOTHING;
