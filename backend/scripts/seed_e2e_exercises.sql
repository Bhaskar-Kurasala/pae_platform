-- E2E test fixture: one coding exercise attached to the free Intro course's first lesson.
-- Used by the Exercises suite (E1-E10) in docs/E2E-TEST-TRACKER.md.
-- Idempotent via lesson_id+title lookup; safe to re-run.
--
-- Requires: seed_e2e_courses.sql has already been applied.
--
-- Apply locally:
--   docker compose exec -T db psql -U postgres -d platform < backend/scripts/seed_e2e_exercises.sql

INSERT INTO exercises (
  id, lesson_id, title, description, exercise_type, difficulty,
  starter_code, solution_code, test_cases, rubric, points, "order",
  created_at, updated_at
)
SELECT
  gen_random_uuid(),
  l.id,
  'Write a Prompt Classifier',
  'Build a function `classify_prompt(text: str) -> str` that returns one of: "question", "command", "statement". Pass the 3 hidden test cases.',
  'coding',
  'beginner',
  E'def classify_prompt(text: str) -> str:\n    """Return one of: question, command, statement."""\n    # TODO: your code here\n    raise NotImplementedError\n',
  E'def classify_prompt(text: str) -> str:\n    t = text.strip().lower()\n    if t.endswith("?"):\n        return "question"\n    if t.split()[0] in {"write", "build", "make", "generate", "create"}:\n        return "command"\n    return "statement"\n',
  '[{"input": "What is RAG?", "expected": "question"}, {"input": "Build an agent.", "expected": "command"}, {"input": "Embeddings are vectors.", "expected": "statement"}]'::jsonb,
  '{"criteria": [{"name": "Correctness", "weight": 60, "description": "All 3 hidden tests pass"}, {"name": "Clarity", "weight": 20, "description": "Readable, idiomatic Python"}, {"name": "Edge cases", "weight": 20, "description": "Handles empty strings and punctuation"}]}'::jsonb,
  100,
  1,
  now(),
  now()
FROM lessons l
JOIN courses c ON c.id = l.course_id
WHERE c.slug = 'intro-ai-engineering' AND l.slug = 'lesson-what-is-genai'
  AND NOT EXISTS (
    SELECT 1 FROM exercises e WHERE e.lesson_id = l.id AND e.title = 'Write a Prompt Classifier'
  );
