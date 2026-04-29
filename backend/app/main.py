from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.exception_handler import unhandled_exception_handler
from app.core.logging import configure_logging
from app.core.rate_limit import limiter
from app.core.request_id import RequestIDMiddleware

configure_logging(level="DEBUG" if settings.debug else "INFO")

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("app.startup", environment=settings.environment)
    yield
    log.info("app.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )

    # Request ID — must be outermost so every log line gets the correlation ID
    app.add_middleware(RequestIDMiddleware)

    # Rate limiting
    app.state.limiter = limiter

    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        # P2-7 — compute Retry-After + X-RateLimit-Remaining so the client can
        # drive a live countdown banner instead of guessing a fallback. slowapi
        # stores the matching RateLimitItem on `request.state.view_rate_limit`
        # once the pre-flight check runs; `get_window_stats` returns
        # (reset_epoch, remaining).
        import time as _time

        retry_after_seconds = 60
        remaining = 0
        limit_amount: int | None = None
        view_limit = getattr(request.state, "view_rate_limit", None)
        if view_limit is not None:
            try:
                item, key_parts = view_limit
                reset_epoch, rem = limiter.limiter.get_window_stats(item, *key_parts)
                retry_after_seconds = max(1, int(reset_epoch - _time.time()))
                remaining = max(0, int(rem))
                limit_amount = item.amount
            except Exception:
                pass

        headers = {
            "Retry-After": str(retry_after_seconds),
            "X-RateLimit-Remaining": str(remaining),
        }
        if limit_amount is not None:
            headers["X-RateLimit-Limit"] = str(limit_amount)

        return JSONResponse(
            status_code=429,
            content={
                "detail": f"Rate limit exceeded: {exc.detail}",
                "retry_after_seconds": retry_after_seconds,
            },
            headers=headers,
        )

    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    # PR2/B4.1 — global handler. Catches anything that escaped the route
    # and turns it into a stable {"error": {...}} JSON shape with the
    # request_id surfaced. Registered AFTER slowapi so RateLimitExceeded
    # keeps its dedicated handler, and registered against the bare
    # `Exception` type so HTTPException keeps FastAPI's machinery upstream
    # (we only catch what FastAPI didn't).
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # CORS — only allow configured origins.
    # P2-7 — expose rate-limit headers so the browser JS can read them
    # from cross-origin responses; without this, `res.headers.get(
    # "X-RateLimit-Remaining")` returns null in the browser even though
    # the header is on the wire.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "Retry-After",
        ],
    )

    # Health (root level)
    from app.api.v1.routes.health import router as health_router

    app.include_router(health_router)

    # API v1
    from app.api.v1.routes.admin import router as admin_router
    from app.api.v1.routes.agents import router as agents_router
    from app.api.v1.routes.application_kit import router as application_kit_router
    from app.api.v1.routes.auth import router as auth_router
    from app.api.v1.routes.billing import router as billing_router
    from app.api.v1.routes.catalog import router as catalog_router
    from app.api.v1.routes.courses import router as courses_router
    from app.api.v1.routes.demo import router as demo_router
    from app.api.v1.routes.diagnostic import router as diagnostic_router
    from app.api.v1.routes.execute import router as execute_router
    from app.api.v1.routes.exercises import router as exercises_router
    from app.api.v1.routes.format import router as format_router
    from app.api.v1.routes.goals import router as goals_router
    from app.api.v1.routes.interview import router as interview_router
    from app.api.v1.routes.lessons import router as lessons_router
    from app.api.v1.routes.misconceptions import router as misconceptions_router
    from app.api.v1.routes.notifications import router as notifications_router
    from app.api.v1.routes.oauth import router as oauth_router
    from app.api.v1.routes.payments_v2 import router as payments_v2_router
    from app.api.v1.routes.payments_webhook import (
        router as payments_webhook_router,
    )
    from app.api.v1.routes.portfolio_autopsy import router as portfolio_autopsy_router
    from app.api.v1.routes.confidence import router as confidence_router
    from app.api.v1.routes.preferences import router as preferences_router
    from app.api.v1.routes.receipts import router as receipts_router
    from app.api.v1.routes.reflections import router as reflections_router
    from app.api.v1.routes.senior_review import router as senior_review_router
    from app.api.v1.routes.skill_path import router as skill_path_router
    from app.api.v1.routes.skills import router as skills_router
    from app.api.v1.routes.srs import router as srs_router
    from app.api.v1.routes.career import router as career_router
    from app.api.v1.routes.chat import router as chat_router
    from app.api.v1.routes.clarification import router as clarification_router
    from app.api.v1.routes.notebook import router as notebook_router
    from app.api.v1.routes.stream import (
        chat_stream_router,
        router as stream_router,
    )
    from app.api.v1.routes.students import router as students_router
    from app.api.v1.routes.teach_back import router as teach_back_router
    from app.api.v1.routes.today import router as today_router
    from app.api.v1.routes.path_summary import router as path_summary_router
    from app.api.v1.routes.promotion_summary import router as promotion_summary_router
    from app.api.v1.routes.webhooks import router as webhooks_router
    from app.api.v1.routes.feedback import router as feedback_router
    from app.api.v1.routes.mock_interview import router as mock_interview_router
    from app.api.v1.routes.tailored_resume import router as tailored_resume_router
    from app.api.v1.routes.jd_decoder import router as jd_decoder_router
    from app.api.v1.routes.readiness import (
        overview_router as readiness_overview_router,
        router as readiness_router,
    )
    from app.api.v1.routes.readiness_events import (
        router as readiness_events_router,
    )
    from app.api.v1.routes.resources import router as resources_router
    from app.api.v1.routes.practice import router as practice_router

    api_routers = [
        auth_router,
        admin_router,
        courses_router,
        lessons_router,
        exercises_router,
        students_router,
        webhooks_router,
        agents_router,
        stream_router,
        chat_stream_router,
        demo_router,
        billing_router,
        catalog_router,
        oauth_router,
        payments_v2_router,
        payments_webhook_router,
        goals_router,
        notifications_router,
        preferences_router,
        confidence_router,
        receipts_router,
        portfolio_autopsy_router,
        reflections_router,
        senior_review_router,
        skills_router,
        skill_path_router,
        srs_router,
        diagnostic_router,
        execute_router,
        format_router,
        misconceptions_router,
        interview_router,
        teach_back_router,
        today_router,
        path_summary_router,
        promotion_summary_router,
        feedback_router,
        career_router,
        chat_router,
        clarification_router,
        notebook_router,
        tailored_resume_router,
        mock_interview_router,
        jd_decoder_router,
        readiness_router,
        readiness_overview_router,
        readiness_events_router,
        application_kit_router,
        resources_router,
        practice_router,
    ]
    for r in api_routers:
        app.include_router(r, prefix="/api/v1")

    return app


app = create_app()
