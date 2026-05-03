"""D10 / Pass 3d §D.4 — log_event universal tool.

Audited @tool wrapper that emits a structured log event the agent
specifically wants to surface. Distinct from the auto-logged
`agent_actions` row that every agent execution writes — this is for
*additional* events agents want to mark (a breakthrough, an
escalation pattern, a noteworthy student state).

Per Pass 3d §D.4 spec verbatim:
  • Permissions: write:audit_log.
  • Implementation: wraps structlog + PostHog. Already-instrumented
    agent actions don't need this; this is for *additional* events
    agents want to surface.

PostHog wiring is deferred to a follow-up — v1 emits via structlog
which is already routed to the operational logging pipeline. Adding
PostHog later is a one-line `posthog.capture(...)` call inside the
tool body and does not change the public input/output schema.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(layer="tools.universal.log_event")

# Pass 3d §D.4 originally pinned event_name to the regex
# `^[a-z_]+\.[a-z_]+$` (e.g. "tutor.student_breakthrough"). We
# enforce that here so log queries can rely on the consistent shape.
_EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class LogEventInput(BaseModel):
    """A single structured event to emit.

    Field validation matches Pass 3d §D.4 verbatim. The properties
    dict is free-form — agents are expected to choose stable key
    names for things they want to chart later.
    """

    model_config = ConfigDict(extra="forbid")

    event_name: str = Field(
        min_length=3,
        max_length=120,
        description=(
            "Dotted lowercase event name, e.g. "
            "'tutor.student_breakthrough'. Must match "
            "^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$ so log dashboards can "
            "consistently group on namespace."
        ),
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Structured event properties. Free-form by design; pick "
            "stable key names if you plan to chart on them."
        ),
    )
    severity: Literal["debug", "info", "warning", "error"] = Field(
        default="info",
        description="Log severity. Routes to the matching structlog level.",
    )

    @field_validator("event_name")
    @classmethod
    def _check_event_name_shape(cls, v: str) -> str:
        if not _EVENT_NAME_PATTERN.match(v):
            raise ValueError(
                f"event_name {v!r} must match "
                "^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$ (e.g. "
                "'tutor.student_breakthrough')."
            )
        return v


class LogEventOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logged: bool = Field(
        description="Always True when no exception was raised; False reserved for downstream sinks.",
    )


@tool(
    name="log_event",
    description=(
        "Emit a structured event the agent specifically wants to "
        "surface — a breakthrough, an unusual state, a noteworthy "
        "decision worth tracking. Distinct from the auto-logged "
        "agent_actions row every execution writes. Use sparingly: "
        "the auto-log already covers the common case."
    ),
    input_schema=LogEventInput,
    output_schema=LogEventOutput,
    requires=("write:audit_log",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def log_event(args: LogEventInput) -> LogEventOutput:
    """Route to the matching structlog severity. PostHog wiring is
    a follow-up — for v1, structlog is the only sink."""
    method = getattr(log, args.severity, log.info)
    method(
        args.event_name,
        # Spread properties so they show up as top-level keys in
        # JSON-formatted log lines (easier to query than nested).
        **args.properties,
    )
    return LogEventOutput(logged=True)


__all__ = ["LogEventInput", "LogEventOutput", "log_event"]
