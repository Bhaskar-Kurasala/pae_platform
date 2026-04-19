"use client";

/**
 * P1-5 — Thumbs up/down + optional reason-chip popover for an assistant
 * message. Lives in its own module so the main chat page stays readable
 * and so tests can mount the control standalone.
 *
 * The component is fully controlled: the parent owns the `myFeedback`
 * state (hydrated from the server on conversation load) and the
 * `onSubmit` callback persists via `chatApi.postFeedback`. Optimistic
 * UI updates happen in the parent to keep this component pure.
 */

import { useEffect, useRef, useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ChatFeedbackCreate, ChatFeedbackRead } from "@/lib/chat-api";

// Reason chips surfaced in the thumbs-down popover. These slugs are sent to
// the backend verbatim; the admin rollup groups counts by the literal
// string. Add new entries freely — the backend doesn't validate against a
// fixed set, so this list is the source of truth for the UI.
export const FEEDBACK_REASONS: readonly { slug: string; label: string }[] = [
  { slug: "incorrect", label: "Incorrect" },
  { slug: "unhelpful", label: "Unhelpful" },
  { slug: "unsafe", label: "Unsafe" },
  { slug: "wrong_tone", label: "Wrong tone" },
  { slug: "other", label: "Other" },
];

const COMMENT_MAX = 500;

export interface FeedbackControlsProps {
  messageId: string;
  myFeedback?: ChatFeedbackRead | null;
  onSubmit: (messageId: string, payload: ChatFeedbackCreate) => Promise<void>;
}

export function FeedbackControls({
  messageId,
  myFeedback,
  onSubmit,
}: FeedbackControlsProps) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [reasons, setReasons] = useState<Set<string>>(() => new Set());
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  const rating = myFeedback?.rating ?? null;

  // Close the popover on outside click. Cheap, no need for a portal.
  useEffect(() => {
    if (!popoverOpen) return;
    const handle = (e: MouseEvent) => {
      if (!popoverRef.current) return;
      if (!popoverRef.current.contains(e.target as Node)) {
        setPopoverOpen(false);
      }
    };
    window.addEventListener("mousedown", handle);
    return () => window.removeEventListener("mousedown", handle);
  }, [popoverOpen]);

  const toggleReason = (slug: string) => {
    setReasons((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  };

  const handleThumbsUp = async () => {
    if (submitting) return;
    // One-click commit. Re-clicking up when already up is a no-op so we
    // don't issue a redundant POST; users can still swap to down via
    // the thumbs-down button.
    if (rating === "up") return;
    setSubmitting(true);
    try {
      await onSubmit(messageId, { rating: "up" });
      setPopoverOpen(false);
    } finally {
      setSubmitting(false);
    }
  };

  const handleThumbsDownClick = () => {
    if (submitting) return;
    // Seed the popover with any existing down-vote details so the user sees
    // what they previously picked; resetting feels surprising.
    if (rating === "down") {
      setReasons(new Set(myFeedback?.reasons ?? []));
      setComment(myFeedback?.comment ?? "");
    } else {
      setReasons(new Set());
      setComment("");
    }
    setPopoverOpen((open) => !open);
  };

  const handleSubmitDown = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      await onSubmit(messageId, {
        rating: "down",
        reasons: reasons.size > 0 ? Array.from(reasons) : undefined,
        comment: comment.trim() ? comment.trim() : undefined,
      });
      setPopoverOpen(false);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="relative inline-flex items-center gap-1">
      <button
        type="button"
        onClick={() => void handleThumbsUp()}
        disabled={submitting}
        aria-label={rating === "up" ? "You rated this response helpful" : "Rate helpful"}
        aria-pressed={rating === "up"}
        className={cn(
          "inline-flex items-center justify-center rounded-md h-7 w-7 transition-colors",
          rating === "up"
            ? "text-emerald-600 dark:text-emerald-400"
            : "text-muted-foreground hover:bg-muted hover:text-foreground",
          submitting && "opacity-60 cursor-not-allowed",
        )}
      >
        <ThumbsUp
          className="h-3.5 w-3.5"
          aria-hidden="true"
          fill={rating === "up" ? "currentColor" : "none"}
        />
      </button>

      <button
        type="button"
        onClick={handleThumbsDownClick}
        disabled={submitting}
        aria-label={rating === "down" ? "You rated this response unhelpful" : "Rate unhelpful"}
        aria-pressed={rating === "down"}
        aria-expanded={popoverOpen}
        className={cn(
          "inline-flex items-center justify-center rounded-md h-7 w-7 transition-colors",
          rating === "down"
            ? "text-rose-600 dark:text-rose-400"
            : "text-muted-foreground hover:bg-muted hover:text-foreground",
          submitting && "opacity-60 cursor-not-allowed",
        )}
      >
        <ThumbsDown
          className="h-3.5 w-3.5"
          aria-hidden="true"
          fill={rating === "down" ? "currentColor" : "none"}
        />
      </button>

      {popoverOpen && (
        <div
          ref={popoverRef}
          role="dialog"
          aria-label="Why was this response unhelpful?"
          className="absolute z-20 top-full left-0 mt-1 w-72 rounded-xl border border-border bg-popover text-popover-foreground shadow-lg p-3"
        >
          <p className="text-xs font-medium mb-2">Why was this unhelpful?</p>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {FEEDBACK_REASONS.map((r) => {
              const active = reasons.has(r.slug);
              return (
                <button
                  key={r.slug}
                  type="button"
                  onClick={() => toggleReason(r.slug)}
                  aria-pressed={active}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
                    active
                      ? "border-rose-500 bg-rose-500/10 text-rose-700 dark:text-rose-300"
                      : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {r.label}
                </button>
              );
            })}
          </div>
          <label className="block text-[11px] text-muted-foreground mb-1" htmlFor={`fb-comment-${messageId}`}>
            Optional comment
          </label>
          <textarea
            id={`fb-comment-${messageId}`}
            value={comment}
            onChange={(e) => setComment(e.target.value.slice(0, COMMENT_MAX))}
            rows={3}
            maxLength={COMMENT_MAX}
            placeholder="What went wrong?"
            className="w-full resize-none rounded-md border border-border bg-background px-2 py-1.5 text-xs outline-none focus:ring-2 focus:ring-primary/30"
          />
          <div className="flex items-center justify-between mt-2">
            <span className="text-[10px] text-muted-foreground/70">
              {comment.length}/{COMMENT_MAX}
            </span>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setPopoverOpen(false)}
                disabled={submitting}
                className="rounded-md border border-border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleSubmitDown()}
                disabled={submitting}
                className="rounded-md bg-rose-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-rose-700 transition-colors disabled:opacity-60"
              >
                {submitting ? "Saving…" : "Submit"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
