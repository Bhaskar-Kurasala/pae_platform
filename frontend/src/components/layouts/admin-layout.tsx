"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  ClipboardList,
  Flame,
  LayoutDashboard,
  LineChart,
  MessageSquare,
  Users,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Separator } from "@/components/ui/separator";
import { Kbd } from "@/components/ui/kbd";
import { SkipToContent } from "@/components/layouts/skip-to-content";

// Sidebar nav — every entry MUST point at a route that has a page.tsx.
// Three previously-listed entries (`/admin/courses`, `/admin/analytics`,
// `/admin/settings`) were aspirational scaffolding from earlier phases —
// no page.tsx existed for any of them, so Next's prefetch on hover
// 404'd and clicks landed on the global error boundary. Removed
// pending the actual screens being built. The `/admin/courses/[id]/edit`
// route still exists for editing a single course (linked from the
// console's row actions), it just doesn't have a list page yet.
// "At-risk" was retired in favour of the F4 retention engine —
// the /admin Overview now hosts the canonical retention panels
// (paid_silent, capstone_stalled, streak_broken, ready-but-stalled,
// never-returned), each with a "See all N →" link that lands on
// the modernized roster filtered by slip pattern. The legacy
// /admin/at-risk page used an older multi-signal scoring system
// that detected a different cohort, so showing both in the
// sidebar created two competing "at-risk" views. The legacy URL
// still exists and redirects to /admin.
const adminNavItems = [
  { href: "/admin", label: "Overview", icon: LayoutDashboard },
  { href: "/admin/pulse", label: "Pulse", icon: Activity },
  { href: "/admin/students", label: "Students", icon: Users },
  { href: "/admin/confusion", label: "Confusion", icon: Flame },
  { href: "/admin/feedback", label: "Feedback", icon: MessageSquare },
  { href: "/admin/agents", label: "Agents", icon: Zap },
  { href: "/admin/audit-log", label: "Audit Log", icon: ClipboardList },
  { href: "/admin/content-performance", label: "Content Perf", icon: LineChart },
];

interface AdminLayoutProps {
  children: React.ReactNode;
}

export function AdminLayout({ children }: AdminLayoutProps) {
  const pathname = usePathname();

  return (
    <div className="flex h-screen bg-background">
      <SkipToContent />
      <aside className="flex w-64 flex-col border-r bg-card">
        <div className="flex h-16 items-center px-6">
          <span className="text-xl font-bold">
            <span className="text-primary">PAE</span> Admin
          </span>
        </div>
        <Separator />
        <div className="px-3 pt-3 pb-1">
          <div className="flex items-center gap-2 rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
            <span className="flex-1">Jump anywhere</span>
            <Kbd keys="mod+k" />
          </div>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-4">
          {adminNavItems.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              aria-label={label}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                pathname === href || pathname.startsWith(`${href}/`)
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              <Icon className="h-5 w-5" aria-hidden="true" />
              {label}
            </Link>
          ))}
        </nav>
      </aside>
      <main id="main-content" tabIndex={-1} className="flex-1 overflow-auto focus:outline-none">
        {children}
      </main>
    </div>
  );
}
