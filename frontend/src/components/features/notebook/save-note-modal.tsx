"use client";

/**
 * P-Today2 (2026-04-26) — SaveNoteModal.
 *
 * The bookmark icon on a chat bubble used to fire `saveToNotebook` directly,
 * dumping the entire assistant reply into the notebook. The result was a wall
 * of text the student rarely revisited. Two ideas come together here:
 *
 *   1. The act of *rewriting* the answer in your own words is what makes it
 *      stick — so we force a brief edit step before saving.
 *   2. Starting from a tight, recall-oriented summary lowers activation
 *      energy: the student edits a 3–6 bullet draft instead of staring at a
 *      blank textarea.
 *
 * Behaviour:
 *   - Modal opens immediately with the raw assistant content as a placeholder
 *     (so it's never blank, even if the LLM is slow / down).
 *   - Fires `chatApi.summarizeForNotebook` in the background; when it lands,
 *     the textarea swaps to the LLM summary and the suggested tags appear as
 *     accept-on-click chips.
 *   - "Regenerate" re-summarizes (cache-busted via a refetch flag).
 *   - "Use original" pastes the raw assistant content back into the box.
 *   - Tags: free-text chip input. Enter / comma to commit, click ✕ to remove.
 *   - "Save to notebook" POSTs `{user_note, content, title, tags}` and closes.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Sparkles, X } from "lucide-react";
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
import { Badge } from "@/components/ui/badge";
import { chatApi } from "@/lib/chat-api";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";

const MAX_TAGS = 8;
const MAX_TAG_LEN = 32;

function normalizeTag(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/^#+/, "")
    .replace(/\s+/g, "-")
    .slice(0, MAX_TAG_LEN);
}

function deriveTitleFromQuestion(q: string | undefined): string {
  if (!q) return "";
  const trimmed = q.trim().replace(/\s+/g, " ");
  if (trimmed.length <= 60) return trimmed;
  return trimmed.slice(0, 57).trimEnd() + "…";
}

export interface SaveNoteModalProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  /** Server message id of the assistant reply being saved. */
  messageId: string;
  /** Conversation id this message belongs to. */
  conversationId: string;
  /** Raw assistant reply markdown — saved as `content` for the audit trail. */
  content: string;
  /** Optional preceding user question — improves summary quality + seeds the title. */
  userQuestion?: string;
  /** Defaults to "chat". Set to "studio" / "quiz" / etc. when reused. */
  sourceType?: string;
  /** Optional preset topic / course context. */
  topic?: string;
  /** Fired after a successful save with the new entry id. */
  onSaved?: (entryId: string) => void;
}

export function SaveNoteModal({
  open,
  onOpenChange,
  messageId,
  conversationId,
  content,
  userQuestion,
  sourceType = "chat",
  topic,
  onSaved,
}: SaveNoteModalProps) {
  const [noteText, setNoteText] = useState<string>("");
  const [title, setTitle] = useState<string>("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagDraft, setTagDraft] = useState<string>("");
  const [suggestedTags, setSuggestedTags] = useState<string[]>([]);
  // Tracks whether we've ever populated the box (so the user typing doesn't
  // get clobbered by a late-arriving summary).
  const userEditedRef = useRef(false);

  const summarizeMutation = useMutation({
    mutationFn: () =>
      chatApi.summarizeForNotebook({
        messageId,
        content,
        userQuestion,
      }),
    onSuccess: (data) => {
      // Only auto-replace the textarea if the user hasn't typed anything yet.
      // Tags always merge — the student can remove the ones they don't want.
      if (!userEditedRef.current && data.summary) {
        setNoteText(data.summary);
      }
      setSuggestedTags(data.suggested_tags ?? []);
    },
  });

  const saveMutation = useMutation({
    mutationFn: (payload: {
      userNote: string;
      title: string;
      tags: string[];
    }) =>
      chatApi.saveToNotebook({
        messageId,
        conversationId,
        content,
        title: payload.title || undefined,
        sourceType,
        topic,
        userNote: payload.userNote,
        tags: payload.tags,
      }),
    onSuccess: (entry) => {
      toast.success("Saved to notebook");
      onSaved?.(entry.id);
      onOpenChange(false);
    },
    onError: () => {
      toast.error("Could not save — try again");
    },
  });

  // Reset + kick off summarization whenever the modal opens for a new message.
  useEffect(() => {
    if (!open) return;
    userEditedRef.current = false;
    // Seed with raw content as the always-available fallback. The summary
    // call below will overwrite this *only* if the user hasn't started typing.
    const initialDraft = content.slice(0, 2000);
    setNoteText(initialDraft);
    setTitle(deriveTitleFromQuestion(userQuestion));
    setTags([]);
    setTagDraft("");
    setSuggestedTags([]);
    summarizeMutation.reset();
    summarizeMutation.mutate();
    // We want to re-run only when the *target* message changes or the modal
    // re-opens — not when the mutation object identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, messageId]);

  function handleNoteChange(next: string) {
    if (next !== noteText) userEditedRef.current = true;
    setNoteText(next);
  }

  function commitTagDraft() {
    const norm = normalizeTag(tagDraft);
    if (!norm) {
      setTagDraft("");
      return;
    }
    if (!tags.includes(norm) && tags.length < MAX_TAGS) {
      setTags([...tags, norm]);
    }
    setTagDraft("");
  }

  function removeTag(t: string) {
    setTags(tags.filter((x) => x !== t));
  }

  function addSuggestedTag(t: string) {
    const norm = normalizeTag(t);
    if (!norm || tags.includes(norm) || tags.length >= MAX_TAGS) return;
    setTags([...tags, norm]);
  }

  function regenerate() {
    userEditedRef.current = false;
    summarizeMutation.reset();
    summarizeMutation.mutate();
  }

  function useOriginal() {
    setNoteText(content);
    userEditedRef.current = true;
  }

  function handleSave() {
    const trimmedNote = noteText.trim();
    if (!trimmedNote) {
      toast.error("Add a note before saving");
      return;
    }
    saveMutation.mutate({
      userNote: trimmedNote,
      title: title.trim(),
      tags,
    });
  }

  const isSummarizing = summarizeMutation.isPending;
  const isSaving = saveMutation.isPending;
  const filteredSuggestedTags = useMemo(
    () => suggestedTags.filter((t) => !tags.includes(normalizeTag(t))),
    [suggestedTags, tags],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-xl"
        aria-label="Save note to notebook"
      >
        <DialogHeader>
          <DialogTitle>Save to notebook</DialogTitle>
          <DialogDescription>
            Rewrite the answer in your own words — the act of summarizing is
            what makes it stick.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="note-title"
              className="text-xs font-medium text-muted-foreground"
            >
              Title <span className="opacity-60">(optional)</span>
            </label>
            <Input
              id="note-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="What is this note about?"
              maxLength={120}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <label
                htmlFor="note-text"
                className="text-xs font-medium text-muted-foreground"
              >
                Your note
              </label>
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                {isSummarizing ? (
                  <>
                    <Loader2
                      className="h-3 w-3 animate-spin"
                      aria-hidden="true"
                    />
                    Summarizing…
                  </>
                ) : summarizeMutation.isError ? (
                  <span className="text-destructive">
                    Summary failed — edit the original below.
                  </span>
                ) : (
                  <>
                    <Sparkles className="h-3 w-3" aria-hidden="true" />
                    AI-drafted — edit before saving
                  </>
                )}
              </div>
            </div>
            <Textarea
              id="note-text"
              value={noteText}
              onChange={(e) => handleNoteChange(e.target.value)}
              autosize
              maxRows={14}
              rows={6}
              placeholder="Your summary in your own words…"
              className="min-h-[120px]"
            />
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={regenerate}
                disabled={isSummarizing}
                className="h-7 text-xs"
              >
                {isSummarizing ? "Regenerating…" : "Regenerate summary"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={useOriginal}
                className="h-7 text-xs"
              >
                Use original
              </Button>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="note-tag-input"
              className="text-xs font-medium text-muted-foreground"
            >
              Tags <span className="opacity-60">(press Enter to add)</span>
            </label>
            <div
              className={cn(
                "flex min-h-9 flex-wrap items-center gap-1.5 rounded-lg border border-input bg-transparent px-2 py-1.5",
                "focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50",
              )}
            >
              {tags.map((t) => (
                <Badge
                  key={t}
                  variant="secondary"
                  className="gap-1 pr-1 text-xs font-medium"
                >
                  {t}
                  <button
                    type="button"
                    onClick={() => removeTag(t)}
                    aria-label={`Remove tag ${t}`}
                    className="rounded-full p-0.5 hover:bg-foreground/10"
                  >
                    <X className="h-3 w-3" aria-hidden="true" />
                  </button>
                </Badge>
              ))}
              <input
                id="note-tag-input"
                type="text"
                value={tagDraft}
                onChange={(e) => setTagDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === ",") {
                    e.preventDefault();
                    commitTagDraft();
                  } else if (
                    e.key === "Backspace" &&
                    tagDraft === "" &&
                    tags.length > 0
                  ) {
                    setTags(tags.slice(0, -1));
                  }
                }}
                onBlur={commitTagDraft}
                placeholder={tags.length === 0 ? "rag, embeddings…" : ""}
                disabled={tags.length >= MAX_TAGS}
                className="min-w-[6rem] flex-1 bg-transparent px-1 py-0.5 text-sm outline-none placeholder:text-muted-foreground"
              />
            </div>
            {filteredSuggestedTags.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                <span className="text-[11px] text-muted-foreground">
                  Suggested:
                </span>
                {filteredSuggestedTags.map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => addSuggestedTag(t)}
                    aria-label={`Add suggested tag ${t}`}
                    className="rounded-full border border-dashed border-input px-2 py-0.5 text-[11px] text-muted-foreground hover:border-ring hover:text-foreground"
                  >
                    + {t}
                  </button>
                ))}
              </div>
            )}
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
            disabled={isSaving || noteText.trim().length === 0}
          >
            {isSaving ? (
              <>
                <Loader2
                  className="mr-1.5 h-3.5 w-3.5 animate-spin"
                  aria-hidden="true"
                />
                Saving…
              </>
            ) : (
              "Save to notebook"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
