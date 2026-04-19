"use client";

import { useEffect, useState } from "react";
import { Loader2, Pencil, Target } from "lucide-react";
import { useMyIntention, useSetIntention } from "@/lib/hooks/use-today";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";

const MAX_LENGTH = 200;

export function TodayIntention() {
  const { data: stored, isLoading } = useMyIntention();
  const setIntention = useSetIntention();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!stored) setEditing(false);
  }, [stored]);

  const trimmed = text.trim();
  const tooLong = trimmed.length > MAX_LENGTH;
  const canSave = trimmed.length > 0 && !tooLong && !setIntention.isPending;

  function handleSave() {
    if (tooLong) {
      setError(`Intention must be ${MAX_LENGTH} characters or fewer.`);
      return;
    }
    if (!canSave) return;
    setError("");
    setIntention.mutate(trimmed, {
      onSuccess: () => {
        setEditing(false);
        toast.success("Intention set for today", { duration: 2400 });
      },
      onError: () => toast.error("Couldn't save your intention. Try again."),
    });
  }

  function handleEdit() {
    setText(stored?.text ?? "");
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
      </article>
    );
  }

  const showStored = stored && !editing;

  return (
    <article
      aria-labelledby="intention-heading"
      className="rounded-2xl border border-foreground/10 bg-card p-5 md:p-6"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Today's intention
          </p>
          <h2
            id="intention-heading"
            className="mt-1.5 text-base font-semibold inline-flex items-center gap-2"
          >
            <Target className="h-4 w-4 text-primary" aria-hidden="true" />
            {showStored ? "Your intention" : "What do you want from today?"}
          </h2>
        </div>
        {showStored && (
          <button
            type="button"
            onClick={handleEdit}
            className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-foreground/10 px-2.5 h-7 text-xs font-medium text-muted-foreground hover:text-foreground hover:border-foreground/20 transition-colors"
          >
            <Pencil className="h-3 w-3" aria-hidden="true" />
            Edit
          </button>
        )}
      </div>

      {showStored ? (
        <p className="mt-3 text-sm leading-relaxed text-foreground">
          {stored.text}
        </p>
      ) : (
        <div className="mt-4">
          <textarea
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              if (error) setError("");
            }}
            rows={2}
            aria-label="Daily intention"
            aria-invalid={tooLong || undefined}
            placeholder="One sentence — what does a good day look like for you?"
            className="w-full rounded-xl border border-foreground/10 bg-transparent p-3 text-sm leading-relaxed outline-none resize-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 placeholder:text-muted-foreground/70"
          />
          {error && (
            <p className="mt-2 text-xs text-destructive" role="alert">
              {error}
            </p>
          )}
          <div className="mt-3 flex items-center justify-between">
            <span
              className={cn(
                "text-xs",
                tooLong ? "text-destructive" : "text-muted-foreground",
              )}
            >
              {trimmed.length} / {MAX_LENGTH}
            </span>
            <div className="flex items-center gap-2">
              {stored && (
                <button
                  type="button"
                  onClick={() => setEditing(false)}
                  className="inline-flex items-center rounded-lg border border-foreground/10 px-3 h-8 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
                >
                  Cancel
                </button>
              )}
              <button
                type="button"
                onClick={handleSave}
                disabled={!canSave}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 h-8 text-xs font-medium text-primary-foreground",
                  "transition-all hover:bg-primary/90 active:translate-y-px",
                  "disabled:opacity-50 disabled:pointer-events-none",
                )}
              >
                {setIntention.isPending && (
                  <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                )}
                {setIntention.isPending ? "Saving…" : "Set intention"}
              </button>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}
