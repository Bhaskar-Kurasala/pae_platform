"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, MessageSquare, X } from "lucide-react";
import { useStudio } from "./studio-context";

export interface StuckBannerProps {
  /** Milliseconds of inactivity before the banner appears. Defaults to 10 minutes. */
  thresholdMs?: number;
}

const DEFAULT_THRESHOLD_MS = 10 * 60 * 1000;

export function StuckBanner({ thresholdMs = DEFAULT_THRESHOLD_MS }: StuckBannerProps) {
  const { code, hasRunOnce, running } = useStudio();
  const [showBanner, setShowBanner] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const lastActivityRef = useRef<number>(Date.now());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    lastActivityRef.current = Date.now();
    setShowBanner(false);
    setDismissed(false);
  }, [code, hasRunOnce, running]);

  // DISC-40 — read-only engagement counts as activity too. Scope listeners to
  // the studio surface (data-slot="studio") so they don't reset on unrelated
  // portal clicks elsewhere on the page.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const root =
      document.querySelector<HTMLElement>('[data-slot="studio"]') ?? document.body;
    function bump() {
      lastActivityRef.current = Date.now();
      setShowBanner(false);
    }
    root.addEventListener("pointerdown", bump);
    root.addEventListener("keydown", bump);
    root.addEventListener("wheel", bump, { passive: true });
    return () => {
      root.removeEventListener("pointerdown", bump);
      root.removeEventListener("keydown", bump);
      root.removeEventListener("wheel", bump);
    };
  }, []);

  useEffect(() => {
    if (dismissed) return;
    const check = () => {
      const idle = Date.now() - lastActivityRef.current;
      if (idle >= thresholdMs) {
        setShowBanner(true);
      } else {
        timerRef.current = setTimeout(check, thresholdMs - idle);
      }
    };
    timerRef.current = setTimeout(check, thresholdMs);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [thresholdMs, dismissed, code, hasRunOnce]);

  if (!showBanner || dismissed) return null;

  function handleAskTutor() {
    try {
      window.dispatchEvent(
        new CustomEvent("studio.stuck_ask_tutor", {
          detail: { code, reason: "stuck_10min" },
        }),
      );
    } catch {
      /* ignore */
    }
    setDismissed(true);
  }

  function handleDismiss() {
    try {
      window.dispatchEvent(new CustomEvent("studio.stuck_dismissed"));
    } catch {
      /* ignore */
    }
    setDismissed(true);
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-start gap-3 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-sm"
    >
      <AlertTriangle
        className="h-4 w-4 mt-0.5 text-amber-500 shrink-0"
        aria-hidden="true"
      />
      <div className="flex-1 min-w-0">
        <p className="font-medium text-foreground">Stuck for a while?</p>
        <p className="text-xs text-muted-foreground leading-relaxed">
          You haven't made progress in 10 minutes. Want the tutor to suggest a next
          step?
        </p>
      </div>
      <button
        type="button"
        onClick={handleAskTutor}
        className="shrink-0 inline-flex items-center gap-1.5 rounded-md bg-primary px-2.5 h-7 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors pointer-coarse:h-11 pointer-coarse:min-w-11 pointer-coarse:px-3 pointer-coarse:text-sm"
      >
        <MessageSquare className="h-3 w-3" aria-hidden="true" />
        Ask the tutor
      </button>
      <button
        type="button"
        onClick={handleDismiss}
        aria-label="Dismiss stuck banner"
        className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-foreground/5 hover:text-foreground transition-colors pointer-coarse:h-11 pointer-coarse:w-11 pointer-coarse:flex pointer-coarse:items-center pointer-coarse:justify-center"
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}
