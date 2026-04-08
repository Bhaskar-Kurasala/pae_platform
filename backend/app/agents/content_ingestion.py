import json
from pathlib import Path
from typing import Any

import structlog

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register

log = structlog.get_logger()

_PROMPT_PATH = Path(__file__).parent / "prompts" / "content_ingestion.md"


@register
class ContentIngestionAgent(BaseAgent):
    name = "content_ingestion"
    description = "Ingests YouTube videos or GitHub commits and returns structured content metadata for curriculum mapping."
    trigger_conditions = [
        "ingest",
        "youtube",
        "github push",
        "new video",
        "process content",
    ]
    model = "claude-sonnet-4-6"

    async def execute(self, state: AgentState) -> AgentState:
        # TODO: connect YouTube Data API and GitHub API
        url = state.context.get("url", "")
        github_commit = state.context.get("github_commit", "")

        source = url or github_commit or state.task

        # Determine content type heuristically
        if "youtube.com" in source or "youtu.be" in source:
            content_type = "youtube_video"
            title = "Introduction to LangGraph State Management"
            topics = ["LangGraph", "State Management", "Agent Orchestration"]
            duration_seconds = 1823
            transcript_stub = (
                "In this video we explore LangGraph's state machine model, "
                "covering how nodes, edges, and conditional routing work together..."
            )
        elif github_commit or "github.com" in source:
            content_type = "github_commit"
            title = "Add RAG pipeline with Pinecone vector store"
            topics = ["RAG", "Pinecone", "Vector Databases", "Embeddings"]
            duration_seconds = 0
            transcript_stub = (
                "Commit adds production-ready RAG pipeline: embedding generation, "
                "Pinecone upsert, similarity search, and context injection..."
            )
        else:
            content_type = "unknown"
            title = "Untitled Content"
            topics = ["General AI Engineering"]
            duration_seconds = 0
            transcript_stub = "Content could not be classified."

        metadata: dict[str, Any] = {
            "title": title,
            "topics": topics,
            "duration_seconds": duration_seconds,
            "transcript_stub": transcript_stub,
            "content_type": content_type,
            "source": source,
            "status": "ingested",
        }

        return state.model_copy(
            update={
                "response": json.dumps(metadata, indent=2),
                "context": {**state.context, "content_metadata": metadata},
                "tools_used": state.tools_used + ["content_ingestion_stub"],
            }
        )
