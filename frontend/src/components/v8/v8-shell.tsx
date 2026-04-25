"use client";

import { useEffect } from "react";
import { V8Sidebar } from "./v8-sidebar";
import { V8Topbar } from "./v8-topbar";
import { V8TopbarProvider } from "./v8-topbar-context";
import { V8Reveal } from "./v8-reveal";
import { V8ToastHost } from "./v8-toast";

/**
 * Full v8 portal shell: sidebar + topbar + main scroll container.
 * Wraps children in the topbar context provider so individual pages can
 * push eyebrow/title/chips/progress without prop drilling.
 *
 * The CSS opt-in class `.v8-portal-shell` scopes v8 body-level rules
 * (background, font, hidden overflow) to this subtree only — the public
 * landing pages and other surfaces keep their existing chrome.
 */
export function V8Shell({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    // Initialize the data-theme attribute from saved theme so v8 selectors
    // apply on first paint (next-themes drives the .dark class; we mirror
    // it onto the data-theme attribute the v8 stylesheet expects).
    if (typeof window === "undefined") return;
    const root = document.documentElement;
    const isDark = root.classList.contains("dark");
    root.setAttribute("data-theme", isDark ? "dark" : "light");
    const observer = new MutationObserver(() => {
      const dark = root.classList.contains("dark");
      root.setAttribute("data-theme", dark ? "dark" : "light");
    });
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  return (
    <V8TopbarProvider>
      <div className="app v8-portal-shell">
        <V8Sidebar />
        <main className="main">
          <V8Topbar />
          {children}
        </main>
      </div>
      <V8Reveal />
      <V8ToastHost />
    </V8TopbarProvider>
  );
}
