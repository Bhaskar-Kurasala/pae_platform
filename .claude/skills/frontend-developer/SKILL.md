---
name: frontend-developer
description: |
  Use when building Next.js pages, React components, or frontend features.
  Covers App Router patterns, shadcn/ui components, Tailwind styling,
  React Query data fetching, and Zustand state management.
  Trigger phrases: "page", "component", "frontend", "UI", "dashboard"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, TodoWrite
---

# Frontend Development Skill

## Page Creation Pattern (App Router)
```
src/app/(portal)/dashboard/
├── page.tsx          # Server Component (default) — fetch data
├── loading.tsx       # Suspense fallback skeleton
├── error.tsx         # Error boundary
└── _components/      # Page-specific client components
    ├── ProgressChart.tsx
    └── RecentActivity.tsx
```

## Component Template
```tsx
// Server Component (default)
import { getCourses } from "@/lib/api-client";

export default async function CoursesPage() {
  const courses = await getCourses();
  return (
    <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
      {courses.map(c => <CourseCard key={c.id} course={c} />)}
    </div>
  );
}

// Client Component (only when needed for interactivity)
"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";

export function AgentChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  // ...
}
```

## Data Fetching
- Server Components: use `fetch()` or API client directly
- Client Components: use `@tanstack/react-query` with `useQuery`/`useMutation`
- Never use `useEffect` for data fetching

## Styling Rules
- Tailwind utility classes ONLY
- Design tokens: teal (#1D9E75), purple (#7C3AED), dark (#111827)
- shadcn/ui components as base — extend with Tailwind
- Responsive: mobile-first (default → sm → md → lg → xl)
- Dark mode: use `dark:` prefix, respect system preference

## New Feature Checklist
- [ ] Page component in `src/app/` with correct route group
- [ ] Loading skeleton in `loading.tsx`
- [ ] Error boundary in `error.tsx`
- [ ] Storybook story for each new component
- [ ] Responsive layout (test at 375px, 768px, 1280px)
- [ ] Accessibility: keyboard nav, screen reader labels
- [ ] API integration via `api-client.ts`
