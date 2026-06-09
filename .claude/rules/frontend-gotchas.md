---
paths:
  - "frontend/**"
---

# Frontend Gotchas (hard-won lessons)

Loaded only when working under `frontend/`. Migrated from `docs/lessons.md`.

## Route groups share the URL namespace
In the Next.js App Router, `(group)/page.tsx` resolves to `/` — two route
groups can't both have a root `page.tsx` (they'd collide at `/`). Use a regular
directory (e.g. `admin/`) when routes need distinct URL paths; reserve route
groups for cases that only differ by layout at the same URL.
