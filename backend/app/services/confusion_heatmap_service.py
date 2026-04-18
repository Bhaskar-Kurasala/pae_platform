"""Confusion heatmap service (P2-13).

Admin-facing analytics that surface the concepts students are struggling with
most — ranked by help-request volume, distinct students affected, and recency.

Signal sources (all already logged, no new writes):
- `agent_actions` rows for the help-oriented agents
  (socratic_tutor, coding_assistant, student_buddy, code_review).
  `input_data["task"]` holds the student's actual question.

Bucketing strategy (deterministic, no LLM):
- Lowercase the task text and match against a curated canonical-topic list
  (RAG, embeddings, prompt injection, etc.). First hit wins.
- If no canonical topic hits, try skill names and lesson titles from the DB.
- Else bucket as "other".

Ranking:
    score = help_count * sqrt(distinct_students) * recency_decay(last_ts)

where `recency_decay` falls from 1.0 (today) to 0.3 at 30+ days, so a topic
that students struggled with a month ago doesn't drown out current pain.

Pure bucketing + ranking helpers live at the top of the module so they're
unit-testable without the DB.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_action import AgentAction
from app.models.lesson import Lesson
from app.models.skill import Skill

log = structlog.get_logger()


# Help-oriented agents whose invocations count as a "student asked for help".
# Creation / analytics / admin agents are excluded so we don't inflate the signal.
HELP_AGENTS: tuple[str, ...] = (
    "socratic_tutor",
    "coding_assistant",
    "student_buddy",
    "code_review",
    "project_evaluator",
)


# Canonical production-AI topics the platform teaches. These take priority over
# lesson-title / skill-name matching because they're the mental-model buckets
# admins actually want to reason about.
#
# Each entry: (bucket_label, [keyword, keyword, ...])
# Keywords are matched against the lowercased task text with word boundaries.
CANONICAL_TOPICS: list[tuple[str, list[str]]] = [
    ("RAG", ["rag", "retrieval augmented", "retrieval-augmented"]),
    ("Embeddings", ["embedding", "embeddings", "vector search", "cosine similarity"]),
    ("Prompt injection", ["prompt injection", "jailbreak", "prompt leak"]),
    ("Fine-tuning vs RAG", ["fine-tune", "fine tuning", "finetune", "lora", "sft"]),
    ("Chunking", ["chunk", "chunking", "splitter"]),
    ("Evaluation", ["eval", "evals", "evaluation", "llm-as-judge", "golden set"]),
    ("Hallucination", ["hallucinate", "hallucination", "made up"]),
    ("Agents / tool use", ["tool use", "function call", "agent loop", "react agent"]),
    ("Streaming", ["streaming", "sse", "stream response"]),
    ("Token cost", ["token cost", "cost per", "pricing", "billing", "quota"]),
    ("Vector DB", ["pinecone", "weaviate", "pgvector", "chroma", "qdrant"]),
    ("Attention / transformers", ["attention", "transformer", "self-attention"]),
    ("Context window", ["context window", "context length", "long context"]),
    ("Guardrails", ["guardrail", "moderation", "safety filter"]),
    ("Memory / history", ["conversation memory", "chat history", "short-term memory"]),
]


_WORD_BOUNDARY_CACHE: dict[str, re.Pattern[str]] = {}


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    pat = _WORD_BOUNDARY_CACHE.get(keyword)
    if pat is None:
        # Allow internal spaces / hyphens; use \b on word chars only.
        escaped = re.escape(keyword).replace(r"\ ", r"[\s-]+").replace(r"\-", r"[\s-]?")
        pat = re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)
        _WORD_BOUNDARY_CACHE[keyword] = pat
    return pat


def bucket_task(
    task: str,
    *,
    skill_names: list[str] | None = None,
    lesson_titles: list[str] | None = None,
) -> str:
    """Assign a task string to a confusion bucket.

    Priority: canonical topics → skill names → lesson titles → "Other".

    Returned label is already display-ready.
    """
    if not task or not task.strip():
        return "Other"

    text = task.lower()
    for label, keywords in CANONICAL_TOPICS:
        for kw in keywords:
            if _keyword_pattern(kw).search(text):
                return label

    for name in skill_names or []:
        if not name:
            continue
        if _keyword_pattern(name).search(text):
            return name

    for title in lesson_titles or []:
        if not title:
            continue
        if _keyword_pattern(title).search(text):
            return title

    return "Other"


def recency_decay(last_ts: datetime | None, *, now: datetime | None = None) -> float:
    """Return a 0.3–1.0 multiplier based on how recent the last hit was.

    Today → 1.0. 30+ days old → 0.3 floor. Linear decay in between.
    Floor is non-zero because a six-month-old pattern still has *some* signal —
    we just don't want it dominating this week's pain.
    """
    if last_ts is None:
        return 0.3
    current = now or datetime.now(UTC)
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=UTC)
    days = max(0.0, (current - last_ts).total_seconds() / 86400.0)
    if days >= 30:
        return 0.3
    return 1.0 - (0.7 * days / 30.0)


@dataclass(frozen=True)
class ConfusionBucket:
    topic: str
    help_count: int                 # total help-agent invocations in this bucket
    distinct_students: int          # unique student_ids
    last_seen: datetime | None
    score: float                    # ranking score (higher = more painful right now)
    sample_questions: list[str]     # up to 3 deduped, redacted examples


def rank_buckets(
    rows: list[dict[str, Any]],
    *,
    skill_names: list[str] | None = None,
    lesson_titles: list[str] | None = None,
    now: datetime | None = None,
    max_samples: int = 3,
) -> list[ConfusionBucket]:
    """Turn raw agent_action rows into ranked confusion buckets.

    Each input row must have keys: `task` (str), `student_id` (str|None),
    `created_at` (datetime|None). Pure function — unit-testable without a DB.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        task = row.get("task") or ""
        if not task.strip():
            continue
        bucket = bucket_task(task, skill_names=skill_names, lesson_titles=lesson_titles)
        entry = grouped.setdefault(
            bucket,
            {
                "count": 0,
                "students": set(),
                "last": None,
                "samples": [],
            },
        )
        entry["count"] += 1
        sid = row.get("student_id")
        if sid:
            entry["students"].add(sid)
        ts = row.get("created_at")
        if ts is not None:
            if entry["last"] is None or ts > entry["last"]:
                entry["last"] = ts
        # Sample collection: first N unique trimmed tasks per bucket.
        if len(entry["samples"]) < max_samples:
            trimmed = task.strip()
            if len(trimmed) > 240:
                trimmed = trimmed[:237] + "…"
            if trimmed not in entry["samples"]:
                entry["samples"].append(trimmed)

    out: list[ConfusionBucket] = []
    for topic, data in grouped.items():
        distinct = len(data["students"])
        decay = recency_decay(data["last"], now=now)
        score = data["count"] * math.sqrt(max(distinct, 1)) * decay
        out.append(
            ConfusionBucket(
                topic=topic,
                help_count=data["count"],
                distinct_students=distinct,
                last_seen=data["last"],
                score=round(score, 2),
                sample_questions=list(data["samples"]),
            )
        )

    out.sort(key=lambda b: (b.score, b.help_count, b.distinct_students), reverse=True)
    return out


async def compute_heatmap(
    db: AsyncSession,
    *,
    days: int = 30,
    limit: int = 20,
    now: datetime | None = None,
) -> list[ConfusionBucket]:
    """Compute the admin confusion heatmap for the last `days` days.

    Pulls help-agent actions, loads skill + lesson names to enrich bucketing,
    and returns the top `limit` buckets ranked by score.
    """
    current = now or datetime.now(UTC)
    window_start = current - timedelta(days=days)

    action_rows = (
        await db.execute(
            select(
                AgentAction.input_data,
                AgentAction.student_id,
                AgentAction.created_at,
            ).where(
                AgentAction.agent_name.in_(HELP_AGENTS),
                AgentAction.created_at >= window_start,
            )
        )
    ).all()

    raw_rows: list[dict[str, Any]] = []
    for input_data, student_id, created_at in action_rows:
        # input_data is JSON — may be dict, None, or (edge case) a string.
        task = ""
        if isinstance(input_data, dict):
            candidate = (
                input_data.get("task")
                or input_data.get("question")
                or input_data.get("message")
                or input_data.get("code")
                or ""
            )
            if isinstance(candidate, str):
                task = candidate
        elif isinstance(input_data, str):
            task = input_data
        raw_rows.append(
            {
                "task": task,
                "student_id": str(student_id) if student_id else None,
                "created_at": created_at,
            }
        )

    skill_names = list(
        (await db.execute(select(Skill.name))).scalars().all()
    )
    lesson_titles = list(
        (await db.execute(select(Lesson.title))).scalars().all()
    )

    ranked = rank_buckets(
        raw_rows,
        skill_names=skill_names,
        lesson_titles=lesson_titles,
        now=current,
    )
    log.info(
        "confusion_heatmap.computed",
        days=days,
        rows=len(raw_rows),
        buckets=len(ranked),
    )
    return ranked[:limit]
