-- High-impact exercises seed for the Exercises tab.
-- Six production AI engineering challenges mapped across the free Intro course
-- + the paid Production RAG course. Idempotent via lesson_id+title.
--
-- Apply:
--   docker compose exec -T db psql -U postgres -d platform < backend/scripts/seed_high_impact_exercises.sql

-- 1) Build a Retry-Backoff Wrapper (Intro · What is GenAI)
INSERT INTO exercises (id, lesson_id, title, description, exercise_type, difficulty, starter_code, solution_code, test_cases, rubric, points, "order", created_at, updated_at)
SELECT
  gen_random_uuid(), l.id,
  'Retry with Exponential Backoff',
  'Wrap an unreliable Claude API call so it retries up to 3 times with exponential backoff (1s, 2s, 4s). Surface a calm error if all attempts fail. This pattern is mandatory for any production LLM client.',
  'coding', 'beginner',
  E'import asyncio\nfrom anthropic import APIError\n\nasync def call_with_retry(fn, max_attempts: int = 3):\n    """Call ``fn()`` with exponential backoff. Re-raise after ``max_attempts``."""\n    # TODO: implement\n    raise NotImplementedError\n',
  E'import asyncio\nfrom anthropic import APIError\n\nasync def call_with_retry(fn, max_attempts: int = 3):\n    last = None\n    for attempt in range(max_attempts):\n        try:\n            return await fn()\n        except APIError as exc:\n            last = exc\n            await asyncio.sleep(2 ** attempt)\n    raise last\n',
  '[{"name": "succeeds first try"}, {"name": "succeeds on retry 2"}, {"name": "raises after exhaustion"}]'::jsonb,
  '{"criteria": [{"name": "Retry semantics", "weight": 50, "description": "Backs off 1s/2s/4s and stops at max_attempts"}, {"name": "Error surfacing", "weight": 30, "description": "Final APIError propagates with original context"}, {"name": "Async correctness", "weight": 20, "description": "No blocking sleep, no swallowed exceptions"}]}'::jsonb,
  150, 1, now(), now()
FROM lessons l JOIN courses c ON c.id=l.course_id
WHERE c.slug='intro-ai-engineering' AND l.slug='lesson-what-is-genai'
  AND NOT EXISTS (SELECT 1 FROM exercises e WHERE e.lesson_id=l.id AND e.title='Retry with Exponential Backoff');

-- 2) Prompt Injection Defense (Intro · Prompt Engineering)
INSERT INTO exercises (id, lesson_id, title, description, exercise_type, difficulty, starter_code, solution_code, test_cases, rubric, points, "order", created_at, updated_at)
SELECT
  gen_random_uuid(), l.id,
  'Prompt Injection Defense',
  'Build ``sanitize_user_input(text: str) -> str`` that detects and neutralizes the 5 most common prompt-injection patterns ("ignore previous instructions", role hijack, system prompt leaks, delimiter breakouts, encoded payloads). Returns a safe wrapped prompt or raises ``InjectionDetected``.',
  'coding', 'intermediate',
  E'class InjectionDetected(ValueError):\n    pass\n\ndef sanitize_user_input(text: str) -> str:\n    """Wrap user text in a safe envelope or raise InjectionDetected."""\n    # TODO: detect 5 attack families, then wrap clean input.\n    raise NotImplementedError\n',
  E'import re\n\nclass InjectionDetected(ValueError):\n    pass\n\n_PATTERNS = [\n    r"ignore\\s+(all\\s+)?previous\\s+instructions",\n    r"you\\s+are\\s+now\\s+",\n    r"system\\s*:",\n    r"</?\\s*(system|assistant)\\s*>",\n    r"base64|\\\\x[0-9a-f]{2}",\n]\n\ndef sanitize_user_input(text: str) -> str:\n    low = text.lower()\n    for p in _PATTERNS:\n        if re.search(p, low):\n            raise InjectionDetected(p)\n    return f"<user_input>{text.strip()}</user_input>"\n',
  '[{"name": "blocks ignore-previous"}, {"name": "blocks role hijack"}, {"name": "blocks system tag"}, {"name": "blocks delimiter breakout"}, {"name": "passes benign input"}]'::jsonb,
  '{"criteria": [{"name": "Coverage", "weight": 50, "description": "Catches all 5 attack families"}, {"name": "Low false positives", "weight": 30, "description": "Benign prompts pass through unmodified"}, {"name": "Safe wrapping", "weight": 20, "description": "Clean input is delimited and trimmed"}]}'::jsonb,
  200, 2, now(), now()
FROM lessons l JOIN courses c ON c.id=l.course_id
WHERE c.slug='intro-ai-engineering' AND l.slug='lesson-prompt-engineering-101'
  AND NOT EXISTS (SELECT 1 FROM exercises e WHERE e.lesson_id=l.id AND e.title='Prompt Injection Defense');

-- 3) Token-Aware Chunker (Intro · Embeddings)
INSERT INTO exercises (id, lesson_id, title, description, exercise_type, difficulty, starter_code, solution_code, test_cases, rubric, points, "order", created_at, updated_at)
SELECT
  gen_random_uuid(), l.id,
  'Token-Aware Document Chunker',
  'Implement ``chunk_document(text, max_tokens=512, overlap=64)`` that splits long documents on sentence boundaries while staying under the token budget. Adjacent chunks share an overlap window so retrieval keeps semantic continuity.',
  'coding', 'intermediate',
  E'def chunk_document(text: str, max_tokens: int = 512, overlap: int = 64) -> list[str]:\n    """Split on sentence boundaries; respect max_tokens; keep overlap between chunks."""\n    # TODO: tokenize, group sentences, slide a window with overlap.\n    raise NotImplementedError\n',
  E'import re\n\ndef _tok(s: str) -> int:\n    return max(1, len(s) // 4)\n\ndef chunk_document(text: str, max_tokens: int = 512, overlap: int = 64) -> list[str]:\n    sents = [s.strip() for s in re.split(r"(?<=[.!?])\\s+", text) if s.strip()]\n    chunks, buf, used = [], [], 0\n    for s in sents:\n        t = _tok(s)\n        if used + t > max_tokens and buf:\n            chunks.append(" ".join(buf))\n            tail, taken = [], 0\n            for prev in reversed(buf):\n                pt = _tok(prev)\n                if taken + pt > overlap: break\n                tail.insert(0, prev); taken += pt\n            buf, used = tail, taken\n        buf.append(s); used += t\n    if buf: chunks.append(" ".join(buf))\n    return chunks\n',
  '[{"name": "respects max_tokens"}, {"name": "sentence boundaries preserved"}, {"name": "overlap maintained"}, {"name": "handles short docs"}]'::jsonb,
  '{"criteria": [{"name": "Chunk size discipline", "weight": 40, "description": "Never exceeds max_tokens"}, {"name": "Sentence integrity", "weight": 30, "description": "Cuts on . ! ? boundaries only"}, {"name": "Overlap correctness", "weight": 30, "description": "Shared tail roughly equals overlap budget"}]}'::jsonb,
  200, 3, now(), now()
FROM lessons l JOIN courses c ON c.id=l.course_id
WHERE c.slug='intro-ai-engineering' AND l.slug='lesson-embeddings-vector-stores'
  AND NOT EXISTS (SELECT 1 FROM exercises e WHERE e.lesson_id=l.id AND e.title='Token-Aware Document Chunker');

-- 4) RAG Citation Validator (Intro · RAG prototype)
INSERT INTO exercises (id, lesson_id, title, description, exercise_type, difficulty, starter_code, solution_code, test_cases, rubric, points, "order", created_at, updated_at)
SELECT
  gen_random_uuid(), l.id,
  'RAG Citation Validator',
  'Build ``validate_citations(answer, retrieved_chunks)`` that confirms every claim in the LLM answer is grounded in the retrieved context. Returns a list of unsupported claims so a hallucination guardrail can reject the response.',
  'coding', 'advanced',
  E'def validate_citations(answer: str, chunks: list[str]) -> list[str]:\n    """Return claims from ``answer`` that have no support in any chunk."""\n    # TODO: split into claims, check token overlap against each chunk.\n    raise NotImplementedError\n',
  E'import re\n\ndef _tokens(s: str) -> set[str]:\n    return {t for t in re.findall(r"[a-z0-9]{4,}", s.lower())}\n\ndef validate_citations(answer: str, chunks: list[str]) -> list[str]:\n    claims = [c.strip() for c in re.split(r"(?<=[.!?])\\s+", answer) if c.strip()]\n    chunk_toks = [_tokens(c) for c in chunks]\n    unsupported = []\n    for claim in claims:\n        ctoks = _tokens(claim)\n        if not ctoks: continue\n        best = max((len(ctoks & ct) / len(ctoks) for ct in chunk_toks), default=0)\n        if best < 0.4:\n            unsupported.append(claim)\n    return unsupported\n',
  '[{"name": "fully grounded passes"}, {"name": "fabricated claim flagged"}, {"name": "partial support flagged"}, {"name": "empty chunks rejects all"}]'::jsonb,
  '{"criteria": [{"name": "Hallucination recall", "weight": 50, "description": "Catches fabricated claims"}, {"name": "Precision", "weight": 30, "description": "Doesn''t flag well-grounded claims"}, {"name": "Robustness", "weight": 20, "description": "Handles empty chunks and degenerate input"}]}'::jsonb,
  300, 4, now(), now()
FROM lessons l JOIN courses c ON c.id=l.course_id
WHERE c.slug='intro-ai-engineering' AND l.slug='lesson-rag-prototype-end-to-end'
  AND NOT EXISTS (SELECT 1 FROM exercises e WHERE e.lesson_id=l.id AND e.title='RAG Citation Validator');

-- 5) Streaming Token Counter (Intro · RAG prototype, second exercise)
INSERT INTO exercises (id, lesson_id, title, description, exercise_type, difficulty, starter_code, solution_code, test_cases, rubric, points, "order", created_at, updated_at)
SELECT
  gen_random_uuid(), l.id,
  'Streaming Cost Meter',
  'Wrap an async streaming Claude response so you can report cumulative input + output tokens and live cost (USD) without buffering the whole stream. This is what every "tokens used" dashboard does in production.',
  'coding', 'intermediate',
  E'from typing import AsyncIterator\n\nasync def metered_stream(stream: AsyncIterator[dict], price_in: float, price_out: float):\n    """Yield (delta_text, cumulative_cost_usd) pairs."""\n    # TODO: track input_tokens + output_tokens deltas, compute running cost.\n    raise NotImplementedError\n',
  E'from typing import AsyncIterator\n\nasync def metered_stream(stream: AsyncIterator[dict], price_in: float, price_out: float):\n    in_tok = out_tok = 0\n    async for ev in stream:\n        u = ev.get("usage", {})\n        in_tok += int(u.get("input_tokens", 0) or 0)\n        out_tok += int(u.get("output_tokens", 0) or 0)\n        delta = ev.get("delta", {}).get("text", "")\n        cost = (in_tok * price_in + out_tok * price_out) / 1_000_000\n        if delta:\n            yield delta, round(cost, 6)\n',
  '[{"name": "yields cumulative cost"}, {"name": "no double-counting"}, {"name": "handles empty deltas"}]'::jsonb,
  '{"criteria": [{"name": "Token accounting", "weight": 50, "description": "Input + output tracked separately and additively"}, {"name": "Streaming hygiene", "weight": 30, "description": "Stays async, no buffering of full stream"}, {"name": "Cost formula", "weight": 20, "description": "USD = (in*p_in + out*p_out) / 1M"}]}'::jsonb,
  200, 5, now(), now()
FROM lessons l JOIN courses c ON c.id=l.course_id
WHERE c.slug='intro-ai-engineering' AND l.slug='lesson-rag-prototype-end-to-end'
  AND NOT EXISTS (SELECT 1 FROM exercises e WHERE e.lesson_id=l.id AND e.title='Streaming Cost Meter');

-- 6) Production RAG Reranker (Production RAG · paid)
INSERT INTO exercises (id, lesson_id, title, description, exercise_type, difficulty, starter_code, solution_code, test_cases, rubric, points, "order", created_at, updated_at)
SELECT
  gen_random_uuid(), l.id,
  'Hybrid Search + Reranker',
  'Combine BM25 keyword scores with vector cosine similarity using reciprocal rank fusion, then rerank top-K with a cross-encoder. Implement ``hybrid_rerank(query, candidates, k=5)`` returning the final ranked list. This is the bread-and-butter of every shipped RAG system.',
  'coding', 'advanced',
  E'def hybrid_rerank(query: str, candidates: list[dict], k: int = 5) -> list[dict]:\n    """Each candidate has keys: text, bm25_score, vector_score.\n    Fuse with RRF (k=60), then rerank top-K with a simple lexical cross-encoder.\n    Return top-k items in final order."""\n    # TODO: implement RRF + rerank.\n    raise NotImplementedError\n',
  E'def hybrid_rerank(query: str, candidates: list[dict], k: int = 5) -> list[dict]:\n    by_bm25 = sorted(candidates, key=lambda c: -c["bm25_score"])\n    by_vec = sorted(candidates, key=lambda c: -c["vector_score"])\n    rrf = {}\n    K = 60\n    for rank, c in enumerate(by_bm25):\n        rrf[id(c)] = rrf.get(id(c), 0) + 1 / (K + rank + 1)\n    for rank, c in enumerate(by_vec):\n        rrf[id(c)] = rrf.get(id(c), 0) + 1 / (K + rank + 1)\n    fused = sorted(candidates, key=lambda c: -rrf[id(c)])[: max(k * 2, k)]\n    qtok = set(query.lower().split())\n    def cross(c):\n        ctok = set(c["text"].lower().split())\n        return len(qtok & ctok) / max(1, len(qtok))\n    return sorted(fused, key=cross, reverse=True)[:k]\n',
  '[{"name": "RRF fusion correct"}, {"name": "rerank top-K"}, {"name": "respects k limit"}, {"name": "ties broken stably"}]'::jsonb,
  '{"criteria": [{"name": "Fusion correctness", "weight": 40, "description": "RRF formula 1/(K+rank) applied to both signals"}, {"name": "Rerank quality", "weight": 40, "description": "Cross-encoder pass meaningfully reorders"}, {"name": "Edge cases", "weight": 20, "description": "Handles empty candidates and small k"}]}'::jsonb,
  400, 6, now(), now()
FROM lessons l JOIN courses c ON c.id=l.course_id
WHERE c.slug='production-rag' AND l.slug='lesson-intro-to-rag-paid'
  AND NOT EXISTS (SELECT 1 FROM exercises e WHERE e.lesson_id=l.id AND e.title='Hybrid Search + Reranker');
