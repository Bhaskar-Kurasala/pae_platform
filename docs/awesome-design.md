# Awesome Design — PAE Platform Design Bible

This document is the single source of truth for design decisions across the platform. Every component, page, and interaction must conform to these principles. When in doubt, reference a real-world example from Linear, Vercel, Stripe, or Claude.ai.

---

## Core Philosophy

**Precision over decoration.** Every pixel earns its place. No gradients without purpose. No animations without meaning. We design for engineers who see through bullshit.

**Density without clutter.** Engineers can process information-dense UIs. Linear proved this. We use whitespace intentionally — not to fill space, but to create hierarchy.

**Dark-first, light-optional.** Our users code at night. Dark mode is the default. Light mode is fully supported but secondary.

---

## Design Zones (Three Distinct Aesthetics)

### Zone 1: Marketing Pages (`/`, `/pricing`, `/about`, `/agents`)
**Inspiration:** Stripe + Notion  
**Feel:** Warm, trustworthy, conversion-optimized  
**Characteristics:**
- Light background default (`bg-background`)
- Generous whitespace (`py-24` sections)
- Gradient accents on CTAs only (never backgrounds)
- Social proof: logo bars, testimonial carousels, stats
- Clear information hierarchy: headline → subline → CTA
- Footer with full link structure

### Zone 2: Student Portal (`/dashboard`, `/courses`, `/lessons`, `/progress`)
**Inspiration:** Linear + Vercel Dashboard  
**Feel:** Focused, productive, no-nonsense  
**Characteristics:**
- Dark mode default (sidebar + content area)
- Left sidebar navigation (64px icon-only collapsed, 240px expanded)
- KPI cards: number-forward, minimal labels, sparkline trend
- Tables over card grids for data-heavy views
- Green (#1D9E75) for positive states: completed, on-track, mastered
- No decorative elements in the portal — every element is functional

### Zone 3: Agent Chat (`/chat`)
**Inspiration:** Claude.ai + Cursor  
**Feel:** Conversational, focused, intelligent  
**Characteristics:**
- Full-height layout, no page chrome visible while chatting
- Agent identity chip (name + avatar + specialty) anchored to top
- Messages: user right-aligned bubble, agent full-width with prose
- Streaming: cursor blink animation while tokens arrive
- Code blocks: dark themed with copy button + language label
- History drawer slides in from left on demand

---

## Color System

```
Primary (Teal):    #1D9E75  —  Success, CTAs, active states, progress
Brand Purple:      #7C3AED  —  Premium, paid tier badges, highlights
Background:        #FAFAFA (light) / #0A0A0A (dark)
Surface:           #FFFFFF (light) / #111111 (dark)
Surface-2:         #F4F4F5 (light) / #1A1A1A (dark)
Text Primary:      #09090B (light) / #FAFAFA (dark)
Text Secondary:    #71717A (light) / #A1A1AA (dark)
Border:            #E4E4E7 (light) / #27272A (dark)
```

**Brand gradient** (use only for hero accent, CTAs, not backgrounds):
```css
background: linear-gradient(135deg, #1D9E75 0%, #7C3AED 100%);
```

---

## Typography

```
Heading Font:  Inter (fallback: system-ui)  — all headings
Body Font:     Inter — body text  
Code Font:     JetBrains Mono — code blocks, terminal output, agent responses with code

Scale:
h1 (hero):       clamp(2.5rem, 5vw, 4rem) / font-bold / tracking-tight
h2 (section):    2rem / font-bold
h3 (card title): 1.25rem / font-semibold
body:            1rem / font-normal / leading-7
small/meta:      0.875rem / text-muted-foreground
code:            0.875rem / JetBrains Mono
```

---

## Motion Principles

**Use framer-motion.** All animations should:

1. **Respect `prefers-reduced-motion`** — wrap with `motion.div` and `AnimatePresence`, but honor the OS setting.
2. **Entrance only** — elements animate in. They do not animate out except for modals/drawers.
3. **Stagger children** — lists stagger at 50ms per item.
4. **Duration:** 200–400ms. Never more than 500ms for UI feedback.
5. **Easing:** `[0.25, 0.46, 0.45, 0.94]` (ease-out-quad) for entrances. `spring` for interactive feedback.

**Approved animation patterns:**
```tsx
// Fade + slide up (page sections, cards)
initial={{ opacity: 0, y: 20 }}
animate={{ opacity: 1, y: 0 }}
transition={{ duration: 0.35, ease: [0.25, 0.46, 0.45, 0.94] }}

// Scale pop (buttons, badges)
whileHover={{ scale: 1.02 }}
whileTap={{ scale: 0.98 }}

// Stagger list
variants={{ container: { staggerChildren: 0.05 }, item: { opacity: 0, y: 10 } }}
```

**DO NOT:**
- Animate colors (performance killer)
- Use `transition: all` 
- Add hover animations to text links
- Use entrance animations in the chat interface (streaming is already motion)

---

## Component Conventions

### Cards
```
rounded-xl border bg-card p-6 shadow-sm
hover: shadow-md transition-shadow duration-200
```

### Buttons (primary)
```
h-10 px-5 rounded-lg bg-primary text-primary-foreground font-semibold text-sm
hover: bg-primary/90 transition-colors
active: scale-[0.98]
```

### Buttons (secondary / outline)
```
h-10 px-5 rounded-lg border border-border bg-transparent text-foreground font-medium text-sm
hover: bg-muted transition-colors
```

### Inputs
```
h-10 rounded-lg border bg-background px-3 text-sm
focus: ring-2 ring-primary/30 border-primary outline-none
```

### Badges
```
Teal (free/active):   bg-primary/10 text-primary rounded-full px-2.5 py-0.5 text-xs font-medium
Purple (paid/premium): bg-[#7C3AED]/10 text-[#7C3AED] rounded-full px-2.5 py-0.5 text-xs font-medium
```

---

## Spacing System

Use Tailwind's default 4px base. Never invent spacing values.

```
Section vertical gaps:    py-24 (marketing), py-16 (portal)
Card internal padding:    p-6 (standard), p-4 (compact)
Navigation item spacing:  gap-1 (vertical list), gap-6 (horizontal)
Form field spacing:       space-y-4
```

---

## Page Layout Patterns

### Marketing Hero
```
full-width gradient mesh background (CSS only, no canvas)
max-w-4xl mx-auto text-center
badge → h1 → p (subtitle) → CTA row → social proof
```

### Gradient Mesh (CSS-only, no particles library)
```css
background: 
  radial-gradient(ellipse at 20% 50%, oklch(0.63 0.13 164 / 0.15) 0%, transparent 50%),
  radial-gradient(ellipse at 80% 20%, oklch(0.52 0.25 283 / 0.12) 0%, transparent 40%);
```

### Portal Layout (Linear-inspired)
```
Fixed left sidebar: w-16 (icons) / w-60 (expanded) — collapsible
Main content: flex-1 overflow-auto
Top bar: h-14 with breadcrumb + user menu + notifications
```

### Chat Layout (Claude.ai-inspired)
```
Full viewport: h-screen flex flex-col
Agent header bar: h-14 shrink-0
Messages area: flex-1 overflow-y-auto px-4
Input area: shrink-0 border-t p-4
```

---

## Accessibility Rules

- All interactive elements: `aria-label` when no visible text label
- All images: `alt` attribute (empty string for decorative)
- Color contrast: AA minimum, AAA for body text
- Focus rings: visible on all focusable elements (use `focus-visible:ring-2`)
- Animation: `prefers-reduced-motion: reduce` must disable all transitions
- Keyboard navigation: all interactive elements must be keyboard-reachable

---

## Icon Strategy

Use `lucide-react` exclusively. Icon sizes:
- Navigation: `h-5 w-5`
- In-button: `h-4 w-4`
- Hero/feature sections: `h-8 w-8` (with bg wrapper)
- Status indicators: `h-3 w-3`

---

## Do's and Don'ts

### DO:
- Use semantic HTML (nav, main, section, article, aside)
- Use `next/image` for all images with explicit dimensions
- Use React Suspense with skeleton fallbacks for all async data
- Use `error.tsx` per route segment for error boundaries
- Test dark mode every time you add a new component

### DON'T:
- Use inline styles (zero exceptions)
- Use CSS modules or styled-components
- Add emoji to UI unless it's a celebration/achievement context
- Use shadows heavier than `shadow-md`
- Add loading spinners — use skeleton components
- Mix Tailwind arbitrary values with OKLCH tokens (pick one per context)

---

## Reference Implementations

These are the gold standard we aspire to:

| Product | What to steal |
|---|---|
| linear.app | Dashboard layout, sidebar navigation, table density |
| vercel.com/dashboard | KPI cards, empty states, notifications |
| stripe.com | Marketing page sections, pricing cards, footer |
| claude.ai | Chat layout, streaming UX, message bubbles |
| cursor.com | Agent-context UI, file tree integration |
