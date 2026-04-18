# UI Component Audit (P0-0b)

**Date:** 2026-04-17
**Baseline primitives:** `@base-ui/react` v1.3 (Radix-quality) + `class-variance-authority` + Tailwind CSS 4.
**Motion:** `framer-motion` v12 (present but underused outside `motion-fade.tsx`).
**Toast:** `sonner` v2 (present but not wired to a shared `toast()` helper).
**Icons:** `lucide-react`.

**Design bar references per surface:** see [docs/design-references/INDEX.md](../design-references/INDEX.md). Portal surfaces target **Linear** (dark, dense, weight 510, whisper borders). Chat surfaces target **Claude** (warm, serif, terracotta). Admin surfaces target **Vercel + PostHog** (shadow-as-border, precise data viz).

---

## Audit Legend

| Column | Meaning |
|---|---|
| **Score** | Current state vs the $1000 bar. 1 = basic/broken, 5 = production-ready for our target surfaces. |
| **Priority** | `P0.5` = rebuild in Phase 0.5. `P1` = iterate during feature work. `P2` = later polish. |
| **Ticket** | Phase 0.5 ticket that covers the upgrade. |

---

## 1. Primitives (`frontend/src/components/ui/`)

### 1.1 `button.tsx`

| Aspect | Current | Target (Linear portal / Vercel public) | Gap |
|---|---|---|---|
| Variants | default, outline, secondary, ghost, destructive, link | All present | ✅ |
| Sizes | xs, sm, default, lg, icon×3 | Match | ✅ |
| Idle bg | `bg-primary` (teal) | Linear: near-transparent `rgba(255,255,255,0.02)` for secondary, brand indigo for primary | ⚠️ teal too warm for dark portal |
| Press | `active:translate-y-px` | Scale(0.98) or translate (current is acceptable) | ✅ |
| Focus ring | `ring-ring/50 ring-3` | Blue accessibility ring like Vercel | ✅ |
| **Loading state** | **None** | Inline spinner + disabled | ❌ **missing** |
| **Icon slots** | data-attr based | Left/right/only — works | ✅ |
| Font weight | 400 via `font-medium` | Linear uses 510 | ⚠️ |
| Letter-spacing | default | Linear: -0.165px at 14-15px labels | ⚠️ |

**Score: 3/5.** Missing loading state is the biggest functional gap. Typography tokens off from Linear bar.
**Priority: P0.5** → ticket **P0.5-01 Button system**.
**Action:** Add `loading` prop (spinner + `aria-busy`), `success` transient state, refine typography tokens to Linear spec (weight 510 for UI labels, negative tracking).

---

### 1.2 `input.tsx`

| Aspect | Current | Target | Gap |
|---|---|---|---|
| Height | h-8 | OK for dense portal | ✅ |
| Border | 1px border-input | Linear whisper `rgba(255,255,255,0.08)` in dark | ⚠️ token-dependent |
| Focus | `ring-3 ring-ring/50` | Vercel blue outline | ✅ |
| Disabled | Opacity + cursor | OK | ✅ |
| **Floating label** | **None** | Claude-style label animation on focus | ❌ |
| **Inline validation** | aria-invalid only | Success/error icons inline | ❌ |
| **Clear button** | **None** | For search inputs | ❌ |
| **Autosize textarea** | No textarea component | Chat input needs autosize | ❌ |
| Character counter | None | For onboarding success textarea | ❌ |

**Score: 2/5.** Functional but primitive. No textarea component at all.
**Priority: P0.5** → ticket **P0.5-02 Input & Textarea**.
**Action:** Add dedicated `textarea.tsx` with autosize, character counter, label animation, validation icons. Add clear button for search variant.

---

### 1.3 `select.tsx`

| Aspect | Current | Target | Gap |
|---|---|---|---|
| Base | `@base-ui/react` select | Good foundation | ✅ |
| Keyboard nav | Yes (via Base UI) | ✅ | ✅ |
| **Search/filter** | No | Raycast-style fuzzy filter | ❌ |
| **Async options** | No | Loading skeleton in dropdown | ❌ |
| **Multi-select chips** | No | For skill-tag selection | ❌ |
| Virtualization | No | Needed when >100 options | ❌ |

**Score: 2/5.** Basic only.
**Priority: P0.5** → split into `select.tsx` (keep) + new `combobox.tsx` for searchable/async.

---

### 1.4 `dialog.tsx` / `sheet.tsx`

| Aspect | Current | Target | Gap |
|---|---|---|---|
| Enter/exit anim | `fade-in zoom-in-95` via tw-anim utilities | Linear uses spring; current is OK | ⚠️ |
| Focus trap | Base UI handles | ✅ | ✅ |
| Esc to close | Base UI | ✅ | ✅ |
| Backdrop | `bg-black/10 backdrop-blur-xs` | Linear `rgba(0,0,0,0.85)` is darker | ⚠️ |
| **Mobile bottom-sheet** | Sheet exists separately but no responsive switch | Auto-switch dialog→sheet at sm breakpoint | ❌ |
| **Stacking** | Not tested | Multi-dialog case | ⚠️ |

**Score: 3/5.**
**Priority: P0.5** → ticket **P0.5-04**. Add `<ResponsiveDialog>` wrapper that picks dialog vs sheet based on viewport.

---

### 1.5 `tabs.tsx`

| Aspect | Current | Target | Gap |
|---|---|---|---|
| Variants | default, line | Good | ✅ |
| Active indicator | Pseudo-element bar | Framer layoutId shared element for smooth slide | ⚠️ better with motion |
| Keyboard nav | Base UI | ✅ | ✅ |
| Scrollable overflow | No | Needed for many tabs | ❌ |
| Pill variant | No | Segmented control style | ❌ |

**Score: 3/5.**
**Priority: P0.5** → ticket **P0.5-08**. Add framer `layoutId` for the active pill slide. Add scrollable container when overflow.

---

### 1.6 `card.tsx`

| Aspect | Current | Target | Gap |
|---|---|---|---|
| Shell | rounded-xl ring-1 | Linear: rgba(255,255,255,0.02) bg + 0.08 border | ⚠️ tokens |
| Header/Footer/Action/Content subparts | Yes | ✅ | ✅ |
| **Hover lift** | None | `translateY(-2px)` + shadow on interactive variant | ❌ |
| **Skeleton variant** | None | Matches real layout | ❌ |
| **Gradient border** | None | For featured CTA cards | ❌ (optional) |
| **Interactive variant** | None | `<Card interactive>` that's a button semantically | ❌ |

**Score: 3/5.**
**Priority: P0.5** → ticket **P0.5-09**.

---

### 1.7 `badge.tsx`

| Aspect | Current | Target | Gap |
|---|---|---|---|
| Variants | default, secondary, destructive, outline, ghost, link | Broad | ✅ |
| Size | h-5 fixed | Add xs/sm/md | ⚠️ |
| Linear pill | 9999px radius | Current is `rounded-4xl` — close | ✅ |
| Status dot variant | No | `<Badge dot color="green">Active</Badge>` | ❌ |

**Score: 3/5.** Add status-dot variant as part of P0.5-09.

---

### 1.8 `avatar.tsx`

| Aspect | Current | Target | Gap |
|---|---|---|---|
| Image + fallback | Yes | ✅ | ✅ |
| Size scale | sm/default/lg | Add xl for hero | ⚠️ |
| Fallback initials | Passed as children | Add helper that generates from name | ⚠️ |
| **Deterministic color** | No | Hash name → color from palette | ❌ |
| Presence indicator | `AvatarBadge` exists | ✅ | ✅ |
| Group stacking | Yes | ✅ | ✅ |

**Score: 3/5.**
**Priority: P0.5** → ticket **P0.5-12**. Add `<Avatar name="Bhaskar" />` auto-initials + deterministic color.

---

### 1.9 `dropdown-menu.tsx`

**Score: 4/5.** Comprehensive Base UI binding — checkbox/radio items, sub-menus, separators, shortcut slot. Works well.
**Priority: P1** (iterate during feature work). No dedicated ticket unless we hit a gap.

---

### 1.10 `label.tsx`, `separator.tsx`

**Score: 3/5.** Minimal, functional. No rebuild needed.
**Priority: P2.**

---

### 1.11 `sonner.tsx` (toast)

| Aspect | Current | Target | Gap |
|---|---|---|---|
| Setup | Sonner Toaster mounted | ✅ (assumed — verify in layout) | ⚠️ |
| **Wrapped `toast()` helper** | No project-local helper | One `lib/toast.ts` with our tokens | ❌ |
| **Action toasts** | Sonner supports | Need pattern for "saved — undo" | ❌ |
| Progress bar | Sonner default | ✅ | ✅ |

**Score: 3/5.**
**Priority: P0.5** → ticket **P0.5-06**. Write `src/lib/toast.ts` wrapping sonner with our variants (info/success/warning/error) and the undo-action pattern.

---

### 1.12 `motion-fade.tsx`

**Score: 3/5.** Good — respects reduced motion, ease-out-quad, delay prop.
**Gap:** Only one motion pattern exists. Need a library: SlideIn, Stagger, LayoutGroup, scroll-triggered reveals.
**Priority: P0.5** → ticket **P0.5-16 Motion primitives**. Keep `MotionFade`, add siblings.

---

### 1.13 `gradient-mesh.tsx` / `section-hero.tsx`

**Score: 4/5.** Marketing-only helpers. Fine as-is; revisit when we overhaul public landing (Stripe-ref Phase 3).

---

## 2. Feature Components (`frontend/src/components/features/`)

### 2.1 `markdown-renderer.tsx`

**Score: 4/5** — the most polished component we have. Syntax highlighting, copy button, custom list bullets, dark code blocks.
**Gaps:** No line-hover highlight. No line-linking. No diff mode.
**Priority: P0.5** → ticket **P0.5-11**. Small polish pass, not a rebuild.

---

### 2.2 `chat-message.tsx` / `agent-chat-stream.tsx`

These drive the chat surface — Claude reference applies. Current impl uses gradient bubbles + `MarkdownRenderer`.
**Score: 4/5** for the recent rebuild.
**Gaps:** User bubble still uses teal primary (should follow Claude warm palette when chat surface adopts Claude zone). Thinking-dots animation is ad-hoc (should live in motion primitives).
**Priority: P1.** Revisit during Phase 1-B Studio (merged chat + code) where chat becomes a pane, not a page.

---

### 2.3 `course-card.tsx`, `lesson-item.tsx`, `progress-bar.tsx`, `user-avatar.tsx`

These are likely to be **deprecated** or significantly restructured:
- `course-card.tsx` → may be replaced by Skill Map node cards (Phase 1-A).
- `progress-bar.tsx` → XP/streaks are being killed (P1-C-1).
- `user-avatar.tsx` → appears to be a wrapper; likely redundant with `ui/avatar.tsx`.
- `lesson-item.tsx` → survives if we keep lesson lists inside Map node drawers.

**Priority: P1.** Audit during Phase 1-A/1-C. Delete redundant ones.

---

## 3. Missing Components (must build in Phase 0.5)

| Component | Why needed | Ticket |
|---|---|---|
| **Combobox** (searchable select) | Skill picker, onboarding, admin | P0.5-03 |
| **Textarea** (autosize, counter, label) | Onboarding goal, chat input, reflection | P0.5-02 |
| **Command palette** (Cmd+K) | Flagship differentiator; Raycast bar | P0.5-10 |
| **DataTable** | Admin cohort views, exercise lists | P0.5-07 |
| **Spinner / Skeleton / Progress** | Loading states everywhere | P0.5-13 |
| **EmptyState shell** | Every list view | P0.5-14 |
| **Form system** (RHF + Zod wrapper) | Onboarding, settings, admin forms | P0.5-15 |
| **Motion primitives** (FadeIn, SlideIn, Stagger, LayoutGroup, ScrollReveal) | Reusable motion | P0.5-16 |
| **Keyboard shortcut system** (`<Kbd>`, `useShortcut`, registry) | Power-user signal | P0.5-17 |
| **Kbd visual** | Shortcut rendering (Raycast gradient-key style) | P0.5-17 |
| **Toast wrapper** | Consistent notifications | P0.5-06 |
| **Icon registry** | Centralize lucide imports | P0.5-19 |
| **Popover + Tooltip** | Base UI primitives — add project wrappers | P0.5-05 |
| **Tooltip delay tokens** | 300ms open / 100ms close consistent | P0.5-05 |

---

## 4. Theme Tokens — audit of `globals.css`

Action item **P0.5-18 Theme tokens refresh**:
- Audit current CSS vars against three zones (Portal=Linear, Public=Stripe, Chat=Claude).
- Add elevation tokens (`--elevation-1` through `--elevation-5` mapping to the multi-layer shadow stacks Linear/Vercel/Claude define).
- Add motion tokens (`--motion-fast-150`, `--motion-base-250`, `--motion-slow-400`, `--ease-out-quad`).
- Add letter-spacing tokens (`--tracking-display-xxl`, `-xl`, `-lg`, etc., per Linear scale).
- Add font-feature-settings utility for Inter `"cv01","ss03"` (Linear identity).
- Verify dark mode defaults are correct for Portal zone.

---

## 5. Priority-Ordered Phase 0.5 Ticket List

(Matches ROADMAP.md P0.5 tickets, now grounded in this audit.)

| Order | Ticket | Component | Why this order |
|---|---|---|---|
| 1 | P0.5-18 | Theme tokens refresh | Every other ticket consumes these tokens |
| 2 | P0.5-19 | Icon registry | Referenced by almost every other ticket |
| 3 | P0.5-16 | Motion primitives | Buttons/Dialogs/Tabs will consume these |
| 4 | P0.5-17 | Keyboard shortcut system | Command palette + all global shortcuts need it |
| 5 | P0.5-01 | Button (add loading/success, tighten tokens) | Highest-usage primitive |
| 6 | P0.5-02 | Input + Textarea | Onboarding blocks on these |
| 7 | P0.5-13 | Spinner / Skeleton / Progress | Consumed by every async surface |
| 8 | P0.5-14 | EmptyState shell | Every list needs it |
| 9 | P0.5-06 | Toast wrapper | After that, every feature can give feedback |
| 10 | P0.5-05 | Tooltip + Popover wrappers | UX polish across the board |
| 11 | P0.5-09 | Card (hover, skeleton, interactive variant) | Today screen consumer |
| 12 | P0.5-08 | Tabs (layoutId animation, scrollable) | Map, Studio, Receipts use tabs |
| 13 | P0.5-04 | Responsive Dialog/Sheet | Onboarding + settings |
| 14 | P0.5-03 | Combobox | Needed when skill graph lands |
| 15 | P0.5-12 | Avatar (deterministic color, initials helper) | Chat + community |
| 16 | P0.5-15 | Form system (RHF + Zod) | Onboarding is first consumer |
| 17 | P0.5-10 | Command palette | Needs keyboard + icon + motion systems first |
| 18 | P0.5-07 | DataTable | Admin Phase 2 |
| 19 | P0.5-11 | Code block polish | Studio Phase 1-B |
| 20 | P0.5-20 | Storybook coverage | Continuous — stories written per ticket above |

---

## 6. Parallelism Map

Tickets that can run in parallel (independent files / no shared changes):

- **Track A (foundation, sequential):** 18 → 19 → 16 → 17
- **Track B (primitives, parallel after A):** 01, 02, 13, 14, 06 can all run at once
- **Track C (composites, after B):** 05, 09, 08, 04 parallel
- **Track D (advanced):** 03, 12, 15 parallel
- **Track E (feature-depth, later):** 10, 07, 11
- **Track F (continuous):** 20 runs alongside all others

Up to **5 agents in parallel** once Track A is done. Each agent works in `pae-<ticket-id>` worktree, claims the `Touches:` files from ROADMAP.md, opens a PR, merges before the next claim.

---

## 7. Non-Goals for Phase 0.5

To stay disciplined:
- **No new feature components.** Only primitives + missing foundations.
- **No backend changes.** This is frontend-only.
- **No redesign of existing feature components** (markdown-renderer, chat-message). Polish only.
- **No Storybook for feature components** — only primitives. Feature stories come with feature tickets.

---

**Audit complete. Ready to execute Phase 0.5 tickets in the order above.**
