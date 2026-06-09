"""Content tools — RAG over course content.

Today the only tool here is `search_course_content`. The Pinecone
integration is out of scope for the primitives layer; the stub
schema is the contract that the eventual implementation will honour.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.tools import tool


class SearchCourseContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    course_id: uuid.UUID | None = None
    lesson_id: uuid.UUID | None = None
    k: int = Field(default=5, ge=1, le=20)


class CourseContentHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lesson_id: uuid.UUID
    lesson_title: str
    snippet: str
    score: float = Field(ge=0.0, le=1.0)


class SearchCourseContentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hits: list[CourseContentHit]
    used_index: str = Field(
        description=(
            "Free-form name of the backing index — 'pinecone:course-v1' "
            "or 'pgvector:lesson-chunks'. Useful for ablation / debug."
        ),
    )


@tool(
    name="search_course_content",
    description=(
        "Hybrid search over course content (lesson transcripts, slides, "
        "exercise prompts). Returns the top-k most relevant excerpts "
        "with a confidence score and lesson anchor."
    ),
    input_schema=SearchCourseContentInput,
    output_schema=SearchCourseContentOutput,
    requires=("read:course_content",),
    cost_estimate=0.0005,  # one embedding + one vector query
    is_stub=True,
)
async def search_course_content(
    args: SearchCourseContentInput,
) -> SearchCourseContentOutput:
    raise NotImplementedError(
        "stub: real implementation lands when the Pinecone (or "
        "pgvector) chunk index is wired. Schema is stable."
    )
