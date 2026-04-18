# Design Reference Index

All DESIGN.md files live at repo root or in named subfolders.
Active root DESIGN.md = **Linear** (primary visual language — dark, dense, sidebar).

## Surface → Design Reference Mapping

| Platform Surface | Primary Reference | Secondary Reference | Notes |
|---|---|---|---|
| **Landing / Marketing** | `stripe/DESIGN.md` | `resend/DESIGN.md` | Hero, pricing, feature sections |
| **Student Portal (sidebar + nav)** | `DESIGN.md` (Linear) | `vercel/DESIGN.md` | Density, sidebar, dark mode |
| **Dashboard / KPIs** | `vercel/DESIGN.md` | `posthog/DESIGN.md` | Charts, stats, dark precision |
| **AI Chat Interface** | `claude/DESIGN.md` | `cursor/DESIGN.md` | Message bubbles, streaming, context |
| **Course / Lesson pages** | `notion/DESIGN.md` | `mintlify/DESIGN.md` | Content blocks, readability |
| **Code Editor / Exercises** | `cursor/DESIGN.md` | `DESIGN.md` (Linear) | Editor chrome, AI inline hints |
| **Command Palette (⌘K)** | `raycast/DESIGN.md` | — | Keyboard-first, fuzzy search |
| **Admin / Analytics** | `posthog/DESIGN.md` | `sentry/DESIGN.md` | Heatmaps, error states, data viz |
| **Micro-interactions / Speed** | `superhuman/DESIGN.md` | `framer/DESIGN.md` | Transitions, hover, feel |
| **Auth (login / register)** | `supabase/DESIGN.md` | `vercel/DESIGN.md` | Clean auth flows, dev portal |
| **Progress / Forms / Scheduling** | `cal/DESIGN.md` | — | Forms, scheduling components |
| **Animations** | `framer/DESIGN.md` | `superhuman/DESIGN.md` | Motion, entrance, scroll |

## Priority Tier

**P1 — Must match our surfaces**
- `DESIGN.md` (Linear) — portal, sidebar, density
- `raycast/` — command palette, keyboard-first
- `vercel/` — dashboards, KPI, dark mode precision
- `claude/` — chat UX, message bubbles
- `stripe/` — marketing pages, pricing
- `notion/` — inline editing, content blocks

**P2 — Strong differentiator influence**
- `superhuman/` — micro-interactions, speed feel
- `cursor/` — code editor + AI context
- `posthog/` — data viz, admin, heatmaps
- `framer/` — motion, animation
- `mintlify/` — docs, readability

**P3 — Polish / aesthetic**
- `resend/` — clean product marketing
- `cal/` — scheduling, forms
- `sentry/` — dashboards, error states
- `supabase/` — developer portal, auth flows
