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

# D9 / Pass 3g §B.3.1 — Presidio uses spaCy en_core_web_lg for PII NER.
# Downloaded at build time (not at app startup) for two reasons:
#   1. Boot-time fetches couple cold-start latency to PyPI availability;
#      a Fly machine cold-starting during a PyPI outage would never serve.
#   2. The model is ~750MB; downloading on every machine cold-start would
#      blow the 20s grace_period in fly.toml's health check.
# Resident memory cost: ~750MB per Python process that imports presidio.
# Combined with gunicorn workers=1 (see CMD below) and fly.toml memory_mb=4096,
# this fits comfortably with 25-40% headroom for app + asyncpg + Redis pools.
RUN uv run python -m spacy download en_core_web_lg

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

# Run with gunicorn + a single uvicorn worker.
#
# D9 / Pass 3g safety primitive: each Python worker that imports presidio
# loads spaCy en_core_web_lg (~750MB resident). With workers=4 this would
# need ~3GB of RAM just for safety, against fly.toml's memory_mb=4096
# leaving thin headroom for the rest of the app. We run a SINGLE worker
# instead.
#
# Why a single worker is safe for this workload:
#   - Requests are I/O-bound (LLM HTTP, Postgres asyncpg, Redis). The
#     uvicorn event loop saturates a single shared CPU on async I/O long
#     before it saturates compute. Pass 3i §D documents this baseline.
#   - Fly's auto_start_machines config in fly.toml forks an extra machine
#     when http_service.concurrency soft_limit (200 connections) is hit;
#     horizontal scale beats vertical worker count for this workload.
#   - Memory cost of multi-worker Presidio is real and bites first; Pass
#     3g §H.3 + the fly.toml comment block document the tradeoff.
#
# Do NOT bump workers back to 4 without bumping memory_mb to ~8192 first
# AND verifying the safety primitive's per-process resident footprint
# under load. Future maintainers: read fly.toml [[vm]] block before
# changing this number.
CMD ["uv", "run", "gunicorn", "app.main:app", \
     "--workers", "1", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120"]
