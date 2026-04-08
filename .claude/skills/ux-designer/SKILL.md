---
name: ux-designer
description: |
  Use for UI design decisions, component layout, accessibility, and design system.
  Trigger phrases: "design", "layout", "UX", "accessibility", "responsive", "UI"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# UX Design Skill

## Design System
- **Primary**: #1D9E75 (teal) — CTAs, success, active states
- **Secondary**: #7C3AED (purple) — premium badges, highlights
- **Background**: #FFFFFF (page), #F8FAFC (cards/sections)
- **Text**: #111827 (primary), #6B7280 (secondary), #9CA3AF (tertiary)
- **Border**: #E2E8F0
- **Error**: #EF4444 | **Warning**: #F59E0B | **Success**: #10B981
- **Font**: Inter (body), JetBrains Mono (code)
- **Radius**: 8px cards, 6px buttons, 4px inputs
- **Shadow**: `shadow-sm` for cards, `shadow-md` for modals

## Layout Patterns
- **Max content width**: 1280px (7xl) centered
- **Grid**: 12-column, gap-6 default
- **Sidebar**: 280px fixed, collapsible on mobile
- **Cards**: rounded-lg, border, p-6, hover:shadow-md transition
- **Tables**: full-width, sticky header, alternating row shading

## Component Hierarchy
1. shadcn/ui base components (Button, Card, Dialog, Input, etc.)
2. Feature components built FROM shadcn/ui (CourseCard, AgentChat, ProgressBar)
3. Page layouts (PortalLayout, AdminLayout, PublicLayout)
4. Pages (compose layouts + feature components)

## Accessibility Requirements
- All interactive elements: `aria-label` or visible label
- Focus indicators: `ring-2 ring-offset-2 ring-teal-500`
- Color contrast: WCAG AA minimum (4.5:1 for text)
- Keyboard navigation: all features accessible without mouse
- Screen reader: semantic HTML (nav, main, aside, article, section)

## Responsive Breakpoints
- Mobile: default (< 640px) — single column, bottom nav
- Tablet: sm/md (640-1024px) — sidebar collapses, 2-column grid
- Desktop: lg+ (1024px+) — full sidebar, 3-column grid
