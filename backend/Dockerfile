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

# PR3/D5.1 — drop to a non-root user before CMD. We can't chown the
# entire /app earlier because `uv sync` writes to /app/.venv with
# absolute path interpolations baked into the activate scripts; the
# safe sequence is: do all the install work as root, THEN create the
# user and reassign ownership in one shot. The Fly platform doesn't
# require root for any port binding (we listen on 8000 which is
# unprivileged), and the production database connection runs through
# asyncpg over TCP — no host-mounted sockets to worry about. Verify
# with: `docker run --rm <image> whoami` → "appuser".
#
# Why a real /home/appuser instead of --no-create-home: `uv run`
# initializes a cache under $HOME/.cache/uv on first invocation; with
# no writable home it dies with EACCES at boot time. Giving the user
# a 0700 home keeps the attack surface tight (no other process can
# poke at the cache) while letting uv do its thing.
RUN groupadd --system --gid 1001 appuser \
 && useradd  --system --uid 1001 --gid 1001 -m -d /home/appuser --shell /sbin/nologin appuser \
 && chown -R appuser:appuser /app /home/appuser \
 && chmod 700 /home/appuser

USER appuser

# Run with gunicorn + uvicorn workers
CMD ["uv", "run", "gunicorn", "app.main:app", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120"]
