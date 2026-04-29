FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock* ./

# Install dependencies (no project itself yet)
RUN uv sync --frozen --no-install-project

# Copy application code
COPY . .

# Install the project
RUN uv sync --frozen

# PR3/C6.2 — build provenance baked into the image. Pass via:
#   docker build --build-arg BUILD_COMMIT_SHA=$(git rev-parse HEAD) \
#                --build-arg BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ) ...
# Both fall back to "dev" / current-time at runtime if unset (see
# `app/api/v1/routes/health.py::version`). CI will always set them; a
# local `docker compose build` without overrides still works for dev.
ARG BUILD_COMMIT_SHA=dev
ARG BUILD_TIME=unknown
ENV BUILD_COMMIT_SHA=${BUILD_COMMIT_SHA}
ENV BUILD_TIME=${BUILD_TIME}

# Run with gunicorn + uvicorn workers
CMD ["uv", "run", "gunicorn", "app.main:app", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120"]
