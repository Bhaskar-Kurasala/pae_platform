"use client";

import { useCallback, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  readinessEventsApi,
  type RecordEventInput,
  type WorkspaceEventSummaryResponse,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

const BATCH_LIMIT = 20;
const FLUSH_INTERVAL_MS = 5_000;

/**
 * Best-effort telemetry buffer for workspace events.
 *
 * Why a singleton: every Job Readiness sub-view fires events; a single buffer
 * avoids per-component timers and lets us flush on `beforeunload` once.
 *
 * SSR-safe: `window`/`document` access is only inside methods, which are
 * never called during module evaluation.
 */
export class WorkspaceEventBuffer {
  private events: RecordEventInput[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;
  private listenersBound = false;
  // Test seam: lets us inject a stub in unit tests instead of real network I/O.
  private sender: (events: RecordEventInput[]) => Promise<unknown>;

  constructor(
    sender: (events: RecordEventInput[]) => Promise<unknown> = (events) =>
      readinessEventsApi.record(events),
  ) {
    this.sender = sender;
  }

  /** Append an event. Triggers an immediate flush if the batch fills up. */
  push(event: RecordEventInput): void {
    this.events.push(event);
    if (this.events.length >= BATCH_LIMIT) {
      void this.flush();
    }
  }

  /** Send everything currently buffered. Failures are silent. */
  async flush(): Promise<void> {
    if (this.events.length === 0) return;
    const batch = this.events;
    this.events = [];
    try {
      await this.sender(batch);
    } catch {
      // Telemetry is best-effort — never let a failed flush throw upward
      // or be observable in the UI. We deliberately do NOT requeue: a stuck
      // backend could otherwise grow the buffer without bound.
    }
  }

  /** Idempotent: starts the periodic flush + binds page-lifecycle listeners. */
  startAutoFlushTimer(): void {
    if (typeof window === "undefined") return;
    if (this.timer === null) {
      this.timer = setInterval(() => {
        void this.flush();
      }, FLUSH_INTERVAL_MS);
    }
    if (!this.listenersBound) {
      window.addEventListener("beforeunload", this.handleBeforeUnload);
      document.addEventListener(
        "visibilitychange",
        this.handleVisibilityChange,
      );
      this.listenersBound = true;
    }
  }

  /** Tear down — primarily for tests; the singleton normally lives forever. */
  stopAutoFlushTimer(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
    if (this.listenersBound && typeof window !== "undefined") {
      window.removeEventListener("beforeunload", this.handleBeforeUnload);
      document.removeEventListener(
        "visibilitychange",
        this.handleVisibilityChange,
      );
      this.listenersBound = false;
    }
  }

  /** Test-only helper: read current buffer length without exposing the array. */
  get size(): number {
    return this.events.length;
  }

  private handleBeforeUnload = (): void => {
    void this.flush();
  };

  private handleVisibilityChange = (): void => {
    if (
      typeof document !== "undefined" &&
      document.visibilityState === "hidden"
    ) {
      void this.flush();
    }
  };
}

// Module-level singleton (SSR-safe — no DOM access at construction time).
export const workspaceEventBuffer = new WorkspaceEventBuffer();

export function useRecordWorkspaceEvent() {
  useEffect(() => {
    workspaceEventBuffer.startAutoFlushTimer();
  }, []);

  return useCallback(
    (
      view: string,
      event: string,
      payload?: Record<string, unknown>,
    ): void => {
      workspaceEventBuffer.push({ view, event, payload });
    },
    [],
  );
}

export function useFlushWorkspaceEvents() {
  return useCallback(async (): Promise<void> => {
    await workspaceEventBuffer.flush();
  }, []);
}

export function useWorkspaceEventSummary(sinceDays: number = 7) {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<WorkspaceEventSummaryResponse>({
    queryKey: ["readiness", "events", "summary", sinceDays],
    queryFn: () =>
      readinessEventsApi.summary({ since_days: sinceDays }),
    enabled: isAuthed,
    staleTime: 30_000,
  });
}
