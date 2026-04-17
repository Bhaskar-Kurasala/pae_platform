import json
from pathlib import Path
from typing import Any

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import SecretStr
from tenacity import retry, stop_after_attempt, wait_exponential

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "content_ingestion.md").read_text()


def _get_github_client() -> Any:
    """Return a PyGitHub client or None if token not configured."""
    if not settings.github_token:
        return None
    try:
        from github import Github  # type: ignore[import]

        return Github(settings.github_token)
    except ImportError:
        log.warning("content_ingestion.pygithub_missing")
        return None


@register
class ContentIngestionAgent(BaseAgent):
    """Ingests content from GitHub URLs, YouTube URLs, or free text.

    - GitHub URLs: fetches README + first 3 Python files, extracts key concepts
      via Claude Sonnet summarisation.
    - YouTube URLs: returns a structured stub logged for Phase 6 ingestion
      (requires YouTube Data API v3 key — not yet configured).
    - Text/other: uses Claude to extract key concepts and suggest lesson category.

    TODO (Phase 6): Wire YouTube Data API v3 for real transcript ingestion.
    """

    name = "content_ingestion"
    description = (
        "Ingests GitHub repos, YouTube videos, or free text and returns structured "
        "content metadata with AI-extracted key concepts."
    )
    trigger_conditions = [
        "ingest",
        "youtube",
        "github push",
        "new video",
        "process content",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self) -> ChatAnthropic:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=self.model,
            anthropic_api_key=SecretStr(settings.anthropic_api_key) if settings.anthropic_api_key else None,
            max_tokens=512,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _summarise_text(self, llm: ChatAnthropic, raw_text: str, source: str) -> dict[str, Any]:
        """Use Claude to extract key concepts and suggest a lesson category."""
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Content source: {source}\n\n"
                    f"Raw content (truncated to 3000 chars):\n{raw_text[:3000]}\n\n"
                    "Please return a JSON object with these fields:\n"
                    "- title: a short descriptive title for this content\n"
                    "- topics: list of 3-5 key technical concepts covered\n"
                    "- summary: a 100-word summary of the content\n"
                    "- lesson_category: which PAE curriculum category this fits best "
                    "(one of: RAG, LangGraph, FastAPI, Pydantic, Embeddings, LLM Evaluation, "
                    "Production Deployment, Agent Architecture, General AI Engineering)\n"
                    "- difficulty: beginner | intermediate | advanced\n\n"
                    "Return ONLY valid JSON, no markdown code fences."
                )
            ),
        ]
        response = await llm.ainvoke(messages)
        raw = str(response.content).strip()

        # Strip markdown fences if present
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        return json.loads(raw)

    async def _ingest_github(self, url: str) -> dict[str, Any]:
        """Fetch README + first 3 Python files and summarise with Claude."""
        gh = _get_github_client()

        raw_content_parts: list[str] = []
        repo_name = "unknown"

        if gh:
            try:
                # Parse repo path from URL: github.com/{owner}/{repo}
                parts = url.rstrip("/").split("github.com/")[-1].split("/")
                if len(parts) >= 2:
                    repo_path = f"{parts[0]}/{parts[1]}"
                    repo = gh.get_repo(repo_path)
                    repo_name = repo.full_name

                    # Fetch README
                    try:
                        readme = repo.get_readme()
                        raw_content_parts.append(f"README:\n{readme.decoded_content.decode('utf-8', errors='replace')[:2000]}")
                    except Exception:
                        pass

                    # Fetch first 3 Python files from root
                    py_count = 0
                    try:
                        root_contents = repo.get_contents("")
                        # get_contents returns list or single ContentFile
                        content_list = root_contents if isinstance(root_contents, list) else [root_contents]
                        for file_content in content_list:
                            if py_count >= 3:
                                break
                            if hasattr(file_content, "type") and file_content.type == "file" and file_content.name.endswith(".py"):
                                try:
                                    code = file_content.decoded_content.decode("utf-8", errors="replace")
                                    raw_content_parts.append(f"File: {file_content.name}\n{code[:1000]}")
                                    py_count += 1
                                except Exception:
                                    pass
                    except Exception as exc:
                        self._log.warning("content_ingestion.github_files_failed", error=str(exc))
            except Exception as exc:
                self._log.warning("content_ingestion.github_fetch_failed", url=url, error=str(exc))

        raw_text = "\n\n".join(raw_content_parts) or (
            f"GitHub repository at {url}. "
            "No content could be fetched (check GITHUB_TOKEN configuration)."
        )

        metadata: dict[str, Any] = {
            "source_type": "github_repo",
            "source": url,
            "repo_name": repo_name,
            "status": "ingested",
        }

        if settings.anthropic_api_key and raw_content_parts:
            try:
                llm = self._build_llm()
                summary = await self._summarise_text(llm, raw_text, url)
                metadata.update(summary)
            except Exception as exc:
                self._log.warning("content_ingestion.summarise_failed", error=str(exc))
                metadata.update({
                    "title": f"GitHub: {repo_name}",
                    "topics": ["GitHub Repository"],
                    "summary": f"Content from {url} (summarisation failed)",
                    "lesson_category": "General AI Engineering",
                    "difficulty": "intermediate",
                })
        else:
            metadata.update({
                "title": f"GitHub: {repo_name}",
                "topics": ["GitHub Repository"],
                "summary": raw_text[:200],
                "lesson_category": "General AI Engineering",
                "difficulty": "intermediate",
            })

        return metadata

    async def _ingest_youtube(self, url: str) -> dict[str, Any]:
        """Return a structured stub for YouTube content.

        YouTube Data API v3 integration is queued for Phase 6.
        Requires YOUTUBE_DATA_API_KEY in settings.
        """
        self._log.info(
            "content_ingestion.youtube_queued",
            url=url,
            reason="YouTube transcript ingestion requires YouTube Data API v3 key — Phase 6",
        )
        return {
            "source_type": "youtube_video",
            "source": url,
            "title": "YouTube Video (pending ingestion)",
            "topics": [],
            "summary": (
                "YouTube transcript ingestion requires YouTube Data API v3 key — "
                "queued for Phase 6."
            ),
            "lesson_category": "General AI Engineering",
            "difficulty": "intermediate",
            "status": "queued_phase6",
            "phase6_note": (
                "To enable: add YOUTUBE_DATA_API_KEY to settings and implement "
                "youtube_transcript_api integration in content_ingestion.py."
            ),
        }

    async def _ingest_text(self, text: str) -> dict[str, Any]:
        """Use Claude to extract key concepts from free text."""
        if settings.anthropic_api_key:
            try:
                llm = self._build_llm()
                summary = await self._summarise_text(llm, text, "user-provided text")
                summary["source_type"] = "text"
                summary["source"] = text[:100]
                summary["status"] = "ingested"
                return summary
            except Exception as exc:
                self._log.warning("content_ingestion.text_summarise_failed", error=str(exc))

        return {
            "source_type": "text",
            "source": text[:100],
            "title": "Ingested Text Content",
            "topics": ["General AI Engineering"],
            "summary": text[:200],
            "lesson_category": "General AI Engineering",
            "difficulty": "intermediate",
            "status": "ingested",
        }

    async def execute(self, state: AgentState) -> AgentState:
        url: str = state.context.get("url", "")
        github_commit: str = state.context.get("github_commit", "")

        source = url or github_commit or state.task

        if "youtube.com" in source or "youtu.be" in source:
            metadata = await self._ingest_youtube(source)
        elif "github.com" in source or github_commit:
            metadata = await self._ingest_github(source)
        else:
            metadata = await self._ingest_text(source)

        return state.model_copy(
            update={
                "response": json.dumps(metadata, indent=2),
                "context": {**state.context, "content_metadata": metadata},
                "tools_used": state.tools_used + ["content_ingestion"],
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        try:
            result = json.loads(state.response or "{}")
            has_topics = bool(result.get("topics"))
            has_summary = bool(result.get("summary"))
            score = 0.9 if (has_topics and has_summary) else (0.6 if has_topics else 0.4)
        except (json.JSONDecodeError, TypeError):
            score = 0.3
        return state.model_copy(update={"evaluation_score": score})
