"use client";

/**
 * Impersonation store — admin "view as student" mode.
 *
 * When an admin clicks "View as student" in the admin console, we set
 * `target` here and persist it to sessionStorage (NOT localStorage)
 * so closing the tab automatically exits impersonation. This is a
 * deliberate safety choice: a forgotten impersonation should not
 * survive a browser restart.
 *
 * The api-client reads the target from this store on every request and
 * adds the `X-Impersonate-Student-Id` header. The backend gates on the
 * admin's JWT — even if a non-admin somehow set this store, the header
 * would be rejected at the dependency.
 *
 * Three React Query side-effects on enter/exit:
 *   - Reset the cache so previously-fetched admin-context data does
 *     not leak into the impersonated view (and vice-versa).
 *   - The portal screens re-fetch under the new identity.
 *   - The banner mounts/unmounts via useImpersonationStore.
 */

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export interface ImpersonationTarget {
  studentId: string;
  studentEmail: string;
  studentName: string;
  startedAt: string; // ISO timestamp
}

interface ImpersonationState {
  target: ImpersonationTarget | null;
  start: (target: Omit<ImpersonationTarget, "startedAt">) => void;
  stop: () => void;
}

export const useImpersonationStore = create<ImpersonationState>()(
  persist(
    (set) => ({
      target: null,
      start: (t) =>
        set({
          target: { ...t, startedAt: new Date().toISOString() },
        }),
      stop: () => set({ target: null }),
    }),
    {
      name: "pae-impersonation",
      // sessionStorage = closing the tab clears the impersonation state.
      // We never want a stale impersonation to ride a browser restart.
      storage: createJSONStorage(() =>
        typeof window !== "undefined"
          ? window.sessionStorage
          : (undefined as unknown as Storage),
      ),
    },
  ),
);

/**
 * Snapshot read for non-React contexts (the api-client request builder).
 * Reads sessionStorage directly to stay reactive even if the store hasn't
 * hydrated yet on the first request after a refresh.
 */
export function getImpersonationHeader(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem("pae-impersonation");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as {
      state?: { target?: ImpersonationTarget | null };
    };
    return parsed.state?.target?.studentId ?? null;
  } catch {
    return null;
  }
}
