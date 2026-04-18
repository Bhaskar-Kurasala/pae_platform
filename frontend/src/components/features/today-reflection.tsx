"use client";

import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check, Sparkles, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useMyReflectionToday,
  useUpsertReflection,
} from "@/lib/hooks/use-reflection";
import { toast } from "@/lib/toast";
import type { Mood } from "@/lib/api-client";

const MOODS: { value: Mood; label: string; emoji: string; color: string }[] = [
  { value: "blocked", label: "Blocked", emoji: "🧱", color: "bg-rose-500/10 text-rose-400 border-rose-500/20" },
  { value: "meh", label: "Meh", emoji: "😐", color: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
  { value: "steady", label: "Steady", emoji: "🚶", color: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
  { value: "flowing", label: "Flowing", emoji: "⚡", color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
];

export function TodayReflection() {
  const prefersReducedMotion = useReducedMotion();
  const { data: stored, isLoading } = useMyReflectionToday();
  const upsert = useUpsertReflection();

  const [mood, setMood] = useState<Mood | null>(null);
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);

  const showSaved = stored !== null && stored !== undefined && !editing;

  function handleSubmit() {
    if (!mood) return;
    upsert.mutate(
      { mood, note: note.trim() },
      {
        onSuccess: () => {
          setEditing(false);
          toast.success("Reflection logged", { duration: 2400 });
        },
        onError: () => {
          toast.error("Couldn't save reflection. Try again.");
        },
      },
    );
  }

  function handleEdit() {
    setMood(stored?.mood ?? null);
    setNote(stored?.note ?? "");
    setEditing(true);
  }

  if (isLoading) {
    return (
      <article
        className="rounded-2xl border border-foreground/10 bg-card p-5 md:p-6"
        aria-busy="true"
      >
        <div className="h-3 w-28 rounded bg-foreground/[0.06] animate-pulse" />
        <div className="mt-3 h-5 w-2/3 rounded bg-foreground/[0.06] animate-pulse" />
        <div className="mt-4 h-8 w-48 rounded-full bg-foreground/[0.06] animate-pulse" />
      </article>
    );
  }

  return (
    <article
      aria-labelledby="reflection-heading"
      className="rounded-2xl border border-foreground/10 bg-card p-5 md:p-6"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Daily reflection
          </p>
          <h2
            id="reflection-heading"
            className="mt-1.5 text-base font-semibold"
          >
            {showSaved
              ? "You checked in today"
              : "How does learning feel right now?"}
          </h2>
        </div>
        {showSaved && (
          <button
            type="button"
            onClick={handleEdit}
            className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-foreground/10 px-2.5 h-7 text-xs font-medium text-muted-foreground hover:text-foreground hover:border-foreground/20 transition-colors"
          >
            Edit
          </button>
        )}
      </div>

      <AnimatePresence mode="wait">
        {showSaved && stored ? (
          <motion.div
            key="saved"
            initial={prefersReducedMotion ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={prefersReducedMotion ? undefined : { opacity: 0, y: -6 }}
            transition={{ duration: 0.25 }}
            className="mt-4 flex items-start gap-3"
          >
            <div
              className={cn(
                "shrink-0 inline-flex items-center gap-1.5 rounded-full border px-3 h-7 text-xs font-medium",
                MOODS.find((m) => m.value === stored.mood)?.color,
              )}
            >
              <span aria-hidden="true">
                {MOODS.find((m) => m.value === stored.mood)?.emoji}
              </span>
              <span>
                {MOODS.find((m) => m.value === stored.mood)?.label}
              </span>
            </div>
            {stored.note && (
              <p className="text-sm text-muted-foreground leading-relaxed">
                {stored.note}
              </p>
            )}
          </motion.div>
        ) : (
          <motion.div
            key="editing"
            initial={prefersReducedMotion ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={prefersReducedMotion ? undefined : { opacity: 0, y: -6 }}
            transition={{ duration: 0.25 }}
            className="mt-4"
          >
            <div
              className="flex flex-wrap gap-2"
              role="radiogroup"
              aria-label="Select today's mood"
            >
              {MOODS.map((m) => {
                const active = mood === m.value;
                return (
                  <button
                    key={m.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setMood(m.value)}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-full border px-3 h-8 text-xs font-medium transition-all outline-none",
                      "focus-visible:ring-3 focus-visible:ring-ring/50",
                      active
                        ? m.color
                        : "border-foreground/10 text-muted-foreground hover:border-foreground/20 hover:text-foreground",
                    )}
                  >
                    <span aria-hidden="true">{m.emoji}</span>
                    <span>{m.label}</span>
                    {active && <Check className="h-3 w-3" aria-hidden="true" />}
                  </button>
                );
              })}
            </div>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              maxLength={280}
              placeholder="One line about what's working or what's not…"
              className="mt-4 w-full rounded-xl border border-foreground/10 bg-transparent p-3 text-sm leading-relaxed outline-none resize-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 placeholder:text-muted-foreground/70"
            />
            <div className="mt-3 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                Saved to your account.
              </span>
              <button
                type="button"
                disabled={!mood || upsert.isPending}
                onClick={handleSubmit}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 h-8 text-xs font-medium text-primary-foreground",
                  "transition-all hover:bg-primary/90 active:translate-y-px",
                  "disabled:opacity-50 disabled:pointer-events-none",
                  "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                )}
              >
                {upsert.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                ) : (
                  <Sparkles className="h-3 w-3" aria-hidden="true" />
                )}
                {upsert.isPending ? "Saving…" : "Log reflection"}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </article>
  );
}
