"""GitHub tools.

`read_github_pr` lets the Code Mentor agentic system read a PR
diff + metadata when a webhook fires. We already have a PyGithub
dependency (see backend pyproject.toml), so the eventual
implementation is just a thin wrapper.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.tools import tool


class ReadGitHubPRInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str = Field(min_length=1, max_length=200, description="GitHub user or org")
    repo: str = Field(min_length=1, max_length=200)
    number: int = Field(ge=1)
    include_diff: bool = True
    diff_max_bytes: int = Field(
        default=200_000,
        ge=1,
        le=2_000_000,
        description=(
            "Hard cap on the returned diff payload. Truncates with a "
            "trailing `...[+N bytes]` marker so the model can tell."
        ),
    )


class PRFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    status: Literal["added", "modified", "removed", "renamed"]
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)


class ReadGitHubPROutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    author_login: str
    state: Literal["open", "closed", "merged"]
    base_ref: str
    head_ref: str
    head_sha: str
    created_at: datetime
    updated_at: datetime
    files: list[PRFile]
    diff: str | None = None
    truncated: bool = False


@tool(
    name="read_github_pr",
    description=(
        "Fetch a pull request's metadata + (optional) diff from the "
        "GitHub REST API. Used by code_review-style agents that "
        "react to webhook pushes. Diff is hard-capped at "
        "`diff_max_bytes` to keep prompts bounded."
    ),
    input_schema=ReadGitHubPRInput,
    output_schema=ReadGitHubPROutput,
    requires=("read:github",),
    cost_estimate=0.0,  # GitHub REST is free for our scale
    timeout_seconds=20.0,
    is_stub=True,
)
async def read_github_pr(args: ReadGitHubPRInput) -> ReadGitHubPROutput:
    raise NotImplementedError(
        "stub: real implementation uses PyGithub with the "
        "GITHUB_TOKEN already in settings. Lands in DX."
    )
