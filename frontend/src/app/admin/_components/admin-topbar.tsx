"use client";

/**
 * <AdminTopbar> — single, shared top bar for every /admin route.
 *
 * Replaces the legacy <AdminLayout> sidebar entirely. One nav system
 * across the whole admin section, no surface-switch when an operator
 * clicks from cockpit → students → audit log.
 *
 * Layout (left → right):
 *   • CareerForge brand + Admin tag
 *   • Page switcher pill (current page + ▾, Cmd+K opens it)
 *   • Search box
 *   • Live indicator (cockpit only — passes liveLabel prop)
 *   • Theme toggle
 *   • Avatar menu (identity + sign out)
 *
 * The styles ride the v8.css palette via CSS variables so the topbar
 * inherits the same warm-cream / deep-forest tones as /path. We
 * intentionally don't use the cockpit's console.module.css here
 * because that file's classes assume a specific page-shell wrapper —
 * the topbar should be reusable across every admin route.
 */

import { useEffect } from "react";
import Link from "next/link";
import { Moon, Search, Sun } from "lucide-react";
import { useAdminTheme } from "@/lib/hooks/use-admin-theme";
import { AdminAvatarMenu } from "./admin-avatar-menu";
import {
  AdminPageSwitcher,
  AdminPageSwitcherStyles,
} from "./admin-page-switcher";

interface AdminTopbarProps {
  /**
   * Optional live-sync indicator — only the cockpit has a meaningful
   * "synced HH:MM" timestamp to surface, so it's opt-in via prop.
   */
  liveLabel?: string;
  /**
   * Optional search-input change handler. When omitted the search
   * box is rendered as a non-interactive shell. The cockpit wires
   * this to its in-memory roster filter.
   */
  onSearchChange?: (value: string) => void;
  /**
   * Optional search placeholder — defaults to a generic prompt.
   */
  searchPlaceholder?: string;
}

export function AdminTopbar({
  liveLabel,
  onSearchChange,
  searchPlaceholder = "Search students, capstones, or events…",
}: AdminTopbarProps) {
  const { theme, toggleTheme } = useAdminTheme();

  // Keep <html> in sync with the chosen theme so any cascading dark
  // tokens (used by base shadcn primitives we still depend on) read
  // the right side of the palette.
  useEffect(() => {
    const html = document.documentElement;
    if (theme === "dark") html.classList.add("dark");
    else html.classList.remove("dark");
  }, [theme]);

  return (
    <header className="cf-topbar" data-theme={theme}>
      <Link href="/admin" className="cf-topbar-brand" aria-label="Admin home">
        <span className="cf-topbar-brand-text">
          Career<i>Forge</i>
        </span>
        <span className="cf-topbar-brand-tag">Admin</span>
      </Link>
      <span className="cf-topbar-divider" aria-hidden="true" />
      <AdminPageSwitcher />
      <span className="cf-topbar-divider" aria-hidden="true" />
      <div className="cf-topbar-search">
        <Search className="cf-topbar-search-icon" />
        <input
          type="search"
          aria-label="Search admin"
          placeholder={searchPlaceholder}
          onChange={(e) => onSearchChange?.(e.target.value)}
        />
      </div>
      <span className="cf-topbar-spacer" />
      {liveLabel ? (
        <div className="cf-topbar-live" role="status" aria-live="polite">
          <span className="cf-topbar-live-dot" />
          {liveLabel}
        </div>
      ) : null}
      <button
        type="button"
        className="cf-topbar-theme"
        aria-label={
          theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
        }
        onClick={toggleTheme}
      >
        {theme === "dark" ? (
          <Moon className="cf-topbar-theme-icon" />
        ) : (
          <Sun className="cf-topbar-theme-icon" />
        )}
      </button>
      <AdminAvatarMenu pageTheme={theme} />
      <AdminPageSwitcherStyles pageTheme={theme} />
      <AdminTopbarStyles pageTheme={theme} />
    </header>
  );
}

function AdminTopbarStyles({
  pageTheme,
}: {
  pageTheme: "light" | "dark";
}) {
  const isDark = pageTheme === "dark";
  // Same palette the v8 dark/light themes use, verbatim.
  const ink = isDark ? "#f0ece1" : "#10120e";
  const muted = isDark ? "#9a9588" : "#686559";
  const muted2 = isDark ? "#7a7568" : "#8f897d";
  const line = isDark ? "#2c3830" : "#dbd1bf";
  const eyebrow = isDark ? "#8fd6b1" : "#356d50";
  const topbarBg = isDark
    ? "linear-gradient(180deg, rgba(15, 22, 18, 0.92), rgba(11, 17, 14, 0.88))"
    : "linear-gradient(180deg, rgba(255, 252, 245, 0.92), rgba(251, 247, 238, 0.88))";
  const searchBg = isDark
    ? "rgba(255, 255, 255, 0.04)"
    : "rgba(255, 255, 255, 0.7)";
  const themeBg = searchBg;
  const themeHover = isDark
    ? "rgba(255, 255, 255, 0.07)"
    : "rgba(255, 255, 255, 0.95)";

  return (
    <style>{`
      .cf-topbar {
        position: sticky;
        top: 0;
        z-index: 50;
        display: flex;
        align-items: center;
        gap: 14px;
        padding: 10px 18px;
        background: ${topbarBg};
        backdrop-filter: blur(14px) saturate(140%);
        -webkit-backdrop-filter: blur(14px) saturate(140%);
        border-bottom: 1px solid ${line};
        color: ${ink};
        font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
      }
      .cf-topbar-brand {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        text-decoration: none;
        color: ${ink};
      }
      .cf-topbar-brand-text {
        font-family: var(--font-fraunces), Georgia, serif;
        font-size: 18px;
        font-weight: 500;
        letter-spacing: -0.025em;
      }
      .cf-topbar-brand-text i {
        font-style: italic;
        color: ${eyebrow};
      }
      .cf-topbar-brand-tag {
        font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
        font-size: 9.5px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        font-weight: 700;
        color: ${eyebrow};
        padding: 3px 7px;
        border: 1px solid ${line};
        border-radius: 5px;
        background: ${
          isDark ? "rgba(143,214,177,0.08)" : "rgba(78,148,112,0.06)"
        };
      }
      .cf-topbar-divider {
        width: 1px;
        height: 20px;
        background: ${line};
      }
      .cf-topbar-search {
        position: relative;
        display: inline-flex;
        align-items: center;
        flex: 0 1 360px;
        max-width: 420px;
      }
      .cf-topbar-search-icon {
        position: absolute;
        left: 10px;
        width: 14px;
        height: 14px;
        color: ${muted2};
        pointer-events: none;
      }
      .cf-topbar-search input {
        width: 100%;
        height: 32px;
        padding: 0 12px 0 30px;
        background: ${searchBg};
        border: 1px solid ${line};
        border-radius: 999px;
        color: ${ink};
        font-family: inherit;
        font-size: 13px;
        letter-spacing: -0.005em;
        transition: border-color .18s cubic-bezier(.2,.8,.2,1), background .18s cubic-bezier(.2,.8,.2,1);
      }
      .cf-topbar-search input::placeholder {
        color: ${muted2};
      }
      .cf-topbar-search input:focus {
        outline: none;
        border-color: ${eyebrow};
        background: ${themeHover};
      }
      .cf-topbar-spacer {
        flex: 1;
      }
      .cf-topbar-live {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        padding: 4px 10px;
        background: ${
          isDark ? "rgba(143,214,177,0.10)" : "rgba(78,148,112,0.08)"
        };
        border: 1px solid ${
          isDark ? "rgba(143,214,177,0.22)" : "rgba(78,148,112,0.20)"
        };
        border-radius: 999px;
        font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
        font-size: 10.5px;
        letter-spacing: 0.10em;
        text-transform: uppercase;
        font-weight: 600;
        color: ${eyebrow};
      }
      .cf-topbar-live-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: ${eyebrow};
        box-shadow: 0 0 0 4px ${
          isDark ? "rgba(143,214,177,0.18)" : "rgba(78,148,112,0.18)"
        };
        animation: cfPulseDot 2.4s ease-in-out infinite;
      }
      @keyframes cfPulseDot {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.6; transform: scale(0.85); }
      }
      .cf-topbar-theme {
        display: inline-grid;
        place-items: center;
        width: 32px;
        height: 32px;
        background: ${themeBg};
        border: 1px solid ${line};
        border-radius: 999px;
        color: ${ink};
        cursor: pointer;
        transition: background .18s cubic-bezier(.2,.8,.2,1), border-color .18s cubic-bezier(.2,.8,.2,1);
      }
      .cf-topbar-theme:hover {
        background: ${themeHover};
        border-color: ${eyebrow};
      }
      .cf-topbar-theme-icon {
        width: 14px;
        height: 14px;
      }
      /* Hide some noisy elements on small screens to keep the bar
         scannable. Search shrinks first; live indicator + theme stay. */
      @media (max-width: 880px) {
        .cf-topbar-search { flex: 0 1 200px; }
        .cf-topbar-brand-tag { display: none; }
      }
      @media (max-width: 720px) {
        .cf-topbar-search { display: none; }
        .cf-topbar-divider { display: none; }
      }
    `}</style>
  );
}
