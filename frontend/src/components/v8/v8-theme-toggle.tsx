"use client";

import { useEffect, useSyncExternalStore } from "react";
import { useTheme } from "next-themes";
import { Moon, Sun } from "lucide-react";

function subscribe(): () => void {
  // No external store — useSyncExternalStore just gives us a deterministic
  // server snapshot ("mounted=false") and the post-hydration value ("true").
  return () => undefined;
}
function getSnapshot() {
  return true;
}
function getServerSnapshot() {
  return false;
}

/**
 * Single-icon circular theme toggle — mirrors the admin top-bar's
 * `.cf-topbar-theme` pattern. Shows Sun in light mode, Moon in dark,
 * click flips. Replaces the older iOS-style sliding pill so the
 * student sidebar and admin top bar speak the same visual language.
 */
export function V8ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const isDark = mounted && resolvedTheme === "dark";
  const next: "light" | "dark" = isDark ? "light" : "dark";

  function toggle() {
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
  }

  // Keep `data-theme` in sync with next-themes so v8.css selectors apply.
  useEffect(() => {
    if (!mounted) return;
    document.documentElement.setAttribute(
      "data-theme",
      isDark ? "dark" : "light",
    );
  }, [isDark, mounted]);

  return (
    <button
      type="button"
      className="v8-theme-btn"
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={toggle}
    >
      {isDark ? (
        <Moon className="v8-theme-btn-icon" aria-hidden />
      ) : (
        <Sun className="v8-theme-btn-icon" aria-hidden />
      )}
    </button>
  );
}
