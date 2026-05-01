"""Agentic OS primitives — public surface.

Each primitive is delivered as its own module; this `__init__` only
re-exports the symbols a downstream agent or test would import. Keep
the surface narrow on purpose — internal helpers stay private to
their module so we can refactor without breaking callers.

Deliverable map (D1 = migration 0054, already shipped):

    D2  memory.py        — MemoryStore + MemoryWrite + MemoryRow
    D3  tools.py         — ToolRegistry, @tool, ToolExecutor (later)
    D4  communication.py — call_agent + CycleDetectedError (later)
    D5  evaluation.py    — Critic + AgentResult + retry loop (later)
    D6  proactive.py     — @proactive cron + @on_event webhook (later)

Anything imported here is part of the stable public contract for the
primitives package.
"""

from app.agents.primitives.communication import (
    AgentCallResult,
    AgentNotFoundError,
    AgentPermissionError,
    AgenticCallee,
    CallChain,
    CallDepthExceededError,
    CommunicationError,
    CycleDetectedError,
    call_agent,
    clear_agentic_registry,
    get_agentic,
    list_agentic,
    register_agentic,
)
from app.agents.primitives.embeddings import (
    EMBEDDING_DIM,
    EmbeddingError,
    embed_batch,
    embed_text,
)
from app.agents.primitives.evaluation import (
    DEFAULT_ESCALATION_LIMIT_PER_AGENT,
    DEFAULT_ESCALATION_WINDOW_SECONDS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_THRESHOLD,
    AgentCoroFactory,
    AgentResult,
    Critic,
    CriticLLM,
    CriticResult,
    CriticVerdict,
    EscalationLimiter,
    escalation_limiter,
    evaluate_with_retry,
)
from app.agents.primitives.memory import (
    DEFAULT_SIMILARITY_THRESHOLD,
    MemoryRow,
    MemoryStore,
    MemoryWrite,
)
from app.agents.primitives.proactive import (
    PROACTIVE_TASK_NAME,
    ProactiveDispatchResult,
    ProactiveError,
    ProactiveSchedule,
    WebhookFormatError,
    WebhookSignatureError,
    WebhookSubscription,
    clear_proactive_registry,
    cron_idempotency_key,
    dispatch_proactive_run,
    list_schedules,
    list_subscriptions,
    on_event,
    proactive,
    register_proactive_schedules,
    route_webhook,
    verify_github_signature,
    verify_stripe_signature,
    webhook_idempotency_key,
)
from app.agents.primitives.tools import (
    DuplicateToolError,
    ToolCallContext,
    ToolCallResult,
    ToolError,
    ToolExecutor,
    ToolNotFoundError,
    ToolPermissionError,
    ToolRegistry,
    ToolSpec,
    ToolValidationError,
    ensure_tools_loaded,
    registry as tool_registry,
    tool,
)

__all__ = [
    "AgentCallResult",
    "AgentCoroFactory",
    "AgentNotFoundError",
    "AgentPermissionError",
    "AgentResult",
    "AgenticCallee",
    "CallChain",
    "CallDepthExceededError",
    "CommunicationError",
    "Critic",
    "CriticLLM",
    "CriticResult",
    "CriticVerdict",
    "CycleDetectedError",
    "DEFAULT_ESCALATION_LIMIT_PER_AGENT",
    "DEFAULT_ESCALATION_WINDOW_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_SIMILARITY_THRESHOLD",
    "DEFAULT_THRESHOLD",
    "DuplicateToolError",
    "EMBEDDING_DIM",
    "EmbeddingError",
    "EscalationLimiter",
    "MemoryRow",
    "MemoryStore",
    "MemoryWrite",
    "ToolCallContext",
    "ToolCallResult",
    "ToolError",
    "ToolExecutor",
    "ToolNotFoundError",
    "ToolPermissionError",
    "ToolRegistry",
    "ToolSpec",
    "PROACTIVE_TASK_NAME",
    "ProactiveDispatchResult",
    "ProactiveError",
    "ProactiveSchedule",
    "ToolValidationError",
    "WebhookFormatError",
    "WebhookSignatureError",
    "WebhookSubscription",
    "call_agent",
    "clear_agentic_registry",
    "clear_proactive_registry",
    "cron_idempotency_key",
    "dispatch_proactive_run",
    "embed_batch",
    "embed_text",
    "ensure_tools_loaded",
    "escalation_limiter",
    "evaluate_with_retry",
    "get_agentic",
    "list_agentic",
    "list_schedules",
    "list_subscriptions",
    "on_event",
    "proactive",
    "register_agentic",
    "register_proactive_schedules",
    "route_webhook",
    "tool",
    "tool_registry",
    "verify_github_signature",
    "verify_stripe_signature",
    "webhook_idempotency_key",
]
