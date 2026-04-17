from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.rate_limit import limiter

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

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    # CORS — only allow configured origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health (root level)
    from app.api.v1.routes.health import router as health_router

    app.include_router(health_router)

    # API v1
    from app.api.v1.routes.admin import router as admin_router
    from app.api.v1.routes.agents import router as agents_router
    from app.api.v1.routes.auth import router as auth_router
    from app.api.v1.routes.billing import router as billing_router
    from app.api.v1.routes.courses import router as courses_router
    from app.api.v1.routes.demo import router as demo_router
    from app.api.v1.routes.exercises import router as exercises_router
    from app.api.v1.routes.lessons import router as lessons_router
    from app.api.v1.routes.oauth import router as oauth_router
    from app.api.v1.routes.stream import router as stream_router
    from app.api.v1.routes.students import router as students_router
    from app.api.v1.routes.webhooks import router as webhooks_router

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
        demo_router,
        billing_router,
        oauth_router,
    ]
    for r in api_routers:
        app.include_router(r, prefix="/api/v1")

    return app


app = create_app()
