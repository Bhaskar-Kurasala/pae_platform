"use client";

/**
 * P-Today2 (2026-04-26) — NoteDetailDrawer.
 *
 * Slides in from the right when the student clicks a notebook card. The card
 * itself only shows a preview (title + first lines + tag chips + status) so
 * the screen stays scannable. The drawer is where the full note lives:
 *   * full rewritten note (Markdown)
 *   * tag chips + inline edit
 *   * collapsible "Original assistant message" — preserved raw text
 *   * graduation status, source, created date
 *   * Edit / Save / Delete
 *
 * Edits PATCH `/chat/notebook/{id}`; delete DELETEs and closes the drawer.
 * Both invalidate the React Query "notebook" cache so the list refreshes.
 */

import { useMemo, useState } from "react";
import { ChevronDown, Loader2, Pencil, Trash2, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { MarkdownRenderer } from "@/components/features/markdown-renderer";
import { chatApi, type NotebookEntryOut } from "@/lib/chat-api";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";

const SOURCE_LABEL: Record<string, string> = {
  chat: "Chat",
  quiz: "Quiz",
  interview: "Interview",
  career: "Career",
  studio: "Studio",
};

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

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

export interface NoteDetailDrawerProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  entry: NotebookEntryOut | null;
}

export function NoteDetailDrawer({
  open,
  onOpenChange,
  entry,
}: NoteDetailDrawerProps) {
  // Bail before mounting the inner so the inner can assume `entry` is non-null
  // and initialize all local state from props (no setState-in-effect needed).
  if (!entry) return null;
  return (
    <NoteDetailDrawerInner
      // `key` forces a fresh mount when the student opens a different entry,
      // which resets every piece of local state (edit mode, draft tags,
      // confirm-delete, etc.) without an effect.
      key={entry.id}
      open={open}
      onOpenChange={onOpenChange}
      entry={entry}
    />
  );
}

function NoteDetailDrawerInner({
  open,
  onOpenChange,
  entry,
}: NoteDetailDrawerProps & { entry: NotebookEntryOut }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(entry.title ?? "");
  const [noteText, setNoteText] = useState(
    entry.user_note ?? entry.content ?? "",
  );
  const [tags, setTags] = useState<string[]>([...(entry.tags ?? [])]);
  const [tagDraft, setTagDraft] = useState("");
  const [showOriginal, setShowOriginal] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const patchMutation = useMutation({
    mutationFn: () =>
      chatApi.patchNotebookEntry(entry.id, {
        title: title.trim() || null,
        user_note: noteText.trim() || null,
        tags,
      }),
    onSuccess: () => {
      toast.success("Note updated");
      void qc.invalidateQueries({ queryKey: ["notebook"] });
      setEditing(false);
    },
    onError: () => {
      toast.error("Could not save changes");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => chatApi.deleteNotebookEntry(entry.id),
    onSuccess: () => {
      toast.success("Note deleted");
      void qc.invalidateQueries({ queryKey: ["notebook"] });
      onOpenChange(false);
    },
    onError: () => {
      toast.error("Could not delete note");
    },
  });

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

  const meta = useMemo(() => {
    const sourceKey = entry.source_type ?? "chat";
    const sourceLabel = SOURCE_LABEL[sourceKey] ?? "Notebook";
    const status = entry.graduated_at ? "Graduated" : "In review";
    return { sourceLabel, status };
  }, [entry]);

  const renderedNote = noteText || entry.content || "";
  const isSaving = patchMutation.isPending;
  const isDeleting = deleteMutation.isPending;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-lg"
      >
        <SheetHeader className="border-b px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-col gap-1">
              <SheetDescription className="text-[11px] uppercase tracking-wide text-muted-foreground">
                {meta?.status} · {meta?.sourceLabel}
                {entry.topic ? ` · ${entry.topic}` : ""}
              </SheetDescription>
              {editing ? (
                <Input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Title"
                  className="h-8 text-base font-semibold"
                  maxLength={120}
                />
              ) : (
                <SheetTitle className="text-base font-semibold">
                  {entry.title || "Untitled note"}
                </SheetTitle>
              )}
              <span className="text-[11px] text-muted-foreground">
                Saved {formatDate(entry.created_at)}
              </span>
            </div>
          </div>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <div className="flex flex-col gap-4">
            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Your note
                </span>
                {!editing && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEditing(true)}
                    className="h-6 text-xs"
                  >
                    <Pencil className="h-3 w-3" aria-hidden="true" />
                    Edit
                  </Button>
                )}
              </div>
              {editing ? (
                <Textarea
                  value={noteText}
                  onChange={(e) => setNoteText(e.target.value)}
                  autosize
                  maxRows={20}
                  rows={8}
                  className="min-h-[160px] text-sm"
                />
              ) : (
                <div className="rounded-lg border border-border bg-muted/30 px-3 py-2.5 text-sm">
                  <MarkdownRenderer content={renderedNote} />
                </div>
              )}
            </div>

            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Tags
                </span>
              </div>
              {editing ? (
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
                      className="gap-1 pr-1 text-xs"
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
                    placeholder={tags.length === 0 ? "Add a tag…" : ""}
                    disabled={tags.length >= MAX_TAGS}
                    className="min-w-[6rem] flex-1 bg-transparent px-1 py-0.5 text-sm outline-none placeholder:text-muted-foreground"
                  />
                </div>
              ) : tags.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {tags.map((t) => (
                    <Badge key={t} variant="secondary" className="text-xs">
                      {t}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-xs italic text-muted-foreground">
                  No tags yet.
                </p>
              )}
            </div>

            {entry.content && entry.content !== renderedNote && (
              <div>
                <button
                  type="button"
                  onClick={() => setShowOriginal((v) => !v)}
                  className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground hover:text-foreground"
                  aria-expanded={showOriginal}
                >
                  <ChevronDown
                    className={cn(
                      "h-3 w-3 transition-transform",
                      showOriginal && "rotate-180",
                    )}
                    aria-hidden="true"
                  />
                  Original assistant message
                </button>
                {showOriginal && (
                  <div className="mt-2 rounded-lg border border-dashed border-border bg-muted/20 px-3 py-2.5 text-sm text-muted-foreground">
                    <MarkdownRenderer content={entry.content} />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 border-t bg-muted/30 px-5 py-3">
          {confirmDelete ? (
            <>
              <span className="text-xs text-destructive">Delete this note?</span>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirmDelete(false)}
                  disabled={isDeleting}
                >
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => deleteMutation.mutate()}
                  disabled={isDeleting}
                >
                  {isDeleting ? (
                    <>
                      <Loader2
                        className="h-3 w-3 animate-spin"
                        aria-hidden="true"
                      />
                      Deleting…
                    </>
                  ) : (
                    "Delete"
                  )}
                </Button>
              </div>
            </>
          ) : editing ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditing(false)}
                disabled={isSaving}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={() => patchMutation.mutate()}
                disabled={isSaving}
              >
                {isSaving ? (
                  <>
                    <Loader2
                      className="h-3 w-3 animate-spin"
                      aria-hidden="true"
                    />
                    Saving…
                  </>
                ) : (
                  "Save changes"
                )}
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setConfirmDelete(true)}
                className="text-destructive hover:text-destructive"
              >
                <Trash2 className="h-3 w-3" aria-hidden="true" />
                Delete
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onOpenChange(false)}
              >
                Close
              </Button>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
