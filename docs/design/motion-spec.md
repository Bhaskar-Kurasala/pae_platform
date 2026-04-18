# Motion Spec

**Source of truth:** `frontend/src/app/globals.css` (CSS custom properties) + `frontend/src/lib/motion.ts` (framer-motion variants).

---

## Duration Tokens

| Token | ms | Use |
|---|---|---|
| `--duration-instant` | 80 | Button press, chip click |
| `--duration-fast` | 140 | Hover, focus ring, tooltip, tabs |
| `--duration-base` | 220 | Dialog / sheet / popover enter-exit, card elevate |
| `--duration-slow` | 420 | Page transitions, hero reveals |

CSS utility classes: `duration-fast`, `duration-base`, `duration-slow`.

## Easing Tokens

| Token | Curve | Use |
|---|---|---|
| `--ease-out-quad` | `cubic-bezier(0.25, 0.46, 0.45, 0.94)` | Default — enters and most state changes |
| `--ease-in-out-quad` | `cubic-bezier(0.455, 0.03, 0.515, 0.955)` | Two-way transitions (drawer toggle) |
| Spring (framer) | `{ type: "spring", stiffness: 300, damping: 30 }` | Dialog popup, card interactions |

CSS utility classes: `ease-out-quad`, `ease-in-out-quad`.

## Motion Tokens (framer)

Exported from `lib/motion.ts` as `MOTION`:

```ts
MOTION.duration.fast   = 0.14
MOTION.duration.base   = 0.22
MOTION.duration.slow   = 0.42
MOTION.ease.outQuad    = [0.25, 0.46, 0.45, 0.94]
MOTION.ease.inOutQuad  = [0.455, 0.03, 0.515, 0.955]
MOTION.ease.spring     = { type: "spring", stiffness: 300, damping: 30 }
```

## Variant Library

From `lib/motion.ts`, reused across the app:

- `fade` — opacity 0 ↔ 1.
- `fadeUp` — opacity + 8px y translate.
- `slideLeft` / `slideRight` — 12px x translate + fade.
- `scaleIn` — 0.95 → 1 scale + fade.
- `staggerParent` — `staggerChildren: 0.05, delayChildren: 0.05`.

Components built on these: `<SlideIn>`, `<Stagger>` + `<StaggerItem>`, `<ScrollReveal>` (uses `useInView` with `once: true`).

## Entrance/Exit Patterns

| Surface | Entrance | Exit |
|---|---|---|
| **Dialog / Sheet** | scale 0.95→1 + fade, duration-base, ease-out-quad | reverse, duration-fast |
| **Popover / Tooltip** | scale 0.95→1 + fade from `--transform-origin`, duration-fast | reverse, duration-fast |
| **Toast** | slide-up 16px + fade, duration-base | slide-down + fade, duration-fast |
| **Card hover** | `-translate-y-0.5` + elevation bump, duration-fast | reverse |
| **Tab indicator** | layout animation, duration-base, spring | — |
| **Page route** | fade + 8px y, duration-base (only on portal routes) | none (Next app-router handles) |
| **Palette open** | scale 0.95→1 + fade from top, duration-base | reverse, duration-fast |

## Reduced Motion

All motion primitives respect `@media (prefers-reduced-motion: reduce)`:
- Framer components use `useReducedMotion()` to flatten transitions.
- CSS durations collapse to 0ms via the media query in `globals.css`.
- Only color/opacity transitions remain on.

## Don'ts

- No bounce on enter (unprofessional).
- No motion over 500ms for UI chrome (marketing hero is the exception).
- No simultaneous motion + color transitions on the same property.
- No spring on continuous drag — use linear/ease-out.
- Never animate `width`/`height` if you can animate `transform` instead.

## Gesture Expectations

- **Swipe-to-dismiss**: sheet, toast. Threshold 40% or 400 px/s velocity.
- **Keyboard repeat**: arrow keys in listboxes trigger at native repeat rate.
- **Scroll**: use `overflow-auto` with native inertia; no custom scroll-hijack.
- **Focus-visible**: always animate ring opacity, never width (causes jitter).
