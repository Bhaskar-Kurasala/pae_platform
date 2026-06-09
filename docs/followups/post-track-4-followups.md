# Follow-ups: post-Track-4 audit findings

**Owner:** _unassigned — items routed at next planning pass._
**Status:** open (none are launch blockers)
**Created:** 2026-05-02
**Source:** Track 4 audit sign-off
  (`docs/audits/naming-audit.md` + `docs/audits/dead-code-audit.md`)

Three concrete actions surfaced by the Track 4 audits that need
human attention but didn't warrant code changes inside the audit
pass itself. Listed in increasing order of irreversibility.

---

## 1. Verify the alembic 0050 gap is cosmetic, not chain-breaking

**Cost:** 5 seconds.
**Risk if skipped:** the next migration crashes with "can't find
revision 0050" if the chain is actually broken.

The migration filenames jump from `0049_student_risk_signals.py` to
`0051_outreach_log.py`. Filename numbering is decorative — alembic
links migrations by `revision` / `down_revision` strings inside the
files. Verify the chain points 0049 → 0051 directly:

```bash
grep -E "^revision|^down_revision" \
  backend/alembic/versions/0049_student_risk_signals.py \
  backend/alembic/versions/0051_outreach_log.py
```

If `0051.down_revision == 0049.revision`, the gap is cosmetic — note
it here as resolved, no further action.

If the gap is a broken chain, file a fresh follow-up for the chain
repair (likely a no-op migration with the right `down_revision`).

**Action when done:** edit this file with the result, don't delete
(audit-trail preference per `docs/followups/README.md`).

---

## 2. Read both `main.py` files and document why both exist

**Cost:** 30 seconds.
**Risk if skipped:** low. Smell, not bug — but the smell persists
forever if nobody investigates.

Two `main.py` files at different altitudes:

- `backend/main.py` (at backend root)
- `backend/app/main.py` (the FastAPI app factory — load-bearing,
  imports all routers, registers middleware)

Possibilities:

- `backend/main.py` is a thin shim that re-exports `app.main:app`
  for `uvicorn main:app` style invocations from the backend root —
  **legitimate.**
- `backend/main.py` is a CLI entry point — **legitimate.**
- `backend/main.py` is vestigial from the pre-`app/` layout —
  **dead code, candidate for deletion.**

**Action:** read both. Update `docs/audits/dead-code-audit.md` §3.3
with the answer:
  - If legitimate, document why both exist (one-liner).
  - If dead, move the entry from SUSPICIOUS to PROBABLE and queue
    for the next deletion batch.

---

## 3. Mark the legacy `/interview` route `@deprecated` (post-launch)

**Cost:** ~5 minutes of code + a 2-week observation window.
**Risk if skipped:** none short-term — works as-is. Long-term, dead
weight in the route table that the team's existing deprecation
pipeline can't see.

`backend/app/api/v1/routes/interview.py` is mounted at
`/api/v1/interview` and imports `interview_service.py`. The team
has 38 other handlers using `@deprecated(sunset="2026-07-01", reason=...)`
which:
  • emit `Deprecation: true` + `Sunset: <date>` headers (RFC 8594)
  • emit `log.warning("deprecated_endpoint_called", ...)` on every call

The legacy `/interview` surface has no marker — so it's invisible to
the team's deletion pipeline.

**Why this is a post-launch task, not a launch-blocker:**

Marking @deprecated *now*, before checking whether the v8 frontend
calls it, could surface deprecation warnings in active user sessions.
Better to do this as part of the broader cleanup batch:

1. Add `@deprecated(sunset="2026-08-01", reason="superseded by Mock
   Interview v3 at /api/v1/mock")` to each handler in
   `backend/app/api/v1/routes/interview.py`.
2. Ship and observe `deprecated_endpoint_called` log warnings for ~2
   weeks.
3. If zero or near-zero callers: delete the route file, the service
   file (`backend/app/services/interview_service.py`), and the test
   (`backend/tests/test_services/test_interview_service.py`) in one
   commit.
4. If non-zero callers: investigate which client is hitting the
   legacy surface and migrate them, then return to step 3.

Cross-reference: `docs/audits/naming-audit.md` §2.3 and
`docs/audits/dead-code-audit.md` §2.2.

---

## Done when

- [ ] §1 alembic chain verified — result noted above
- [ ] §2 both `main.py` files read — result noted in dead-code audit
- [ ] §3 legacy `/interview` marked `@deprecated`, observed,
      then deleted (or kept with a documented reason)

## References

- Track 4 commit: `4e6595e` (`docs(audits): track-4 — naming +
  dead-code inventories`)
- `docs/audits/naming-audit.md`
- `docs/audits/dead-code-audit.md`
