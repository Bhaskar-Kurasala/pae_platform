"""Code-quality tools.

`run_ruff` is the only tool here today. It runs the same linter the
existing `code_review` agent already uses (see
`app/agents/code_review.py::analyze_code`) but exposed through the
new tool registry so a multi-agent flow can call it via the executor
and get an audit row.

Why duplicate the existing tool surface: the legacy `code_review`
agent uses `langchain_core.tools.@tool`, which does not register
with our new `ToolRegistry` and skips the executor's audit /
timeout / retry path. New agents (and the eventual `code_review`
migration) should call this entry point instead.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.tools import tool


class RunRuffInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=200_000)
    select: list[str] | None = Field(
        default=None,
        description=(
            "Optional ruff rule selectors (e.g. ['E', 'F', 'I']). "
            "When None, runs the project's default config."
        ),
    )


class RuffFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_code: str
    message: str
    line: int = Field(ge=1)
    column: int = Field(ge=1)
    severity: Literal["error", "warning", "info"] = "warning"


class RunRuffOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[RuffFinding]
    summary: str
    ran_against_version: str | None = None


@tool(
    name="run_ruff",
    description=(
        "Run ruff against a snippet of Python source. Returns "
        "structured findings (rule code, message, line/column, "
        "severity) — not free-form stdout. The `code_review` agent "
        "should call this instead of using the legacy in-file linter."
    ),
    input_schema=RunRuffInput,
    output_schema=RunRuffOutput,
    requires=("read:public",),  # no DB access; effectively unrestricted
    cost_estimate=0.0,
    timeout_seconds=15.0,
    is_stub=True,
)
async def run_ruff(args: RunRuffInput) -> RunRuffOutput:
    raise NotImplementedError(
        "stub: real implementation shells out to ruff with --output-format=json "
        "and parses findings. Lands in DX."
    )
