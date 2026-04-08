from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

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
    from app.api.v1.routes.auth import router as auth_router
    from app.api.v1.routes.courses import router as courses_router
    from app.api.v1.routes.exercises import router as exercises_router
    from app.api.v1.routes.lessons import router as lessons_router
    from app.api.v1.routes.students import router as students_router
    from app.api.v1.routes.webhooks import router as webhooks_router

    api_routers = [
        auth_router,
        courses_router,
        lessons_router,
        exercises_router,
        students_router,
        webhooks_router,
    ]
    for r in api_routers:
        app.include_router(r, prefix="/api/v1")

    return app


app = create_app()
