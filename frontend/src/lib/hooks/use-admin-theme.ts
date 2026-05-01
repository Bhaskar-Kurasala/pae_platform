"use client";

/**
 * <useAdminTheme> — shared light/dark preference across every admin
 * surface (cockpit, slip-type roster, student detail modal).
 *
 * The /admin cockpit owns the theme toggle in its top bar, but other
 * admin pages (and portal-rendered popups like the student detail
 * modal) need to know the same value. Without this hook, an operator
 * who toggles dark mode on /admin and then clicks "See all 92" lands
 * on a hard-coded light page — and the modal opened from there
 * inherits light too, which jars against the cockpit they just left.
 *
 * Persisted in localStorage so the choice survives reload / new tab,
 * and broadcast via a CustomEvent so multiple components mounted on
 * the same page stay in sync without a global store.
 */

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "admin.theme";
const EVENT = "admin-theme-change";
type Theme = "light" | "dark";

function readStoredTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const raw = window.localStorage.getItem(STORAGE_KEY);
  return raw === "dark" ? "dark" : "light";
}

export function useAdminTheme(): {
  theme: Theme;
  setTheme: (next: Theme) => void;
  toggleTheme: () => void;
} {
  // SSR-safe initial value (always "light" on the server). The first
  // effect re-reads from storage so the client matches the operator's
  // saved preference.
  const [theme, setThemeState] = useState<Theme>("light");

  useEffect(() => {
    setThemeState(readStoredTheme());
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) {
        setThemeState(e.newValue === "dark" ? "dark" : "light");
      }
    };
    const onCustom = (e: Event) => {
      const ce = e as CustomEvent<Theme>;
      if (ce.detail === "dark" || ce.detail === "light") {
        setThemeState(ce.detail);
      }
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(EVENT, onCustom as EventListener);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(EVENT, onCustom as EventListener);
    };
  }, []);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, next);
      window.dispatchEvent(new CustomEvent<Theme>(EVENT, { detail: next }));
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "light" ? "dark" : "light");
  }, [theme, setTheme]);

  return { theme, setTheme, toggleTheme };
}
