# Frontend — Next.js 15

## Stack
Next.js 15 (App Router) + TypeScript (strict) + Tailwind CSS 4 + shadcn/ui + React Query + Zustand

## Commands
```
pnpm dev          # Dev server on :3000
pnpm build        # Production build
pnpm lint         # ESLint + Prettier
pnpm test         # Vitest
pnpm storybook    # Component browser
pnpm generate:api # Regenerate API client from OpenAPI schema
```

## File Structure
```
src/
├── app/              # App Router pages (file-based routing)
│   ├── (public)/     # No-auth pages: landing, courses, etc.
│   ├── (portal)/     # Auth-required student portal pages
│   ├── (admin)/      # Admin dashboard pages
│   └── layout.tsx    # Root layout with providers
├── components/
│   ├── ui/           # shadcn/ui base components
│   ├── features/     # Feature-specific components (CourseCard, AgentChat)
│   └── layouts/      # Page layouts (PortalLayout, AdminLayout)
├── lib/
│   ├── api-client.ts # Auto-generated from backend OpenAPI schema
│   ├── hooks/        # Custom React hooks
│   └── utils.ts      # Shared utilities
├── stores/           # Zustand stores (auth, ui, agents)
└── types/            # Generated TypeScript types
```

## Rules
- Use Server Components by default. Add 'use client' ONLY when needed (interactivity, hooks).
- API calls through `src/lib/api-client.ts` — auto-generated from FastAPI OpenAPI schema.
- ALL components must have Storybook stories in `__stories__/` adjacent directory.
- Use Tailwind utility classes ONLY — no inline styles, no CSS modules, no styled-components.
- Accessibility: all interactive elements need `aria-label`. All images need `alt`.
- Images: always use `next/image` with explicit width/height.
- Loading states: use React Suspense boundaries with skeleton components.
- Error states: use error.tsx boundary files per route segment.

## Design Tokens
```
Primary:    #1D9E75 (teal — CTAs, success, navigation)
Secondary:  #7C3AED (purple — paid badges, premium)
Background: #FFFFFF / #F8FAFC
Text:       #111827 (primary) / #6B7280 (secondary)
Border:     #E2E8F0
Font:       Inter (body), JetBrains Mono (code)
Radius:     8px (cards), 6px (buttons), 4px (inputs)
```
