"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo } from "react";
import { useAuthStore } from "@/stores/auth-store";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { useMyGoal } from "@/lib/hooks/use-goal";
import { V8SoundToggle } from "./v8-sound-toggle";
import { V8ThemeToggle } from "./v8-theme-toggle";

const NAV_GROUPS: ReadonlyArray<{
  label: string;
  variant?: "secondary";
  items: ReadonlyArray<{
    href: string;
    label: string;
    sparkle?: string;
    catalogStyle?: boolean;
  }>;
}> = [
  {
    label: "Core",
    items: [
      { href: "/today", label: "Today" },
      { href: "/path", label: "My path" },
      { href: "/studio", label: "Studio" },
      { href: "/promotion", label: "Promotion" },
    ],
  },
  {
    label: "Career",
    items: [
      { href: "/readiness", label: "Job readiness" },
      { href: "/notebook", label: "Notebook" },
    ],
  },
  {
    label: "Practice",
    items: [
      { href: "/chat", label: "AI Tutor" },
      { href: "/exercises", label: "Exercises" },
    ],
  },
  {
    label: "Explore",
    variant: "secondary",
    items: [
      {
        href: "/catalog",
        label: "Catalog",
        sparkle: "5 tracks",
        catalogStyle: true,
      },
    ],
  },
];

function initials(name: string | undefined): string {
  if (!name) return "??";
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("") || "??";
}

function isActive(pathname: string, href: string): boolean {
  if (pathname === href) return true;
  return pathname.startsWith(`${href}/`);
}

interface RoleSummary {
  current: string;
  next: string;
  daysToNext: number;
  level: number;
  promotionPct: number;
}

function deriveRole(
  goalSuccess: string | undefined,
  progressPct: number | undefined,
  deadlineMonths: number | undefined,
): RoleSummary {
  // Fallback role names mirror the v8 narrative when no skill path exists yet.
  const current = "Python Developer";
  // Derive a "next role" by stripping leading articles from the goal success
  // statement; that field is the student's own description of where they're
  // headed and is the closest signal we have today.
  const next = goalSuccess
    ? goalSuccess
        .replace(/^(become|be|land|get|reach|achieve)\s+(an?|the)?\s+/i, "")
        .split(/[.,;\n]/)[0]!
        .trim()
        .replace(/\s+job$/i, "")
        .slice(0, 32) || "Data Analyst"
    : "Data Analyst";
  const monthsLeft = deadlineMonths ?? 2;
  const daysToNext = Math.max(7, Math.round(monthsLeft * 30 * (1 - (progressPct ?? 0) / 100)));
  const level = Math.max(1, Math.floor((progressPct ?? 0) / 25) + 1);
  const promotionPct = Math.max(0, Math.min(100, Math.round(progressPct ?? 0)));
  return { current, next, daysToNext, level, promotionPct };
}

export function V8Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const { data: goal } = useMyGoal();
  const { data: progress } = useMyProgress();

  const role = useMemo(
    () =>
      deriveRole(
        goal?.success_statement,
        progress?.overall_progress,
        goal?.deadline_months,
      ),
    [goal, progress],
  );

  function handleLogout() {
    logout();
    router.replace("/login");
  }

  return (
    <aside className="sidebar">
      <div className="brand reveal">
        <h1>
          Career<i>Forge</i>
        </h1>
        <p>Become. Do not just learn.</p>
      </div>

      <div className="role-card reveal delay-1">
        <div className="eyebrow">Current identity</div>
        <div className="current-role">{role.current}</div>
        <div className="role-meta">
          Next role: <b>{role.next}</b> in <span>{role.daysToNext}</span> days at your current pace.
        </div>
      </div>

      <nav className="nav reveal delay-2" aria-label="Primary">
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            <div className={`nav-group${group.variant === "secondary" ? " secondary" : ""}`}>
              {group.label}
            </div>
            {group.items.map((item) => {
              const active = isActive(pathname, item.href);
              const className = [
                active ? "active" : "",
                item.catalogStyle ? "catalog-link" : "",
              ]
                .filter(Boolean)
                .join(" ");
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={className || undefined}
                  aria-current={active ? "page" : undefined}
                  prefetch
                >
                  <span className="nav-dot" aria-hidden />
                  {item.label}
                  {item.sparkle && <span className="sparkle">{item.sparkle}</span>}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="sidebar-foot reveal delay-3">
        <div className="student">
          <div className="avatar" aria-hidden>
            {initials(user?.full_name)}
          </div>
          <div>
            <div className="name">{user?.full_name ?? "Student"}</div>
            <div className="meta">
              Level {role.level} · {role.promotionPct}% to promotion
            </div>
          </div>
        </div>
        <div className="sidebar-foot-bottom">
          <V8SoundToggle />
          <V8ThemeToggle />
          <button
            type="button"
            onClick={handleLogout}
            aria-label="Sign out"
            className="sidebar-signout"
            title="Sign out"
          >
            <svg
              viewBox="0 0 14 14"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.6}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M5 4V2.5a1 1 0 011-1h5a1 1 0 011 1v9a1 1 0 01-1 1H6a1 1 0 01-1-1V10" />
              <path d="M2 7h7m0 0L7 5m2 2l-2 2" />
            </svg>
          </button>
        </div>
      </div>
    </aside>
  );
}
