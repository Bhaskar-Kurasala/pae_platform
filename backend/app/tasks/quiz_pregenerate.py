"""Pre-generate 3 quiz versions for an assistant message in the background.

When a message is persisted, the chat route fires `pregenerate_quiz_for_message`
via Celery. By the time the student clicks "Quiz Me", all 3 versions are cached
in Redis (TTL 24h) and served instantly.

Version rotation: the cache also stores a per-message counter so the endpoint
can cycle v1→v2→v3→v1→… on successive Quiz Me clicks.
"""

from __future__ import annotations

import asyncio
import json

import structlog

from app.core.celery_app import celery_app
from app.core.redis import get_redis, namespaced_key

log = structlog.get_logger()

_QUIZ_TTL_SECONDS = 86_400  # 24 hours
_NUM_VERSIONS = 3


def _quiz_key(message_id: str) -> str:
    return namespaced_key("quiz", message_id)


async def _generate_versions(message_id: str, content: str) -> list[list[dict]]:
    """Run the MCQFactoryAgent 3 times with different temperature seeds."""
    from app.agents.base_agent import AgentState
    from app.agents.mcq_factory import MCQFactoryAgent
    from app.api.v1.routes.chat import _parse_quiz_questions

    versions: list[list[dict]] = []
    agent = MCQFactoryAgent()

    for attempt in range(_NUM_VERSIONS):
        state = AgentState(
            student_id="pregenerate",
            conversation_history=[],
            task=f"Generate 5 MCQ questions (version {attempt + 1})",
            context={
                "focus_topic": content,
                "source_message_id": message_id,
                "content": content,
                "version": attempt + 1,
            },
            response=None,
            tools_used=[],
            evaluation_score=None,
            agent_name=None,
            error=None,
            metadata={},
        )
        try:
            result = await agent.execute(state)
            questions, concepts = _parse_quiz_questions(result.response or "")
            versions.append([
                {
                    "question": q.question,
                    "options": q.options,
                    "correct_index": q.correct_index,
                    "explanation": q.explanation,
                    "bloom_level": q.bloom_level,
                    "concept": q.concept,
                    "question_type": q.question_type,
                    "distractor_rationales": q.distractor_rationales,
                    "misconception_tag": q.misconception_tag,
                    "_concepts_covered": concepts,
                }
                for q in questions
            ])
            log.info(
                "quiz_pregenerate.version_done",
                message_id=message_id,
                version=attempt + 1,
                question_count=len(questions),
            )
        except Exception as exc:
            log.warning(
                "quiz_pregenerate.version_failed",
                message_id=message_id,
                version=attempt + 1,
                error=str(exc),
            )
            versions.append([])

    return versions


async def _run(message_id: str, content: str) -> None:
    redis = await get_redis()
    key = _quiz_key(message_id)

    # Skip if already cached (e.g. duplicate trigger)
    existing = await redis.exists(key)
    if existing:
        log.info("quiz_pregenerate.already_cached", message_id=message_id)
        return

    versions = await _generate_versions(message_id, content)

    payload = json.dumps({
        "versions": versions,
        "counter": 0,  # tracks which version to serve next (0-indexed)
    })
    await redis.setex(key, _QUIZ_TTL_SECONDS, payload)
    log.info(
        "quiz_pregenerate.cached",
        message_id=message_id,
        versions_stored=len([v for v in versions if v]),
    )


@celery_app.task(name="quiz_pregenerate_for_message", bind=True, max_retries=2)
def pregenerate_quiz_for_message(self, message_id: str, content: str) -> None:  # type: ignore[misc]
    """Celery task: generate 3 quiz versions and store in Redis."""
    try:
        asyncio.run(_run(message_id, content))
    except Exception as exc:
        log.warning(
            "quiz_pregenerate.task_failed",
            message_id=message_id,
            error=str(exc),
        )
        raise self.retry(exc=exc, countdown=30)
