"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  Info,
  Loader2,
  MessageSquareWarning,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  SeniorReview,
  SeniorReviewComment,
  SeniorReviewSeverity,
  SeniorReviewVerdict,
} from "@/lib/api-client";

const SEVERITY_STYLE: Record<
  SeniorReviewSeverity,
  { label: string; badge: string; Icon: typeof Info }
> = {
  nit: {
    label: "nit",
    badge:
      "bg-muted text-muted-foreground border border-border",
    Icon: Info,
  },
  suggestion: {
    label: "suggestion",
    badge:
      "bg-sky-500/10 text-sky-700 dark:text-sky-300 border border-sky-500/20",
    Icon: Info,
  },
  concern: {
    label: "concern",
    badge:
      "bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-500/20",
    Icon: AlertTriangle,
  },
  blocking: {
    label: "blocking",
    badge:
      "bg-red-500/10 text-red-700 dark:text-red-300 border border-red-500/20",
    Icon: AlertTriangle,
  },
};

const VERDICT_STYLE: Record<
  SeniorReviewVerdict,
  { label: string; pill: string; Icon: typeof Check }
> = {
  approve: {
    label: "Approved",
    pill: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
    Icon: Check,
  },
  request_changes: {
    label: "Changes requested",
    pill: "bg-red-500/15 text-red-700 dark:text-red-300",
    Icon: AlertTriangle,
  },
  comment: {
    label: "Comments",
    pill: "bg-muted text-muted-foreground",
    Icon: MessageSquareWarning,
  },
};

/** Typewriter interval in ms per character. Capped so total < 1500ms. */
const CHAR_INTERVAL_MS = 25;
const MAX_TYPEWRITER_MS = 1500;

function CommentRow({ comment }: { comment: SeniorReviewComment }) {
  const style = SEVERITY_STYLE[comment.severity];
  const Icon = style.Icon;
  return (
    <li className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider",
            style.badge,
          )}
        >
          <Icon className="h-3 w-3" aria-hidden="true" />
          {style.label}
        </span>
        <span className="font-mono text-[11px] text-muted-foreground">
          L{comment.line}
        </span>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-foreground">
        {comment.message}
      </p>
      {comment.suggested_change && (
        <pre className="mt-2 overflow-x-auto rounded-md bg-muted/60 p-2 text-[12px] font-mono text-foreground">
          {comment.suggested_change}
        </pre>
      )}
    </li>
  );
}

interface Props {
  open: boolean;
  loading: boolean;
  error: string | null;
  review: SeniorReview | null;
  onClose: () => void;
}

export function SeniorReviewPanel({
  open,
  loading,
  error,
  review,
  onClose,
}: Props) {
  // Reveal animation state
  const [verdictVisible, setVerdictVisible] = useState(false);
  const [displayedHeadline, setDisplayedHeadline] = useState("");
  const [headlineDone, setHeadlineDone] = useState(false);
  const [bodyVisible, setBodyVisible] = useState(false);
  const [nextStepVisible, setNextStepVisible] = useState(false);

  // Track which review we last animated so we don't re-animate on re-renders
  const animatedReviewRef = useRef<SeniorReview | null>(null);

  // Reset all reveal state when panel closes or a new request starts
  useEffect(() => {
    if (!open || loading) {
      setVerdictVisible(false);
      setDisplayedHeadline("");
      setHeadlineDone(false);
      setBodyVisible(false);
      setNextStepVisible(false);
      animatedReviewRef.current = null;
    }
  }, [open, loading]);

  // Trigger reveal sequence when review data arrives
  useEffect(() => {
    if (!review || animatedReviewRef.current === review) return;
    animatedReviewRef.current = review;

    // Phase 1: fade-in verdict pill (100ms delay)
    const verdictTimer = window.setTimeout(() => {
      setVerdictVisible(true);
    }, 100);

    // Phase 2: typewriter for headline, starting after verdict fades in
    const headline = review.headline;
    const charInterval = Math.min(
      CHAR_INTERVAL_MS,
      MAX_TYPEWRITER_MS / Math.max(headline.length, 1),
    );
    let charIndex = 0;

    const typewriterStart = window.setTimeout(() => {
      const interval = window.setInterval(() => {
        charIndex += 1;
        setDisplayedHeadline(headline.slice(0, charIndex));
        if (charIndex >= headline.length) {
          window.clearInterval(interval);
          setHeadlineDone(true);
        }
      }, charInterval);
    }, 300); // start typewriter 300ms after mount (after verdict begins fading in)

    // Phase 3 & 4: strengths + comments, then next step, timed off max typewriter duration
    const bodyDelay = 300 + Math.min(headline.length * charInterval, MAX_TYPEWRITER_MS) + 150;
    const nextStepDelay = bodyDelay + 300;

    const bodyTimer = window.setTimeout(() => setBodyVisible(true), bodyDelay);
    const nextStepTimer = window.setTimeout(() => setNextStepVisible(true), nextStepDelay);

    return () => {
      window.clearTimeout(verdictTimer);
      window.clearTimeout(typewriterStart);
      window.clearTimeout(bodyTimer);
      window.clearTimeout(nextStepTimer);
    };
  }, [review]);

  // Escape key closes panel
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const verdict = review ? VERDICT_STYLE[review.verdict] : null;

  return (
    <div className="fixed inset-0 z-50 flex">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className="relative ml-auto flex h-full w-full max-w-xl flex-col border-l border-border bg-background shadow-xl"
        role="dialog"
        aria-label="Senior engineer review"
      >
        <header className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Pair review
            </p>
            <h2 className="text-base font-semibold leading-tight">
              Senior engineer
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close review"
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {loading && (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
              <p className="text-sm text-muted-foreground">
                Reading your code…
              </p>
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-700 dark:text-red-300">
              {error}
            </div>
          )}

          {review && verdict && (
            <div className="space-y-5">
              {/* Phase 1: verdict pill fades in */}
              <div
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-opacity duration-300",
                  verdict.pill,
                  verdictVisible ? "opacity-100" : "opacity-0",
                )}
              >
                <verdict.Icon className="h-3.5 w-3.5" aria-hidden="true" />
                {verdict.label}
              </div>

              {/* Phase 2: headline typewriter */}
              <p
                className="text-base font-medium text-foreground"
                aria-live="polite"
                aria-label={headlineDone ? review.headline : undefined}
              >
                {displayedHeadline}
                {!headlineDone && (
                  <span
                    className="ml-px inline-block w-0.5 h-[1em] align-middle bg-foreground animate-pulse"
                    aria-hidden="true"
                  />
                )}
              </p>

              {/* Phase 3: strengths + comments fade in after headline */}
              <div
                className={cn(
                  "space-y-5 transition-opacity duration-500",
                  bodyVisible ? "opacity-100" : "opacity-0",
                )}
              >
                {review.strengths.length > 0 && (
                  <section>
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Strengths
                    </h3>
                    <ul className="mt-2 space-y-1.5">
                      {review.strengths.map((s, i) => (
                        <li
                          key={i}
                          className="flex gap-2 text-sm text-foreground/90"
                        >
                          <Check
                            className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400"
                            aria-hidden="true"
                          />
                          <span>{s}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                <section>
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Comments ({review.comments.length})
                  </h3>
                  {review.comments.length === 0 ? (
                    <p className="mt-2 text-sm text-muted-foreground">
                      No line-level comments.
                    </p>
                  ) : (
                    <ul className="mt-2 space-y-2">
                      {review.comments.map((c, i) => (
                        <CommentRow key={i} comment={c} />
                      ))}
                    </ul>
                  )}
                </section>
              </div>

              {/* Phase 4: next step fades in last */}
              <section
                className={cn(
                  "rounded-lg border border-primary/30 bg-primary/5 p-3 transition-opacity duration-500",
                  nextStepVisible ? "opacity-100" : "opacity-0",
                )}
              >
                <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-primary">
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                  Next step
                </div>
                <p className="mt-1.5 text-sm leading-relaxed text-foreground">
                  {review.next_step}
                </p>
              </section>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
