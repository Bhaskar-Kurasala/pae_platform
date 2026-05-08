# pnpm 11 migration (frontend Dockerfile)

**Status:** Open. Frontend team owned. Mitigated short-term via
pinning pnpm to 10.5.0; long-term migration to pnpm 11 deferred.
**Origin:** Surfaced 2026-05-08 during D18 Phase A retrofit
verification (Path A pre-CP1). Any `docker compose build frontend`
invocation has been silently broken since pnpm 11 became the
corepack default; the previous-running frontend container was
built with an older pnpm and ran fine, masking the rebuild break.

## What this is

`frontend/Dockerfile` previously called
`corepack prepare pnpm@latest --activate`, which resolves to the
latest pnpm available via corepack at image-build time. pnpm 11.x
(released earlier in 2026) changed the default behavior of
`pnpm install --frozen-lockfile`:

  * **pnpm 10 and earlier:** treated ignored build scripts
    (packages whose postinstall hooks pnpm refuses to auto-run for
    security) as a warning. Install completed with exit 0.
  * **pnpm 11:** treats ignored build scripts as a hard error in
    `--frozen-lockfile` mode. Install exits non-zero with
    `[ERR_PNPM_IGNORED_BUILDS]` and points the operator at
    `pnpm approve-builds` for explicit allow-listing.

The project has six packages with ignored install scripts:

| Package          | Role                                         |
|------------------|----------------------------------------------|
| sharp            | Image processing (Next.js Image optimization) |
| @sentry/cli      | Sentry source-map upload (production builds)  |
| msw              | Mock Service Worker (test setup)              |
| core-js          | Polyfills (Babel runtime)                    |
| protobufjs       | Protobuf runtime (transitive dep)             |
| unrs-resolver    | Module resolver (transitive dep)              |

Until pnpm 11 became the corepack default, this was a non-issue —
pnpm 10 silently skipped the install scripts and the resulting
images ran fine (the runtime functionality of these packages is
mostly available without their install-time setup). pnpm 11's
stricter policy now blocks `pnpm install` entirely.

## Short-term mitigation (shipped)

`frontend/Dockerfile` pins pnpm explicitly:

```dockerfile
RUN corepack enable && corepack prepare pnpm@10.5.0 --activate
```

This restores rebuild capability without changing project behavior.
Both stages of the multi-stage build (`deps` and `builder`) use the
same pin so they install identically.

## Long-term migration paths

Three options for the frontend team to consider when migrating to
pnpm 11:

**Option α — `pnpm approve-builds` whitelist.** Run
`pnpm approve-builds` interactively against the local checkout, pick
which of the six packages get to run install scripts, and commit
the resulting whitelist (likely lands in `package.json` under
`pnpm.onlyBuiltDependencies` or similar). pnpm 11 then accepts the
explicit allow-list and `--frozen-lockfile` exits 0.

  * Pros: most aligned with pnpm's 11.x security model.
  * Cons: requires evaluating which scripts are actually safe to
    auto-run (sharp + sentry-cli are clearest yes; msw / core-js /
    transitive deps need investigation).

**Option β — `--ignore-scripts` flag.** Change the install command
to `pnpm install --frozen-lockfile --ignore-scripts`. Skips ALL
install scripts.

  * Pros: simplest to land.
  * Cons: skips legitimate setup work (sharp's native binary
    fetch, sentry-cli's binary download). May cause runtime
    breakage if any package actually needs its postinstall.

**Option γ — Stay on pnpm 10 indefinitely.** Pin permanently;
treat pnpm 11 migration as out-of-scope.

  * Pros: zero migration risk.
  * Cons: bug fixes + perf improvements in pnpm 11+ unavailable;
    eventual forced migration when 10.x EOLs.

**Recommendation:** Option α for the long-term fix; Option γ is
the current state until that work happens.

## Cross-references

- `frontend/Dockerfile` lines 6, 15 — the pinned `corepack prepare`
  invocations. Both must stay in sync if the version is bumped.
- D18 Phase A retrofit commit (immediately follows this doc) —
  the retrofit work that surfaced this rebuild break.
- pnpm 11 release notes: <https://pnpm.io/blog> — search for the
  `--frozen-lockfile` policy change announcement.
