"use client";

import { useState } from "react";
import { Brain, Check, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDueCards, useReviewCard } from "@/lib/hooks/use-srs";

const QUALITY_BUTTONS: { quality: number; label: string; hint: string; tone: string }[] = [
  {
    quality: 1,
    label: "Forgot",
    hint: "Wrong / blank",
    tone: "border-rose-500/30 bg-rose-500/10 text-rose-400 hover:bg-rose-500/15",
  },
  {
    quality: 3,
    label: "Hard",
    hint: "Right, with effort",
    tone: "border-amber-500/30 bg-amber-500/10 text-amber-400 hover:bg-amber-500/15",
  },
  {
    quality: 5,
    label: "Easy",
    hint: "Instant recall",
    tone: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/15",
  },
];

function formatInterval(days: number): string {
  if (days < 1) return "soon";
  if (days === 1) return "tomorrow";
  if (days < 7) return `${days}d`;
  if (days < 30) return `${Math.round(days / 7)}w`;
  return `${Math.round(days / 30)}mo`;
}

export function TodayReview() {
  const [index, setIndex] = useState(0);
  const [showPrompt, setShowPrompt] = useState(true);
  const { data: cards, isLoading } = useDueCards();
  const review = useReviewCard();

  if (isLoading) {
    return (
      <article className="rounded-2xl border border-foreground/10 bg-card p-5 md:p-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Loading review queue…
        </div>
      </article>
    );
  }

  if (!cards || cards.length === 0) {
    return (
      <article className="rounded-2xl border border-foreground/10 bg-card p-5 md:p-6">
        <div className="flex items-start gap-3">
          <div className="shrink-0 rounded-xl bg-foreground/[0.04] p-2.5">
            <Brain className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold leading-snug">
              Nothing due for review.
            </h2>
            <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
              Your spaced-repetition queue is clear. Concepts will resurface here
              as they reach their next review interval.
            </p>
          </div>
        </div>
      </article>
    );
  }

  const current = cards[Math.min(index, cards.length - 1)];
  const remaining = cards.length - index;
  const done = index >= cards.length;

  function handleReview(quality: number) {
    if (!current || review.isPending) return;
    review.mutate(
      { cardId: current.id, quality },
      {
        onSuccess: () => {
          setIndex((i) => i + 1);
          setShowPrompt(true);
        },
      },
    );
  }

  if (done) {
    return (
      <article className="rounded-2xl border border-foreground/10 bg-card p-5 md:p-6">
        <div className="flex items-start gap-3">
          <div className="shrink-0 rounded-xl bg-emerald-500/10 p-2.5">
            <Check className="h-4 w-4 text-emerald-400" aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold leading-snug">
              Queue cleared.
            </h2>
            <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
              You reviewed {cards.length} {cards.length === 1 ? "concept" : "concepts"}.
              Next batch surfaces when intervals elapse.
            </p>
          </div>
        </div>
      </article>
    );
  }

  return (
    <article
      aria-labelledby="review-heading"
      className="rounded-2xl border border-foreground/10 bg-card p-5 md:p-6"
    >
      <div className="flex items-start gap-3">
        <div className="shrink-0 rounded-xl bg-foreground/[0.04] p-2.5">
          <Brain className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center rounded-full border border-foreground/10 bg-foreground/[0.04] px-2 h-5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Spaced review
            </span>
            <span className="text-[11px] text-muted-foreground tabular-nums">
              {remaining} due
            </span>
          </div>
          <h2
            id="review-heading"
            className="mt-2 text-base font-semibold leading-snug"
          >
            {current.concept_key}
          </h2>

          {showPrompt && current.prompt ? (
            <p className="mt-2 text-sm text-foreground/80 leading-relaxed">
              {current.prompt}
            </p>
          ) : null}

          <div className="mt-4 grid grid-cols-3 gap-2">
            {QUALITY_BUTTONS.map((b) => (
              <button
                key={b.quality}
                type="button"
                onClick={() => handleReview(b.quality)}
                disabled={review.isPending}
                aria-label={`Rate recall as ${b.label}`}
                className={cn(
                  "flex flex-col items-start rounded-lg border px-3 py-2 text-left transition disabled:cursor-not-allowed disabled:opacity-50",
                  b.tone,
                )}
              >
                <span className="text-sm font-semibold">{b.label}</span>
                <span className="text-[11px] opacity-80">{b.hint}</span>
              </button>
            ))}
          </div>

          {review.isError ? (
            <p className="mt-3 inline-flex items-center gap-1 text-xs text-rose-400">
              <X className="h-3 w-3" aria-hidden="true" />
              {review.error.message}
            </p>
          ) : null}

          <p className="mt-3 text-[11px] text-muted-foreground/80">
            Current interval: {current.interval_days === 0 ? "new" : formatInterval(current.interval_days)}
            {" · "}
            Reviews: {current.repetitions}
          </p>
        </div>
      </div>
    </article>
  );
}
