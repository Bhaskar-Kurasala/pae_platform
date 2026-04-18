import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "code_review.md").read_text()


@tool
def analyze_code(code: str, language: str = "python") -> str:
    """Run static analysis on submitted code.

    Runs ruff (for Python) and returns findings as a structured string.

    Args:
        code: The source code to analyze.
        language: Programming language (default: python).

    Returns:
        Analysis results as a formatted string.
    """
    if language != "python":
        return f"Static analysis for {language} not yet supported."

    findings: list[str] = []

    # Check for common issues without running code
    checks = [
        ("print(", "Use structlog instead of print() for logging"),
        ("import *", "Avoid wildcard imports"),
        ("except:", "Bare except clause — catch specific exceptions"),
        ("os.environ[", "Use pydantic-settings instead of os.environ directly"),
        ("password", "Potential credential — ensure this is not hardcoded"),
        ("api_key", "Potential credential — ensure this is not hardcoded"),
    ]
    for pattern, message in checks:
        if pattern.lower() in code.lower():
            findings.append(f"WARNING: {message}")

    # Run ruff if available
    try:
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(code)
            tmp_path = f.name
        result = subprocess.run(
            ["ruff", "check", "--output-format=concise", tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.stdout.strip():
            ruff_lines = result.stdout.strip().split("\n")
            # Strip the temp file path for cleanliness
            findings.extend(
                [ln.replace(tmp_path, "<code>") for ln in ruff_lines[:10]]
            )
        Path(tmp_path).unlink(missing_ok=True)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        findings.append("INFO: ruff not available for static analysis")

    if not findings:
        return "Static analysis: No issues found."
    return "Static analysis findings:\n" + "\n".join(findings)


@register
class CodeReviewAgent(BaseAgent):
    name = "code_review"
    description = "Reviews student code for correctness, production-readiness, and LLM best practices. Returns structured JSON feedback with score 0–100."
    trigger_conditions = [
        "review my code",
        "check my code",
        "code review",
        "is this code correct",
        "feedback on my code",
        "submit code",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self, max_tokens: int = 1024):
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    async def execute(self, state: AgentState) -> AgentState:
        code = state.context.get("code", state.task)

        # Run static analysis first
        static_results = analyze_code.invoke({"code": code, "language": "python"})

        llm = self._build_llm()
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Please review this code:\n\n```python\n{code}\n```\n\n"
                    f"Static analysis pre-results:\n{static_results}\n\n"
                    "Return your review as JSON matching the schema in the system prompt."
                )
            ),
        ]

        response = await llm.ainvoke(messages)
        raw = str(response.content)

        # Try to parse JSON; fall back gracefully
        review_json: dict[str, Any] = {}
        try:
            # Extract JSON from markdown code blocks if present
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            review_json = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            review_json = {"raw_response": raw, "score": 0, "approved": False}

        return state.model_copy(
            update={
                "response": json.dumps(review_json, indent=2),
                "tools_used": state.tools_used + ["analyze_code"],
                "context": {**state.context, "review": review_json},
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        """Score is valid if review JSON contains a numeric score."""
        try:
            review = json.loads(state.response or "{}")
            score_raw = review.get("score", 0)
            score = float(score_raw) / 100.0 if isinstance(score_raw, (int, float)) else 0.5
        except (json.JSONDecodeError, TypeError, ValueError):
            score = 0.5
        return state.model_copy(update={"evaluation_score": min(1.0, max(0.0, score))})
