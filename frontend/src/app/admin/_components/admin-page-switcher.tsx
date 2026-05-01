"use client";

/**
 * <AdminPageSwitcher> — single source of truth for admin navigation.
 *
 * Replaces the legacy AdminLayout sidebar (8 destinations stacked
 * vertically) with a click-to-open dropdown pill in the topbar.
 * Pill label shows the current page name + ▾ chevron, doubling as a
 * breadcrumb. Cmd+K (Ctrl+K on Windows) opens the same dropdown for
 * power users.
 *
 * Destinations are grouped Operate/System so admins can scan them as
 * an org map rather than a flat list. Each item supports an optional
 * meta-state badge (e.g. "20 healthy", "4 unread") for at-a-glance
 * status without leaving the cockpit.
 *
 * Theme tokens come from v8.css palette (--ink, --line, etc.) so this
 * pill reads as part of the same surface as the cockpit topbar.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BookOpen,
  ChevronDown,
  ClipboardList,
  Flame,
  GraduationCap,
  LayoutDashboard,
  MessageSquare,
  Users,
  Zap,
} from "lucide-react";

interface SwitcherItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  meta?: string;
}

interface SwitcherGroup {
  label: string;
  items: SwitcherItem[];
}

const GROUPS: SwitcherGroup[] = [
  {
    label: "Operate",
    items: [
      { href: "/admin", label: "Cockpit", icon: LayoutDashboard },
      { href: "/admin/students", label: "Students", icon: Users },
      { href: "/admin/content", label: "Content", icon: Flame },
      { href: "/admin/feedback", label: "Feedback", icon: MessageSquare },
      { href: "/admin/courses", label: "Courses", icon: GraduationCap },
    ],
  },
  {
    label: "System",
    items: [
      { href: "/admin/agents", label: "Agents", icon: Zap },
      { href: "/admin/audit-log", label: "Audit log", icon: ClipboardList },
    ],
  },
];

const ALL_ITEMS = GROUPS.flatMap((g) => g.items);

function findCurrent(pathname: string): SwitcherItem {
  // Longest prefix match — "/admin/students/abc" picks the Students
  // entry, not the cockpit.
  let best: SwitcherItem = ALL_ITEMS[0];
  let bestLen = 0;
  for (const item of ALL_ITEMS) {
    if (
      (pathname === item.href || pathname.startsWith(item.href + "/")) &&
      item.href.length > bestLen
    ) {
      best = item;
      bestLen = item.href.length;
    }
  }
  return best;
}

export function AdminPageSwitcher() {
  const pathname = usePathname() ?? "/admin";
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const current = findCurrent(pathname);

  // Close on outside click + Esc.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Cmd+K / Ctrl+K toggles the switcher — same combo the legacy
  // sidebar advertised, now wired to the actual command palette.
  useEffect(() => {
    const onShortcut = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, []);

  return (
    <div className="cf-switcher" ref={containerRef}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="cf-switcher-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Switch admin view"
      >
        <current.icon className="cf-switcher-trigger-icon" />
        <span className="cf-switcher-trigger-label">{current.label}</span>
        <ChevronDown className="cf-switcher-trigger-chev" />
        <span className="cf-switcher-kbd" aria-hidden="true">
          ⌘K
        </span>
      </button>
      {open ? (
        <div className="cf-switcher-popup" role="listbox">
          {GROUPS.map((group) => (
            <div key={group.label} className="cf-switcher-group">
              <div className="cf-switcher-group-label">{group.label}</div>
              <ul className="cf-switcher-list">
                {group.items.map((item) => {
                  const isActive = item.href === current.href;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        role="option"
                        aria-selected={isActive}
                        className={`cf-switcher-item${
                          isActive ? " cf-switcher-item-active" : ""
                        }`}
                        onClick={() => {
                          setOpen(false);
                          router.push(item.href);
                        }}
                      >
                        <item.icon className="cf-switcher-item-icon" />
                        <span className="cf-switcher-item-label">
                          {item.label}
                        </span>
                        {item.meta ? (
                          <span className="cf-switcher-item-meta">
                            {item.meta}
                          </span>
                        ) : null}
                        {isActive ? (
                          <span
                            className="cf-switcher-item-current"
                            aria-hidden="true"
                          >
                            ●
                          </span>
                        ) : null}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Inline style sheet for the switcher. Token values mirror the
 * v8.css palette so the popup feels native to whichever cockpit
 * theme the operator chose. Lives in a <style> tag rather than a
 * CSS module so we can interpolate the active-theme tokens at
 * render time, the same approach the student-detail-modal uses.
 */
export function AdminPageSwitcherStyles({
  pageTheme,
}: {
  pageTheme: "light" | "dark";
}) {
  const isDark = pageTheme === "dark";
  const ink = isDark ? "#f0ece1" : "#10120e";
  const muted = isDark ? "#9a9588" : "#686559";
  const muted2 = isDark ? "#7a7568" : "#8f897d";
  const line = isDark ? "#2c3830" : "#dbd1bf";
  const accent = isDark ? "#73c79c" : "#244f39";
  const accentSoft = isDark ? "rgba(143,214,177,0.14)" : "#e5efe8";
  const eyebrow = isDark ? "#8fd6b1" : "#356d50";
  const triggerBg = isDark
    ? "rgba(255,255,255,0.04)"
    : "rgba(255,255,255,0.7)";
  const triggerHover = isDark
    ? "rgba(255,255,255,0.07)"
    : "rgba(255,255,255,0.9)";
  const popupBg = isDark
    ? "rgba(20, 28, 22, 0.95)"
    : "rgba(255, 255, 255, 0.96)";
  const popupShadow = isDark
    ? "0 24px 60px rgba(0, 0, 0, 0.55)"
    : "0 24px 60px rgba(21, 19, 13, 0.14)";

  return (
    <style>{`
      .cf-switcher {
        position: relative;
        display: inline-block;
      }
      .cf-switcher-trigger {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        height: 34px;
        padding: 0 12px 0 10px;
        background: ${triggerBg};
        border: 1px solid ${line};
        border-radius: 999px;
        color: ${ink};
        font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
        font-size: 13px;
        font-weight: 500;
        letter-spacing: -0.005em;
        backdrop-filter: blur(6px);
        -webkit-backdrop-filter: blur(6px);
        transition:
          background .18s cubic-bezier(.2,.8,.2,1),
          border-color .18s cubic-bezier(.2,.8,.2,1);
        cursor: pointer;
      }
      .cf-switcher-trigger:hover {
        background: ${triggerHover};
        border-color: ${accent};
      }
      .cf-switcher-trigger-icon {
        width: 14px;
        height: 14px;
        color: ${eyebrow};
      }
      .cf-switcher-trigger-label {
        line-height: 1;
      }
      .cf-switcher-trigger-chev {
        width: 14px;
        height: 14px;
        color: ${muted};
        margin-left: 2px;
      }
      .cf-switcher-kbd {
        font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
        font-size: 10px;
        letter-spacing: 0.04em;
        color: ${muted2};
        padding: 2px 5px;
        background: ${
          isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)"
        };
        border: 1px solid ${line};
        border-radius: 5px;
        margin-left: 4px;
      }
      .cf-switcher-popup {
        position: absolute;
        top: calc(100% + 8px);
        left: 0;
        min-width: 280px;
        background: ${popupBg};
        border: 1px solid ${line};
        border-radius: 14px;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        box-shadow: ${popupShadow};
        padding: 8px;
        z-index: 60;
        animation: cfSwitcherPop .18s cubic-bezier(.2,.8,.2,1) both;
      }
      @keyframes cfSwitcherPop {
        from { opacity: 0; transform: translateY(-4px) scale(.98); }
        to { opacity: 1; transform: translateY(0) scale(1); }
      }
      .cf-switcher-group {
        padding: 6px 4px;
      }
      .cf-switcher-group + .cf-switcher-group {
        border-top: 1px solid ${line};
        margin-top: 4px;
      }
      .cf-switcher-group-label {
        font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
        font-size: 9.5px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        font-weight: 700;
        color: ${eyebrow};
        padding: 4px 8px 6px;
      }
      .cf-switcher-list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 1px;
      }
      .cf-switcher-item {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 10px;
        border-radius: 10px;
        color: ${ink};
        text-decoration: none;
        font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
        font-size: 14px;
        font-weight: 500;
        letter-spacing: -0.005em;
        transition:
          background .14s cubic-bezier(.2,.8,.2,1),
          color .14s cubic-bezier(.2,.8,.2,1);
      }
      .cf-switcher-item:hover {
        background: ${accentSoft};
      }
      .cf-switcher-item-active {
        background: ${accentSoft};
        color: ${eyebrow};
      }
      .cf-switcher-item-icon {
        width: 15px;
        height: 15px;
        color: ${eyebrow};
        flex-shrink: 0;
      }
      .cf-switcher-item-label {
        flex: 1;
      }
      .cf-switcher-item-meta {
        font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
        font-size: 10.5px;
        letter-spacing: 0.04em;
        color: ${muted2};
      }
      .cf-switcher-item-current {
        color: ${eyebrow};
        font-size: 8px;
      }
    `}</style>
  );
}
