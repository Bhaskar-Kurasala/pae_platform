"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";

/**
 * iOS-style sliding pill that mirrors the v8 sidebar theme toggle.
 * next-themes drives the actual theme; this just controls the UI.
 */
export function V8ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const isDark = mounted && resolvedTheme === "dark";
  const next = isDark ? "light" : "dark";

  function setMode(mode: "light" | "dark") {
    setTheme(mode);
    document.documentElement.setAttribute(
      "data-theme",
      mode === "dark" ? "dark" : "light",
    );
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
    <div
      className="theme-toggle"
      role="switch"
      aria-checked={isDark}
      aria-label={`Switch to ${next} mode`}
      tabIndex={0}
      onClick={() => setMode(next)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setMode(next);
        }
      }}
    >
      <button
        type="button"
        className={`theme-opt${!isDark ? " active" : ""}`}
        aria-label="Light theme"
        tabIndex={-1}
        onClick={(e) => {
          e.stopPropagation();
          setMode("light");
        }}
      >
        <svg
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.6}
          strokeLinecap="round"
          aria-hidden
        >
          <circle cx={7} cy={7} r={2.4} />
          <path d="M7 1v1.4M7 11.6V13M1 7h1.4M11.6 7H13M2.6 2.6l1 1M10.4 10.4l1 1M2.6 11.4l1-1M10.4 3.6l1-1" />
        </svg>
      </button>
      <button
        type="button"
        className={`theme-opt${isDark ? " active" : ""}`}
        aria-label="Dark theme"
        tabIndex={-1}
        onClick={(e) => {
          e.stopPropagation();
          setMode("dark");
        }}
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
          <path d="M11.5 8.5A4.5 4.5 0 015.5 2.5a5 5 0 106 6z" />
        </svg>
      </button>
    </div>
  );
}
