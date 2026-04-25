"use client";

import { createContext, useContext, useMemo, useState } from "react";
import { useEffect } from "react";

export interface V8Chip {
  label: string;
  variant?: "forest" | "gold" | "ink" | "neutral";
}

export interface V8TopbarState {
  eyebrow: string;
  /** May contain inline `<i>` tags for serif italic emphasis */
  titleHtml: string;
  chips: ReadonlyArray<V8Chip>;
  /** Session progress 0–100 for the under-topbar shimmer bar. */
  progress: number;
}

const DEFAULT_STATE: V8TopbarState = {
  eyebrow: "",
  titleHtml: "",
  chips: [],
  progress: 34,
};

interface V8TopbarContextValue {
  state: V8TopbarState;
  setState: (next: Partial<V8TopbarState>) => void;
}

const V8TopbarContext = createContext<V8TopbarContextValue | null>(null);

export function V8TopbarProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<V8TopbarState>(DEFAULT_STATE);
  const value = useMemo<V8TopbarContextValue>(
    () => ({
      state,
      setState: (next) => setState((prev) => ({ ...prev, ...next })),
    }),
    [state],
  );
  return <V8TopbarContext.Provider value={value}>{children}</V8TopbarContext.Provider>;
}

export function useV8Topbar(): V8TopbarContextValue {
  const ctx = useContext(V8TopbarContext);
  if (!ctx) {
    // Before the provider mounts, return a no-op so SSR doesn't crash.
    return { state: DEFAULT_STATE, setState: () => undefined };
  }
  return ctx;
}

/**
 * Per-page hook to set topbar state. Intentionally fires once on mount and
 * whenever the inputs change (callers should keep them stable or use a
 * dedicated component to avoid unnecessary re-renders).
 */
export function useSetV8Topbar(state: Partial<V8TopbarState>): void {
  const { setState } = useV8Topbar();
  const key = JSON.stringify(state);
  useEffect(() => {
    setState(state);
    // We compare on serialized state to avoid object identity churn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}
