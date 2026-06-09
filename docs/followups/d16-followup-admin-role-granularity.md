# D16 follow-up — admin role granularity (super-admin / support / read-only)

**Status:** Open. Post-launch. Single admin tier suffices for v1.
**Created:** 2026-05-08 (D16/CP2 closure).

## What this is

The platform today has a single admin tier — `users.role == "admin"`.
Every admin endpoint guard is the same `_require_admin` check (CP1
finding 3.4). For v1 launch volume (one or two admins, possibly the
founder + one operator), this is correct: more granularity is more
configuration to get wrong without value to show for it.

This follow-up captures the deliberate v1 simplification so a future
deliverable doesn't accidentally proliferate the admin gate without
the role taxonomy decision being made first.

## When to revisit

When at least two of the following are true:

- More than two people need admin-shaped access.
- Some admin-shaped users need to see students but should not
  refund / cannot delete records (compliance separation of duty).
- A "support agent" persona emerges who handles per-student outreach
  but doesn't need course / content authorship.

## v2 sketch (when triggered)

Likely shape:

- `users.role` becomes a single canonical field still, but the
  values become more specific: `admin`, `support`, `analyst`,
  `content_admin` (enum or controlled string).
- `_require_admin` becomes `_require_role(allowed: set[str])` with
  per-route allowlists.
- Audit (already at `agent_actions.actor_role` per DISC-57) doesn't
  change shape; it just gains more values.

## Out of scope

OAuth/IDP integration (Okta/Azure AD/etc.) is a separate problem from
role granularity and would land first if multi-admin lands first.

## Cross-references

- CP1 audit (`docs/architecture/d16-functional-audit.md`) finding (n)
  closing notes on admin tooling.
- `docs/architecture/d16-pre-flight-admin-surface-audit.md` §3.4 —
  current single-tier authorization model.
