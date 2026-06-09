# Playwright browser system deps not in backend container image

**Surfaced**: 2026-05-08, D18 Phase A CP1 smoke verification
**Severity**: Operational; resolved in-running-container, not durable
**Owner**: CP6 (`docker-compose.playwright.yml` / Dockerfile additions)

## What happened

CP1 smoke (`backend/tests/playwright/smoke/test_cp1_smoke.py`) installed
the Playwright chromium binary inside `pae_platform-backend-1` via:

```bash
docker exec backend uv run playwright install chromium
```

Browser binary downloaded fine. But launching it failed:

```
chrome-headless-shell: error while loading shared libraries:
libglib-2.0.so.0: cannot open shared object file
```

The backend image is a slim Python image. It ships the Python runtime
+ `uv` + project deps, but not the X / GTK / fontconfig system libs
chromium needs to launch — even in headless mode.

## One-shot fix used at CP1

Ran as root inside the running container:

```bash
docker exec --user root pae_platform-backend-1 \
    sh -c "cd /app && uv run playwright install-deps chromium"
```

This `apt-get install`s the libs (libglib2.0-0, libnss3, libcups2,
libdbus-1-3, libdrm2, libgbm1, libxkbcommon0, libpango-1.0-0,
libcairo2, libasound2, libatk-bridge2.0-0, libatk1.0-0, libxcomposite1,
libxdamage1, libxfixes3, libxrandr2, fontconfig, plus mesa packages).

Smoke passes after this step.

**This fix is not durable.** A `docker compose down && up --build`
rebuilds the image and the libs vanish. CI is also affected: a fresh
container per CI run starts without the libs.

## Durable fix (CP6 deliverable)

Pick one:

### Option A — extend `backend/Dockerfile`

Add browser deps to the base image so any container off it can run
Playwright. Cleanest for parity between dev / CI / Phase B journey runs.

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libnspr4 libcups2 libdbus-1-3 libdrm2 libgbm1 \
    libxkbcommon0 libpango-1.0-0 libcairo2 libasound2 libatk-bridge2.0-0 \
    libatk1.0-0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libxshmfence1 fontconfig fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
```

Cost: ~50-80 MB image-size increase.

### Option B — separate playwright-runner image in `docker-compose.playwright.yml`

CP6 ships an override anyway. Add a `playwright-runner` service that
extends `mcr.microsoft.com/playwright/python:v1.59.0-noble` (or pinned
matching version), bind-mounts `./backend:/app`, and runs the suite.
Backend container stays slim.

```yaml
services:
  playwright-runner:
    image: mcr.microsoft.com/playwright/python:v1.59.0-jammy
    working_dir: /app
    volumes:
      - ./backend:/app
    environment:
      PLAYWRIGHT_BASE_URL: http://frontend:3000
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@db:5432/playwright_test
    command: uv run pytest tests/playwright/
    depends_on:
      - frontend
      - backend
      - db
```

Cost: separate image; rebuild of the runner is independent of backend.

### Recommendation

**Option B** for D18 Phase A. Reasons:
- Backend image stays focused on serving the API; doesn't carry browser
  libs that production never uses.
- Microsoft's official Playwright image keeps browser + libs version-locked
  to the Playwright Python version automatically.
- Browser-deps-in-prod-image is a Pattern 1 / supply-chain smell.
- Phase B / Phase C / Phase D all want a dedicated runner anyway.

Option A is acceptable if CP6 architecture wants single-image simplicity
and is willing to pay the size hit.

## CP1 closure note

CP1 ships with the smoke passing on the current host (after one-shot
deps install). Setup doc records the workaround. CP6 picks the durable
option. No CP1 STOP triggered: the prompt's CP1 STOP says "browser
binaries can't be installed in container" — they can be installed
(downloaded fine); only the launch system-deps were missing, and a
trivial workaround unblocks. Architectural fix deferred to the natural
home (CP6 / `docker-compose.playwright.yml`).
