"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

const MIN_LENGTH = 10;
const MAX_LENGTH = 1000;

export interface SelfExplanationModalProps {
  open: boolean;
  /** Whether the caller-side submit is in flight */
  submitting?: boolean;
  /** Fires with the entered explanation (trimmed). Empty string = "skip". */
  onConfirm: (explanation: string) => void;
  /** Optional cancel: closes the modal without submitting. */
  onCancel?: () => void;
}

export function SelfExplanationModal({
  open,
  submitting = false,
  onConfirm,
  onCancel,
}: SelfExplanationModalProps) {
  const [text, setText] = useState("");

  // Reset text whenever the modal opens
  useEffect(() => {
    if (open) setText("");
  }, [open]);

  const trimmed = text.trim();
  const explanationReady = trimmed.length >= MIN_LENGTH;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !submitting) onCancel?.();
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Before I show the grade…</DialogTitle>
          <DialogDescription>
            In one or two sentences — why does your approach work? Jot the
            reasoning before you see the score. It's the reflection that moves
            the needle.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-2">
          <label htmlFor="self-explanation-text" className="sr-only">
            Your self-explanation
          </label>
          <textarea
            id="self-explanation-text"
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, MAX_LENGTH))}
            rows={5}
            placeholder="My approach works because…"
            disabled={submitting}
            autoFocus
            className={cn(
              "w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm leading-relaxed",
              "outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary",
              "disabled:opacity-60",
            )}
          />
          <div className="mt-1.5 flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {explanationReady
                ? "Nice — that'll unlock your grade."
                : `${Math.max(MIN_LENGTH - trimmed.length, 0)} chars to go (or skip).`}
            </span>
            <span>
              {trimmed.length}/{MAX_LENGTH}
            </span>
          </div>
        </div>

        <DialogFooter className="mt-3 flex gap-2 sm:justify-end">
          <button
            type="button"
            onClick={() => onConfirm("")}
            disabled={submitting}
            className="h-9 rounded-md border border-border bg-background px-4 text-sm text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-60"
          >
            Skip & submit
          </button>
          <button
            type="button"
            onClick={() => onConfirm(trimmed)}
            disabled={submitting || !explanationReady}
            className="inline-flex items-center gap-2 h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-60"
          >
            {submitting && (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            )}
            {submitting ? "Submitting…" : "Submit with explanation"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
