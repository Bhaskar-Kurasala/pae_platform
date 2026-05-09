"""Structured logging configuration (P3 3B #159; extended D19.1 CP1).

Wires `structlog` with `merge_contextvars` so any value bound via
`structlog.contextvars.bind_contextvars(...)` at the start of a request
automatically rides along on every log line until unbound.

D19.1 CP1.4 extension — adds the sampling processor in the chain so
INFO / DEBUG lines can be probabilistically discarded per the D-E
rules. ERROR / WARNING always pass. The processor sits *after*
``merge_contextvars`` so the ``trace_id`` is in scope when sampling
makes its deterministic-per-trace decision.

Call `configure_logging()` once during FastAPI startup. Safe to call
more than once — the processor chain is idempotent.
"""

from __future__ import annotations

import logging

import structlog

from app.core.log_sampling import sampling_processor


def configure_logging(*, level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            # 1. Inject contextvars (request_id, trace_id, user_id,
            #    agent_id, …) bound by RequestIDMiddleware,
            #    get_current_user, BaseAgent.run, etc.
            structlog.contextvars.merge_contextvars,
            # 2. Stamp the level onto the event dict so downstream
            #    processors and the sampling decision see it.
            structlog.processors.add_log_level,
            # 3. Sampling — drops INFO/DEBUG per D-E. Deterministic
            #    per trace_id when bound; random otherwise.
            sampling_processor,
            # 4. Timestamp & exc info & JSON.
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
