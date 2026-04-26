"use client";

/**
 * P-Today3 (2026-04-26) — MakeFlashcardsModal.
 *
 * The previous "Add flashcards" button auto-extracted Q/A pairs from the
 * assistant message via the spaced_repetition agent. In practice the agent
 * either failed to find a clean Q/A shape (so the route fell back to dumping
 * `content[:200]` as the question and "Review this material." as the answer)
 * or split formatted Markdown — including code fences — into one giant card
 * that rendered terribly on the warm-up screen.
 *
 * Worse, auto-extraction skips the *generation effect*: writing the card in
 * your own words is what makes spaced repetition stick. So we move the
 * authoring step in front of the student.
 *
 * Behaviour:
 *   - Click "Flashcards" on a chat reply → modal opens with one empty row.
 *   - The assistant message is collapsed at the top (click to peek). Source
 *     is *available* but not *prominent* — discourages copy-paste.
 *   - Each card row: Front (≤140 chars), Back (≤280 chars). Counters with
 *     soft warning at 200 chars on Back. Backend ALSO enforces these caps.
 *   - "+ Add another card" up to 10 cards.
 *   - Save POSTs `{messageId, conversationId, cards}`. Backend strips code
 *     fences from Back and dedupes by (message_id, normalized front) — the
 *     UI surfaces the trimmed count if non-zero.
 */

import { useState } from "react";
import { ChevronDown, Loader2, Plus, X } from "lucide-react";
import { useMutation } from "@tanstack/react-query";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownRenderer } from "@/components/features/markdown-renderer";
import { chatApi } from "@/lib/chat-api";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";

const MAX_CARDS = 10;
const FRONT_MAX = 140;
const BACK_MAX = 280;
const BACK_SOFT_WARN = 200;

interface CardDraft {
  /** Stable id per row so React keys survive add/remove without scrambling. */
  uid: number;
  front: string;
  back: string;
}

let _uid = 0;
function nextUid(): number {
  _uid += 1;
  return _uid;
}

function emptyCard(): CardDraft {
  return { uid: nextUid(), front: "", back: "" };
}

export interface MakeFlashcardsModalProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  /** Server message id of the assistant reply being studied. */
  messageId: string;
  /** Conversation id this message belongs to. */
  conversationId: string;
  /** Raw assistant reply markdown — shown collapsed for reference only. */
  content: string;
  /** Fired after a successful save with the count of cards added. */
  onSaved?: (cardsAdded: number) => void;
}

export function MakeFlashcardsModal({
  open,
  onOpenChange,
  messageId,
  conversationId,
  content,
  onSaved,
}: MakeFlashcardsModalProps) {
  // We re-mount the inner via `key={messageId}` whenever a different message's
  // modal is opened, so the inner can initialize state from props directly
  // (no setState-in-effect).
  if (!open) return null;
  return (
    <MakeFlashcardsModalInner
      key={messageId}
      open={open}
      onOpenChange={onOpenChange}
      messageId={messageId}
      conversationId={conversationId}
      content={content}
      onSaved={onSaved}
    />
  );
}

function MakeFlashcardsModalInner({
  open,
  onOpenChange,
  messageId,
  conversationId,
  content,
  onSaved,
}: MakeFlashcardsModalProps) {
  const [cards, setCards] = useState<CardDraft[]>(() => [emptyCard()]);
  const [showSource, setShowSource] = useState(false);

  const saveMutation = useMutation({
    mutationFn: (validCards: Array<{ front: string; back: string }>) =>
      chatApi.addFlashcards({
        messageId,
        conversationId,
        cards: validCards,
      }),
    onSuccess: (result) => {
      const n = result.cards_added;
      const tail = n === 1 ? "" : "s";
      let msg = `${n} card${tail} added to review`;
      if (result.cards_trimmed > 0) {
        msg += ` · trimmed code blocks from ${result.cards_trimmed}`;
      }
      toast.success(msg);
      onSaved?.(n);
      onOpenChange(false);
    },
    onError: () => {
      toast.error("Could not save cards — try again");
    },
  });

  function updateCard(uid: number, patch: Partial<CardDraft>) {
    setCards((prev) =>
      prev.map((c) => (c.uid === uid ? { ...c, ...patch } : c)),
    );
  }

  function removeCard(uid: number) {
    setCards((prev) => {
      const next = prev.filter((c) => c.uid !== uid);
      return next.length === 0 ? [emptyCard()] : next;
    });
  }

  function addCard() {
    if (cards.length >= MAX_CARDS) return;
    setCards((prev) => [...prev, emptyCard()]);
  }

  const validCards = cards
    .map((c) => ({ front: c.front.trim(), back: c.back.trim(), uid: c.uid }))
    .filter((c) => c.front.length > 0 && c.back.length > 0);

  const hasInvalid = cards.some((c) => {
    const f = c.front.trim().length;
    const b = c.back.trim().length;
    // A row is "invalid" only if it's partially filled (front xor back) or
    // exceeds the hard caps. A fully-empty row is allowed — we just skip it.
    if (f === 0 && b === 0) return false;
    if (f === 0 || b === 0) return true;
    if (f > FRONT_MAX || b > BACK_MAX) return true;
    return false;
  });

  function handleSave() {
    if (validCards.length === 0) {
      toast.error("Add at least one card before saving");
      return;
    }
    if (hasInvalid) {
      toast.error("Fix the highlighted cards first");
      return;
    }
    saveMutation.mutate(
      validCards.map(({ front, back }) => ({ front, back })),
    );
  }

  const isSaving = saveMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-2xl"
        aria-label="Create flashcards from this message"
      >
        <DialogHeader>
          <DialogTitle>Make flashcards</DialogTitle>
          <DialogDescription>
            Pick the 1–2 things you nearly forgot. Write each card in your
            own words — short prompts beat long ones.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div>
            <button
              type="button"
              onClick={() => setShowSource((v) => !v)}
              aria-expanded={showSource}
              className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground hover:text-foreground"
            >
              <ChevronDown
                className={cn(
                  "h-3 w-3 transition-transform",
                  showSource && "rotate-180",
                )}
                aria-hidden="true"
              />
              Source message
            </button>
            {showSource && (
              <div className="mt-2 max-h-40 overflow-y-auto rounded-lg border border-dashed border-border bg-muted/20 px-3 py-2 text-sm text-muted-foreground">
                <MarkdownRenderer content={content} />
              </div>
            )}
          </div>

          <div className="flex flex-col gap-3">
            {cards.map((card, idx) => (
              <CardRow
                key={card.uid}
                index={idx}
                card={card}
                canRemove={cards.length > 1 || card.front !== "" || card.back !== ""}
                onChange={(patch) => updateCard(card.uid, patch)}
                onRemove={() => removeCard(card.uid)}
              />
            ))}
          </div>

          <div className="flex items-center justify-between">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={addCard}
              disabled={cards.length >= MAX_CARDS}
              className="h-7 text-xs"
            >
              <Plus className="h-3 w-3" aria-hidden="true" />
              Add another card
            </Button>
            <span className="text-[11px] text-muted-foreground">
              {validCards.length} ready · max {MAX_CARDS}
            </span>
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isSaving}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleSave}
            disabled={isSaving || validCards.length === 0 || hasInvalid}
          >
            {isSaving ? (
              <>
                <Loader2
                  className="mr-1.5 h-3.5 w-3.5 animate-spin"
                  aria-hidden="true"
                />
                Saving…
              </>
            ) : validCards.length === 0 ? (
              "Save cards"
            ) : (
              `Save ${validCards.length} card${validCards.length === 1 ? "" : "s"}`
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface CardRowProps {
  index: number;
  card: CardDraft;
  canRemove: boolean;
  onChange: (patch: Partial<CardDraft>) => void;
  onRemove: () => void;
}

function CardRow({ index, card, canRemove, onChange, onRemove }: CardRowProps) {
  const frontTrim = card.front.trim().length;
  const backTrim = card.back.trim().length;
  const frontOver = frontTrim > FRONT_MAX;
  const backOver = backTrim > BACK_MAX;
  const backWarn = backTrim > BACK_SOFT_WARN && !backOver;
  const partial =
    (frontTrim === 0 && backTrim > 0) || (frontTrim > 0 && backTrim === 0);

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg border border-input bg-background/40 p-3",
        (frontOver || backOver) && "border-destructive/60",
        partial && "border-amber-500/60",
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Card {index + 1}
        </span>
        <button
          type="button"
          onClick={onRemove}
          disabled={!canRemove}
          aria-label={`Remove card ${index + 1}`}
          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>

      <div className="flex flex-col gap-1">
        <label
          htmlFor={`card-${card.uid}-front`}
          className="text-[11px] text-muted-foreground"
        >
          Front · the cue
        </label>
        <Input
          id={`card-${card.uid}-front`}
          value={card.front}
          onChange={(e) => onChange({ front: e.target.value })}
          placeholder="What's the question or cue?"
          maxLength={FRONT_MAX + 40}
          aria-invalid={frontOver || undefined}
        />
        <div className="flex items-center justify-between text-[10px] text-muted-foreground">
          <span aria-live="polite">
            {partial && (
              <span className="text-amber-600 dark:text-amber-400">
                Front and back are both required.
              </span>
            )}
          </span>
          <span className={cn(frontOver && "text-destructive")}>
            {frontTrim}/{FRONT_MAX}
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label
          htmlFor={`card-${card.uid}-back`}
          className="text-[11px] text-muted-foreground"
        >
          Back · your recall in 1–2 sentences
        </label>
        <Textarea
          id={`card-${card.uid}-back`}
          value={card.back}
          onChange={(e) => onChange({ back: e.target.value })}
          autosize
          maxRows={6}
          rows={2}
          placeholder="Say the answer in your own words…"
          maxLength={BACK_MAX + 80}
          aria-invalid={backOver || undefined}
        />
        <div className="flex items-center justify-end text-[10px]">
          <span
            className={cn(
              backOver
                ? "text-destructive"
                : backWarn
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-muted-foreground",
            )}
          >
            {backTrim}/{BACK_MAX}
            {backWarn && !backOver ? " · keep it tight" : ""}
            {backOver ? " · too long" : ""}
          </span>
        </div>
      </div>
    </div>
  );
}
