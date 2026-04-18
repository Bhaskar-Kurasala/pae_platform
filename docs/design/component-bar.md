# Component Bar — the $1000 Standard

**Purpose:** Before any UI ships, every primitive is held to this bar. Used as the acceptance checklist for Phase 0.5 and onwards.

**References:** See `docs/design-references/INDEX.md` for surface→inspiration mapping. Primary: Linear (portal), Claude (chat), Vercel/Stripe (public).

---

## Universal Rules

Every interactive primitive must:

1. **Have 6 states visible in the design gallery** (`/design`): idle, hover, focus-visible (keyboard), active/pressed, disabled, loading (if async).
2. **Respect keyboard** — all actions reachable without mouse. `Tab` order is logical. `Esc` closes floating surfaces.
3. **Respect `prefers-reduced-motion`** — use `transition-*` tokens that the motion spec gates off for reduced-motion users.
4. **Announce state** — `aria-busy` during loading, `aria-invalid` + `aria-describedby` for errors, `aria-current` for nav.
5. **No layout shift** — loading skeletons match final dimensions; dropdowns use portals.
6. **Use tokens, not literals** — colors via `var(--*)` / theme classes, spacing via Tailwind scale, elevation via `var(--elevation-N)`.
7. **Dark-mode parity** — every surface has a tested dark variant (portal default is dark).
8. **Duration tokens** — only `duration-fast` (140ms), `duration-base` (220ms), `duration-slow` (420ms). Nothing ad-hoc.

---

## Per-Primitive Bar

### Button
- Variants: default, outline, secondary, ghost, destructive, link.
- Sizes: sm, md (default), lg, icon.
- States: all 6 above + `success` (Check icon, 1.6s flash).
- Icon slots: `iconStart`, `iconEnd`, icon-only (requires `aria-label`).
- Press: `translate-y-px` on `:active`.
- Loading: inline `Loader2`, label dims to 70% opacity, `aria-busy=true`.

### Input / Textarea
- Border whisper idle; focus-within ring; destructive on `aria-invalid`.
- Leading / trailing icon slots. Clearable variant swaps trailing icon with X when value present.
- Textarea: `autosize` with `maxRows`, optional character counter (amber at 90%, destructive at 100%).

### Combobox / Select
- Searchable. Arrow-key nav, Enter selects, Esc closes. Groups render with tracked-out uppercase labels.
- Multi-select shows chips with individual remove buttons.
- Popup width matches trigger by default (`var(--anchor-width)`).

### Dialog / Sheet
- Spring-ish entrance (`scale-95 → 100, opacity-0 → 100`, duration-base).
- Focus trap; Esc closes; backdrop blur.
- `ResponsiveDialog`: Dialog on ≥640px, bottom Sheet below. Consumer never worries about viewport.

### Tooltip
- 300ms open delay, 100ms close delay (shared `TooltipProvider`).
- Content + optional `shortcut` kbd chip. Never layout-shifts anchor.

### Popover
- Elevation-3 by default; can opt into 2/4/5.
- Click-outside + Esc close. Portaled.

### Toast (Sonner)
- Variants: success, error, warning, info, loading, message.
- Error defaults to 8s; others 4s. `toast.undo(msg, onUndo)` for destructive actions (6s).
- Queue stacks bottom-right; swipe to dismiss on touch.

### Table / DataTable
- Sort-click header with chevron. Global filter, pagination, row selection.
- Loading → skeleton rows with fixed height (no shift).
- Empty → `EmptyState` inside the `<tbody>`.

### Tabs
- Underline variant: animated indicator on trigger switch.
- Pill variant: active trigger has `bg-foreground text-background`, elevation-1.
- `scrollable` prop wraps the list in overflow-x with edge mask fade.

### Card
- Variants: default, interactive (lifts on hover), ghost (no border), elevated (permanent shadow-2).
- Loading variant shows shimmer skeletons in the slot positions.

### Command Palette (⌘K)
- Auto-registers `mod+k` via `useShortcut`. Editable inputs exempt from capture.
- Token-AND filter over `label + hint + keywords + group`. Arrow/Home/End/Enter navigation.
- Footer always shows `↑ ↓ navigate · ↵ select` kbd hints.

### CodeBlock
- Language chip + optional filename. Copy button (Check flash 1.6s).
- Line numbers auto-on past 5 lines. Hover highlights line row. Click a line number to copy `#L{n}` link and highlight.

### EmptyState
- Icon (lucide, 24px muted) + title + description + optional primary + secondary action.
- `bordered` prop for inline use in cards/tables.

### Avatar
- Sizes sm/default/lg/xl. Fallback = 1–2 initials from `toInitials()`. Background class from `avatarColor(seed)` — deterministic palette of 8 hues.
- `AvatarGroup` stacks with negative margin + ring-background.

### Kbd
- Platform-aware (`useSyncExternalStore` mac detection). Keys: mod, shift, alt, ctrl, enter, esc, up/down/left/right, space, tab, backspace.
- Accepts `+`-joined shortcut string and renders individual chips.

---

## Acceptance for any new primitive

A new primitive is "ready" when:

- [ ] Lives in `frontend/src/components/ui/` with a short header comment explaining intent.
- [ ] Appears in `/design` under a labeled section with idle + hover + invalid/loading/disabled states visible.
- [ ] Passes `pnpm exec tsc --noEmit` and `pnpm exec eslint` with zero errors.
- [ ] Uses tokens for color/motion/spacing (no literals).
- [ ] Dark mode checked.
- [ ] Keyboard-only demo works.
