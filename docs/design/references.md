# Design References

**Primary index:** [`docs/design-references/INDEX.md`](../design-references/INDEX.md) — per-surface inspiration mapping with each reference platform's `DESIGN.md` captured in a subfolder.

## What Each Reference Teaches Us

| Reference | What it does well | Applied to |
|---|---|---|
| **Linear** | Dense dark UI, weight 510, whisper borders (`rgba(255,255,255,0.02–0.08)`), Inter OT features `cv01 cv02 cv11 ss03`, tracking -0.04em→-0.01em scale, elevation via shadow | Student portal shell, sidebar, Today screen |
| **Raycast** | Command palette: token-AND fuzzy filter, kbd chips on every row, empty state that teaches | Our `CommandPalette` primitive |
| **Vercel** | Shadow-as-border cards, precise KPI layouts, sidebar with muted nav | Dashboard / KPI surfaces, marketing |
| **Stripe** | Typography hierarchy on landing, pricing tables, feature grids | Public marketing pages |
| **Claude** | Warm terracotta accent, serif-ish feel, message bubble chrome, streaming cursor | AI chat Studio |
| **Cursor** | Inline AI hints in editor, context pills | Studio code editor |
| **PostHog** | Dense data viz, heatmap legends, empty-data messaging | Admin analytics |
| **Sentry** | Error states, stack trace chrome | Admin incidents |
| **Superhuman** | Speed — everything 100–200ms, keyboard-first, status dots | Micro-interaction speed bar |
| **Notion** | Content blocks, readable line length, slash menus | Lesson pages |
| **Mintlify** | Docs readability, sidebar nav, code block defaults | Lesson pages (secondary) |
| **Supabase** | Auth flow clarity | Login / register |
| **Cal** | Form density, scheduling, step indicators | Onboarding, forms |
| **Framer** | Motion language — spring in, ease-out chrome | Motion spec |

## How To Use

1. When starting a surface, consult `INDEX.md` → map row for that surface.
2. Open the primary reference's `DESIGN.md`. Skim the 3 top-of-page rules and the typography/spacing tables.
3. Build against the `component-bar.md` bar with that reference's tone as the tiebreaker.
4. When unsure which reference wins, primary always beats secondary.

## Signoff

P0-0 acceptance (user reviews + signs off on the reference pack) is implicit via the existing `docs/design-references/INDEX.md` + this file + `component-bar.md` + `motion-spec.md`. If the user hasn't reviewed yet, this is the read-in-order:

1. `docs/design-references/INDEX.md` — what beats what.
2. `docs/design/component-bar.md` — the $1000 bar per primitive.
3. `docs/design/motion-spec.md` — duration/ease tokens.
4. `docs/design/component-audit.md` — where every existing component scored on the bar.
