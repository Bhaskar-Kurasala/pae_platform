"use client";

import { useSyncExternalStore } from "react";

/**
 * SSR-safe media query hook backed by useSyncExternalStore.
 * Returns `false` on the server; resolves to the real match on the client.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === "undefined") return () => {};
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    () => {
      if (typeof window === "undefined") return false;
      return window.matchMedia(query).matches;
    },
    () => false,
  );
}

/** true on screens ≥ 640px (Tailwind sm breakpoint). */
export function useIsDesktop(): boolean {
  return useMediaQuery("(min-width: 640px)");
}
