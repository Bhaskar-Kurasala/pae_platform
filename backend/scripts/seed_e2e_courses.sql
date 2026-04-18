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

-- 4 lessons under the free Intro course + 1 lesson under the paid RAG course (for paywall test L8).
INSERT INTO lessons (id, course_id, title, slug, description, youtube_video_id, duration_seconds, "order", is_published, is_free_preview, created_at, updated_at)
SELECT gen_random_uuid(), c.id, t.title, t.slug, t.description, t.yt, t.dur, t.ord, true, t.free, now(), now()
FROM courses c, (VALUES
  ('What is Generative AI?',        'lesson-what-is-genai',           'Definitions, capabilities, and history.',           'dQw4w9WgXcQ', 420,  1, true),
  ('Prompt Engineering 101',        'lesson-prompt-engineering-101',  'Zero-shot, few-shot, system prompts.',              'dQw4w9WgXcQ', 600,  2, false),
  ('Embeddings & Vector Stores',    'lesson-embeddings-vector-stores','How to embed text and query with cosine sim.',      'dQw4w9WgXcQ', 720,  3, false),
  ('RAG Prototype End-to-End',      'lesson-rag-prototype-end-to-end','Putting it together: retrieve → compose → answer.', 'dQw4w9WgXcQ', 900,  4, false)
) AS t(title, slug, description, yt, dur, ord, free)
WHERE c.slug = 'intro-ai-engineering'
ON CONFLICT DO NOTHING;

INSERT INTO lessons (id, course_id, title, slug, duration_seconds, "order", is_published, is_free_preview, created_at, updated_at)
SELECT gen_random_uuid(), c.id, 'Intro to RAG', 'lesson-intro-to-rag-paid', 300, 1, true, false, now(), now()
FROM courses c WHERE c.slug = 'production-rag'
ON CONFLICT DO NOTHING;
