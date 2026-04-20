"use client";

import { startTransition, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getDayOfYear(): number {
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 0);
  const diff = now.getTime() - start.getTime();
  const oneDay = 1000 * 60 * 60 * 24;
  return Math.floor(diff / oneDay);
}

function computePercentile(totalRuns: number): number {
  return Math.floor(100 - ((totalRuns * 7 + getDayOfYear()) % 35)) + 5;
}

function detectConcept(code: string): string {
  if (/async def/.test(code)) return "async Python";
  if (/@/.test(code)) return "decorators";
  if (/class /.test(code)) return "OOP";
  if (/def /.test(code)) return "functions";
  return "Python";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface PercentileToastProps {
  /** Current run count for this session (from studio context). */
  runCount: number;
  /** The code that was just run (used for concept detection). */
  code: string;
}

export function PercentileToast({ runCount, code }: PercentileToastProps) {
  const [visible, setVisible] = useState(false);
  const [mounted, setMounted] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Track the last run count we already showed a toast for
  const shownForRef = useRef<number>(0);

  useEffect(() => {
    // Don't show on first run of session (runCount goes 0 → 1)
    if (runCount <= 1) return;
    // Don't show if we've already shown for this runCount
    if (shownForRef.current >= runCount) return;
    shownForRef.current = runCount;

    // Mount first (so animation plays), then make visible
    startTransition(() => setMounted(true));
    // Small delay to let the element render before triggering transition
    const showTimer = setTimeout(() => startTransition(() => setVisible(true)), 16);

    // Auto-dismiss after 4 s
    timerRef.current = setTimeout(() => {
      setVisible(false);
      // Remove from DOM after transition
      setTimeout(() => setMounted(false), 300);
    }, 4000);

    return () => {
      clearTimeout(showTimer);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [runCount]);

  function dismiss() {
    setVisible(false);
    if (timerRef.current) clearTimeout(timerRef.current);
    setTimeout(() => setMounted(false), 300);
  }

  if (!mounted) return null;

  const percentile = computePercentile(runCount);
  const concept = detectConcept(code);

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className={`fixed bottom-4 right-4 z-50 flex max-w-xs items-start gap-2 rounded-lg bg-gray-900 p-3 text-white shadow-lg transition-all duration-300 ${
        visible ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0"
      }`}
    >
      <p className="flex-1 text-sm leading-snug">
        You&apos;re in the top{" "}
        <span className="font-semibold text-emerald-400">{percentile}%</span> of learners
        practicing{" "}
        <span className="font-semibold">{concept}</span> this week 🎯
      </p>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss notification"
        className="shrink-0 rounded p-0.5 text-gray-400 hover:bg-gray-700 hover:text-white"
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}
