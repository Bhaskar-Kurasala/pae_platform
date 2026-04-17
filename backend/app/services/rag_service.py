"""RAG Service — semantic search over course content.

Provides semantic search over course content.
Uses Pinecone when API key present; falls back to keyword search on mock data.

TODO (Phase 6): Wire real embeddings via Anthropic and full Pinecone integration.
"""

from typing import Any

import structlog

log = structlog.get_logger()

_PINECONE_INDEX_NAME = "pae-course-content"

# Mock results returned when Pinecone is not configured
_MOCK_RESULTS: list[dict[str, Any]] = [
    {
        "content": (
            "RAG (Retrieval Augmented Generation) in development — Pinecone key required. "
            "RAG combines retrieval of relevant documents from a vector store with LLM generation. "
            "Key components: document ingestion, chunking, embedding, vector storage, similarity search."
        ),
        "source": "mock:rag-overview",
        "score": 0.85,
    },
    {
        "content": (
            "RAG (Retrieval Augmented Generation) in development — Pinecone key required. "
            "LangGraph integrates with RAG via dedicated retrieval nodes in the state graph. "
            "The retrieval node enriches AgentState before the generation step."
        ),
        "source": "mock:langgraph-rag",
        "score": 0.78,
    },
    {
        "content": (
            "RAG (Retrieval Augmented Generation) in development — Pinecone key required. "
            "Vector embeddings convert text into high-dimensional numerical representations "
            "that capture semantic meaning, enabling similarity search."
        ),
        "source": "mock:embeddings",
        "score": 0.72,
    },
]


class RagService:
    """Semantic search service over PAE course content.

    When `api_key` is None or empty, returns mock results with a warning.
    When `api_key` is present, queries Pinecone index 'pae-course-content'
    using Anthropic embeddings.
    """

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key or ""
        self._log = log.bind(service="rag_service")
        self._pinecone_client: Any | None = None

    def _get_pinecone(self) -> Any | None:
        """Lazily initialise Pinecone client."""
        if not self._api_key:
            return None
        if self._pinecone_client is not None:
            return self._pinecone_client
        try:
            from pinecone import Pinecone  # type: ignore[import]

            self._pinecone_client = Pinecone(api_key=self._api_key)
            return self._pinecone_client
        except ImportError:
            self._log.warning("rag_service.pinecone_not_installed")
            return None
        except Exception as exc:
            self._log.warning("rag_service.pinecone_init_failed", error=str(exc))
            return None

    async def _embed(self, text: str) -> list[float]:
        """Create an embedding via Anthropic embeddings API.

        Note: Anthropic does not yet expose a public embeddings endpoint at the
        time of writing. This stub uses a placeholder until the API is available.
        When available, replace with: anthropic.embeddings.create(text=text, ...)
        """
        # STUB: Anthropic embeddings API not yet publicly available (as of Phase 5).
        # Phase 6 will replace this with the real endpoint or OpenAI ada-002.
        self._log.debug("rag_service.embed_stub", text_length=len(text))
        # Return a zero vector of dimension 1536 as placeholder
        return [0.0] * 1536

    async def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Search course content for the given query.

        Args:
            query: The search query string.
            top_k: Number of results to return (default 5).

        Returns:
            List of dicts with keys: content (str), source (str), score (float).
        """
        pc = self._get_pinecone()

        if not pc or not self._api_key:
            self._log.warning(
                "rag_service.using_mock_results",
                reason="Pinecone API key not configured",
                query_preview=query[:60],
            )
            return _MOCK_RESULTS[:top_k]

        try:
            embedding = await self._embed(query)
            index = pc.Index(_PINECONE_INDEX_NAME)
            results = index.query(vector=embedding, top_k=top_k, include_metadata=True)

            hits: list[dict[str, Any]] = []
            for match in results.get("matches", []):
                metadata = match.get("metadata", {})
                hits.append({
                    "content": metadata.get("content", ""),
                    "source": metadata.get("source", match.get("id", "")),
                    "score": float(match.get("score", 0.0)),
                })

            self._log.info("rag_service.search_complete", query_preview=query[:60], results=len(hits))
            return hits

        except Exception as exc:
            self._log.warning("rag_service.search_failed", error=str(exc))
            return _MOCK_RESULTS[:top_k]

    async def upsert_lesson(
        self,
        lesson_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        """Upsert a lesson's content into the Pinecone index.

        Args:
            lesson_id: Unique identifier for the lesson (used as vector ID).
            content: The lesson text content to embed and store.
            metadata: Additional metadata to attach (title, course_id, etc.).

        Note: This is a stub until Anthropic embeddings API is available.
        Full implementation in Phase 6.
        """
        self._log.info(
            "rag_service.upsert_lesson_stub",
            lesson_id=lesson_id,
            content_length=len(content),
            reason="Embedding API not yet available — Phase 6",
        )
        pc = self._get_pinecone()
        if not pc:
            self._log.warning("rag_service.upsert_skipped", reason="Pinecone not configured")
            return

        # STUB: Real implementation will:
        # 1. embedding = await self._embed(content)
        # 2. index.upsert(vectors=[(lesson_id, embedding, {**metadata, "content": content})])
        self._log.debug("rag_service.upsert_lesson_noop", lesson_id=lesson_id)
