#!/usr/bin/env bash
# D18 Phase A CP6 — build & serve the Playwright stack.
#
# Idempotent end-to-end orchestrator for running the Playwright suite
# locally OR from CI. Three responsibilities:
#
#   1. Ensure playwright_test_template exists (one-time create per host).
#   2. Spin up backend + frontend with the playwright overlay so the
#      backend reads from playwright_test, not the dev `platform` DB.
#   3. Wait for both health checks before yielding control to the caller.
#
# After this script returns 0, the stack is ready for:
#   * docker compose -f docker-compose.yml \
#       -f docker-compose.playwright.yml \
#       --profile playwright run --rm playwright-runner pytest <args>
#   * OR a host-side pytest invocation:
#       PLAYWRIGHT_BASE_URL=http://localhost:3002 \
#       docker compose exec backend uv run pytest tests/playwright/
#
# Usage:
#   ./backend/tests/playwright/scripts/build_and_serve.sh
#   ./backend/tests/playwright/scripts/build_and_serve.sh --rebuild   # force frontend rebuild
#   ./backend/tests/playwright/scripts/build_and_serve.sh --reset-db  # drop + recreate template
#
# Frontend rebuild ritual (per frontend/CLAUDE.md): the frontend
# container runs `node server.js` from a Next.js standalone build,
# NOT `pnpm dev`. So source changes don't propagate via HMR — the
# image must be rebuilt before any browser-test pass that exercises
# the updated frontend code. --rebuild forces this; CI always passes
# --rebuild because clean checkouts have no prior build cache.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
COMPOSE_FILES=(-f "${PROJECT_ROOT}/docker-compose.yml" -f "${PROJECT_ROOT}/docker-compose.playwright.yml")
BACKEND_HEALTH_URL="${BACKEND_HEALTH_URL:-http://localhost:8080/health}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3002}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-90}"

REBUILD_FRONTEND=0
RESET_DB=0
for arg in "$@"; do
    case "${arg}" in
        --rebuild) REBUILD_FRONTEND=1 ;;
        --reset-db) RESET_DB=1 ;;
        --help|-h)
            sed -n '2,/^set -euo pipefail$/p' "${BASH_SOURCE[0]}"
            exit 0 ;;
        *) echo "[build_and_serve] unknown flag: ${arg}" >&2; exit 2 ;;
    esac
done

cd "${PROJECT_ROOT}"

log() { echo "[build_and_serve] $*" >&2; }

# ── Step 1: ensure docker is up + db service running ────────────────
log "step 1/4: ensure docker stack is up (db, backend, frontend, nginx)"
docker compose "${COMPOSE_FILES[@]}" up -d db nginx >&2
# Wait for db to accept connections — pg_isready via the db service.
for i in $(seq 1 30); do
    if docker compose "${COMPOSE_FILES[@]}" exec -T db pg_isready -U postgres >/dev/null 2>&1; then
        log "  db ready"
        break
    fi
    sleep 1
    [[ "${i}" -eq 30 ]] && { log "FATAL: db not ready after 30s"; exit 1; }
done

# ── Step 2: ensure playwright_test_template exists ──────────────────
log "step 2/4: ensure playwright_test_template database"
template_exists=$(docker compose "${COMPOSE_FILES[@]}" exec -T db \
    psql -U postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='playwright_test_template'" 2>/dev/null || true)

if [[ "${RESET_DB}" -eq 1 ]] || [[ "${template_exists}" != "1" ]]; then
    log "  building playwright_test_template (this takes ~6-7s)"
    # Bring backend up first so create_template.py can run inside it
    # (alembic + asyncpg + the project venv all live there).
    docker compose "${COMPOSE_FILES[@]}" up -d backend >&2
    # Backend may take a few seconds to be exec-able after `up -d`.
    for i in $(seq 1 30); do
        if docker compose "${COMPOSE_FILES[@]}" exec -T backend true >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    docker compose "${COMPOSE_FILES[@]}" exec -T backend sh -c \
        "cd /app && uv run python /app/tests/playwright/db/create_template.py" >&2
else
    log "  template already exists; use --reset-db to force rebuild"
fi

# ── Step 3: bring up backend + frontend (rebuild if requested) ──────
log "step 3/4: bring up backend + frontend"
if [[ "${REBUILD_FRONTEND}" -eq 1 ]]; then
    log "  rebuilding frontend image (--rebuild flag set)"
    docker compose "${COMPOSE_FILES[@]}" build frontend >&2
fi
docker compose "${COMPOSE_FILES[@]}" up -d backend frontend nginx >&2

# ── Step 4: wait for health checks ──────────────────────────────────
log "step 4/4: wait for backend + frontend health"

wait_for_url() {
    local label="$1" url="$2" timeout="$3"
    for i in $(seq 1 "${timeout}"); do
        if curl -fsS -o /dev/null -m 2 "${url}"; then
            log "  ${label} healthy after ${i}s"
            return 0
        fi
        sleep 1
    done
    log "FATAL: ${label} did not become healthy at ${url} within ${timeout}s"
    docker compose "${COMPOSE_FILES[@]}" logs --tail=50 backend frontend nginx >&2 || true
    return 1
}

wait_for_url "backend" "${BACKEND_HEALTH_URL}" "${HEALTH_TIMEOUT_SECONDS}"
wait_for_url "frontend" "${FRONTEND_URL}" "${HEALTH_TIMEOUT_SECONDS}"

log "stack ready — backend reads from playwright_test"
log "  backend (via nginx): ${BACKEND_HEALTH_URL}"
log "  frontend:            ${FRONTEND_URL}"
log ""
log "next steps:"
log "  # In-container test run (preferred for CI):"
log "  docker compose ${COMPOSE_FILES[*]} \\"
log "    --profile playwright run --rm playwright-runner \\"
log "    pytest tests/playwright/smoke/test_cp6_full_loop.py -v"
log ""
log "  # Host-side test run:"
log "  PLAYWRIGHT_BASE_URL=${FRONTEND_URL} \\"
log "    docker compose exec backend uv run pytest tests/playwright/"
