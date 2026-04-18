-- E2E test fixture: one weekly growth_snapshot + one unread weekly_letter notification.
-- Used by the Progress suite (P3-P6) in docs/E2E-TEST-TRACKER.md.
-- Idempotent — deletes rows for the test user+week_ending before reinserting.
--
-- Apply locally:
--   docker compose exec -T db psql -U postgres -d platform < backend/scripts/seed_e2e_receipts.sql

-- Target: E2E test user 7cd5417a-d30e-4959-b60d-0dee162ffb0f.
-- In CI, adapt the user_id to whatever the test harness creates.

DELETE FROM growth_snapshots
WHERE user_id = '7cd5417a-d30e-4959-b60d-0dee162ffb0f'
  AND week_ending = '2026-04-12';

DELETE FROM notifications
WHERE user_id = '7cd5417a-d30e-4959-b60d-0dee162ffb0f'
  AND notification_type = 'weekly_letter'
  AND body LIKE '%2026-04-12%';

INSERT INTO growth_snapshots (
  id, user_id, week_ending, lessons_completed, skills_touched,
  streak_days, top_concept, payload, created_at, updated_at
) VALUES (
  gen_random_uuid(),
  '7cd5417a-d30e-4959-b60d-0dee162ffb0f',
  '2026-04-12',
  3,
  2,
  4,
  'Embeddings',
  '{"quiz_attempts": 2, "quiz_avg_score": 0.75, "reflections": 0}'::json,
  now(), now()
);

INSERT INTO notifications (
  id, user_id, title, body, notification_type, is_read, action_url, metadata, created_at, updated_at
) VALUES (
  gen_random_uuid(),
  '7cd5417a-d30e-4959-b60d-0dee162ffb0f',
  'Your weekly letter — 2026-04-12',
  E'# Week of 2026-04-12\n\nYou completed **3 lessons** this week and touched **2 skills**.\n\n## What worked\n- You kept a 4-day active streak\n- Your quiz average was 75%\n\n## Focus for next week\n- Finish the RAG prototype lesson\n- Try the classifier exercise\n\n```python\ndef classify_prompt(text):\n    return "statement"\n```',
  'weekly_letter',
  false,
  NULL,
  '{"week_ending": "2026-04-12"}'::jsonb,
  now(), now()
);
