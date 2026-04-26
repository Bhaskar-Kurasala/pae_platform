"""Summarize an assistant chat reply into a student-edit-ready note.

The chat answers we ship are long. Pasting one verbatim into the notebook
produces a wall-of-text the student is unlikely to revisit. This service
turns a reply into:
  * a concise prose summary (<= 6 short bullets, recall-oriented)
  * 3–5 lowercase tag suggestions the student can keep, edit, or replace

Both halves are surfaced in the SaveNoteModal so the student edits *before*
saving — the act of rewriting is what makes the note stick. The raw assistant
text is still saved on the entry as `content` (audit trail / "show original"),
while the canonical display text becomes whatever the student typed.

Caching: keyed by `(message_id, len(content))`. The message id is the natural
cache key, and including the content length kills the (rare) case where
upstream regenerated the message but kept the id.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm_factory import build_llm
from app.core.redis import get_redis, namespaced_key

log = structlog.get_logger().bind(service="notebook_summarize")

# 1h cache. The student can re-open the modal multiple times while drafting;
# we don't want to bill another LLM call for a re-render.
_CACHE_TTL_SECONDS = 60 * 60

# Strict cap so very long replies don't blow the input budget. Anything past
# this is enough context for a summary; we trim from the END so the question
# context (early in the reply) survives.
_MAX_CONTENT_CHARS = 8_000

_SYSTEM_PROMPT = """You help a learner save a study note from an AI assistant's reply.

Your job: turn the reply into a tight, recall-oriented summary the student can later
re-read in 30 seconds and remember the key takeaways.

Rules:
- Output STRICT JSON only. No prose before or after, no markdown fences.
- The summary MUST be plain Markdown bullets (lines starting with "- ").
- 3 to 6 bullets max. Each bullet <= 18 words. No nested bullets.
- Lead with the answer or insight, then the *why*. Skip greetings, preamble,
  apologies, and meta talk ("As mentioned above…").
- Preserve any concrete: numbers, function names, formulas, command names.
- Tags: 3–5 short lowercase noun-phrases (e.g. "rag", "vector-search",
  "embedding-models"). Use kebab-case. No "#" prefix.

Output schema:
{
  "summary": "- bullet 1\\n- bullet 2\\n- bullet 3",
  "tags": ["tag-one", "tag-two", "tag-three"]
}
"""


def _normalize_llm_content(content: Any) -> str:
    """Coerce a LangChain `response.content` into a plain string.

    Mirrors `career_service.normalize_llm_content` — duplicated locally so this
    module stays importable in 3.10 test environments that can't load the
    full models tree. MiniMax returns content as a list of {type, text|content}
    dicts mixing thinking + text blocks; Anthropic returns plain str.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "thinking":
                    continue
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first balanced {…} JSON object from *text*.

    LLM output may include thinking text or markdown fences before the JSON;
    scan for the first `{` and walk the string tracking brace depth until
    the matching `}`.
    """
    match = re.search(r"\{", text)
    if not match:
        return {}
    start = match.start()
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])  # noqa: E203
                except json.JSONDecodeError:
                    return {}
    return {}


@dataclass(frozen=True)
class NoteSummary:
    summary: str
    tags: list[str]
    cached: bool


def _cache_key(message_id: str, content_len: int) -> str:
    return namespaced_key("notebook", "summary", message_id, str(content_len))


def _coerce_tags(raw: Any) -> list[str]:
    """Normalize tags from arbitrary LLM output into kebab-case noun-phrases.

    LLMs occasionally hand back strings instead of arrays, or include "#" /
    capital letters / spaces. Be lenient on input, strict on output.
    """
    if isinstance(raw, str):
        # Allow "rag, vector-search, embeddings" as a string fallback.
        candidates: list[str] = [t.strip() for t in raw.split(",")]
    elif isinstance(raw, list):
        candidates = [str(t).strip() for t in raw]
    else:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if not c:
            continue
        # Drop hashes, lower-case, collapse whitespace to "-".
        norm = c.lstrip("#").strip().lower()
        norm = "-".join(norm.split())
        if not norm or norm in seen:
            continue
        seen.add(norm)
        cleaned.append(norm)
        if len(cleaned) >= 5:
            break
    return cleaned


def _coerce_summary(raw: Any, fallback_content: str) -> str:
    """Return a clean bullet-list summary, or a graceful fallback."""
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    # Last-ditch: take the first ~3 lines of the original content as a stub.
    head = [ln.strip() for ln in fallback_content.splitlines() if ln.strip()][:3]
    if not head:
        return fallback_content[:200].strip()
    return "\n".join(f"- {ln[:140]}" for ln in head)


async def summarize_for_notebook(
    *,
    message_id: str,
    content: str,
    user_question: str | None = None,
    use_cache: bool = True,
) -> NoteSummary:
    """Summarize *content* into a note + suggested tags.

    On Redis miss, calls MiniMax (or Anthropic, depending on which key is
    configured — see `build_llm`). On any LLM or parse failure we degrade
    to a deterministic head-of-text fallback rather than 5xx-ing the modal:
    the student can always edit the box themselves.
    """
    if not content or not content.strip():
        return NoteSummary(summary="", tags=[], cached=False)

    trimmed = content[:_MAX_CONTENT_CHARS]

    cache_key = _cache_key(message_id, len(trimmed))
    if use_cache:
        try:
            redis = await get_redis()
            cached_raw = await redis.get(cache_key)
            if cached_raw:
                cached = json.loads(cached_raw)
                return NoteSummary(
                    summary=str(cached.get("summary", "")),
                    tags=list(cached.get("tags", []) or []),
                    cached=True,
                )
        except Exception as exc:  # pragma: no cover — redis hiccups must not block
            log.warning("notebook_summarize.cache_read_failed", error=str(exc))

    human_parts: list[str] = []
    if user_question:
        human_parts.append(f"The student asked:\n{user_question.strip()}")
    human_parts.append(f"Assistant reply to summarize:\n{trimmed}")
    human = "\n\n".join(human_parts)

    summary_text = ""
    tags: list[str] = []
    try:
        llm = build_llm(max_tokens=600, tier="fast")
        messages: list[Any] = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=human),
        ]
        response = await llm.ainvoke(messages)
        raw_text = _normalize_llm_content(response.content)
        parsed = _extract_json_object(raw_text)
        summary_text = _coerce_summary(parsed.get("summary"), trimmed)
        tags = _coerce_tags(parsed.get("tags"))
    except Exception as exc:
        log.warning(
            "notebook_summarize.llm_failed",
            message_id=message_id,
            error=str(exc),
        )
        summary_text = _coerce_summary(None, trimmed)
        tags = []

    if use_cache and summary_text:
        try:
            redis = await get_redis()
            await redis.setex(
                cache_key,
                _CACHE_TTL_SECONDS,
                json.dumps({"summary": summary_text, "tags": tags}),
            )
        except Exception as exc:  # pragma: no cover
            log.warning("notebook_summarize.cache_write_failed", error=str(exc))

    return NoteSummary(summary=summary_text, tags=tags, cached=False)
