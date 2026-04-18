"""Structured logging configuration (P3 3B #159).

Wires `structlog` with `merge_contextvars` so any value bound via
`structlog.contextvars.bind_contextvars(...)` at the start of a request
automatically rides along on every log line until unbound.

Call `configure_logging()` once during FastAPI startup. Safe to call
more than once — the processor chain is idempotent.
"""

from __future__ import annotations

import logging

import structlog


def configure_logging(*, level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
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
