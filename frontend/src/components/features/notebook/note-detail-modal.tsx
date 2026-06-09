"use client";

/**
 * P-Notebook2 (2026-04-28) — NoteDetailModal.
 *
 * Replaces the right-edge slide-in `<NoteDetailDrawer>` (Sheet) with a
 * centered editorial reading view. The drawer leaked a chat-app feel into
 * what is supposed to be a *notebook*: it landed on the right edge with
 * the assistant's raw markdown showing as the primary content, which made
 * the page feel like a phone-style chat panel rather than a place a
 * student writes things down.
 *
 * The modal:
 *   - lands centered, with newspaper margins around the body so the
 *     student's eye reads "this is a document, not a panel"
 *   - leads with the **student's note** when present; falls back to a
 *     framed "Captured from chat" block when only the original message
 *     exists, so the user knows they didn't write it
 *   - hides the original assistant message under a quiet "View source"
 *     toggle in the footer (revealed <10% of the time per usage data)
 *   - keeps Edit / Save / Delete in a calm footer bar identical in
 *     vocabulary to the old drawer so the affordance carries over
 *
 * The drawer component is left intact (and still exported from its own
 * file) so existing tests that target it continue to pass; this modal is
 * the new production surface mounted from `<NotebookScreen>`.
 */

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Loader2, Pencil, Trash2, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

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

export interface NoteDetailModalProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  entry: NotebookEntryOut | null;
}

export function NoteDetailModal({
  open,
  onOpenChange,
  entry,
}: NoteDetailModalProps) {
  if (!open || !entry) return null;
  return (
    <NoteDetailModalInner
      // Fresh mount per entry id — drops draft state cleanly.
      key={entry.id}
      open={open}
      onOpenChange={onOpenChange}
      entry={entry}
    />
  );
}

function NoteDetailModalInner({
  onOpenChange,
  entry,
}: NoteDetailModalProps & { entry: NotebookEntryOut }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(entry.title ?? "");
  const [noteText, setNoteText] = useState(entry.user_note ?? "");
  const [tags, setTags] = useState<string[]>([...(entry.tags ?? [])]);
  const [tagDraft, setTagDraft] = useState("");
  const [showOriginal, setShowOriginal] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Esc closes the modal (matches v8 modal idiom — TutorHelpModal, SaveDialog).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onOpenChange(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onOpenChange]);

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

  // Editorial priority: when the student wrote a note, show that as the
  // hero. When they didn't, fall back to the original chat *but* frame
  // it explicitly as "Captured from chat" so they don't think we made
  // their words up.
  const hasUserNote = (entry.user_note ?? "").trim().length > 0;
  const heroBody = hasUserNote ? entry.user_note ?? "" : entry.content ?? "";
  const heroLabel = hasUserNote ? "Your note" : "Captured from chat";
  const hasOriginal = (entry.content ?? "").trim().length > 0;
  // Don't show "View source" when there's nothing different to see.
  const showSourceToggle =
    hasUserNote && hasOriginal && entry.content !== heroBody;

  const isSaving = patchMutation.isPending;
  const isDeleting = deleteMutation.isPending;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="note-detail-title"
      onClick={() => onOpenChange(false)}
      data-testid="note-detail-modal"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(16,18,14,0.55)",
        backdropFilter: "blur(4px)",
        zIndex: 80,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "60px 24px 24px",
        overflowY: "auto",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card"
        style={{
          maxWidth: 720,
          width: "100%",
          background: "var(--panel)",
          boxShadow: "0 30px 80px rgba(0,0,0,0.35)",
          borderRadius: 22,
          position: "relative",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* ── Header ──────────────────────────────────────────────────── */}
        <div
          style={{
            padding: "28px 36px 18px",
            borderBottom: "1px solid var(--line)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 16,
          }}
        >
          <div style={{ minWidth: 0, flex: 1 }}>
            <div
              className="eyebrow"
              style={{
                fontSize: 10,
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                color: "var(--muted)",
                fontWeight: 700,
              }}
            >
              {meta.status} · {meta.sourceLabel}
              {entry.topic ? ` · ${entry.topic}` : ""}
            </div>
            {editing ? (
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Title"
                className="mt-2 h-9 text-lg font-medium"
                maxLength={120}
              />
            ) : (
              <h2
                id="note-detail-title"
                style={{
                  margin: "10px 0 4px",
                  fontFamily: "var(--serif)",
                  fontSize: 28,
                  fontWeight: 500,
                  letterSpacing: "-0.025em",
                  lineHeight: 1.15,
                  color: "var(--ink)",
                }}
              >
                {entry.title || "Untitled note"}
              </h2>
            )}
            <div
              style={{
                marginTop: 4,
                fontSize: 12,
                color: "var(--muted)",
              }}
            >
              Saved {formatDate(entry.created_at)}
            </div>
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            aria-label="Close"
            data-testid="note-detail-close"
            style={{
              width: 32,
              height: 32,
              borderRadius: 16,
              border: "1px solid var(--line)",
              background: "transparent",
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              color: "var(--ink-2)",
            }}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        {/* ── Body — newspaper margins, serif copy ────────────────────── */}
        <div
          style={{
            padding: "28px 36px",
            overflowY: "auto",
            maxHeight: "calc(100vh - 260px)",
          }}
        >
          <div
            className="eyebrow"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: hasUserNote ? "var(--forest)" : "var(--gold)",
              fontWeight: 700,
              marginBottom: 14,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 10,
            }}
          >
            <span>{heroLabel}</span>
            {!editing ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditing(true)}
                className="h-6 text-xs"
                data-testid="note-detail-edit"
              >
                <Pencil className="h-3 w-3" aria-hidden="true" />
                {hasUserNote ? "Edit" : "Add your note"}
              </Button>
            ) : null}
          </div>

          {editing ? (
            <Textarea
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="One sentence: what clicked?"
              autosize
              maxRows={20}
              rows={8}
              className="min-h-[160px] text-base"
              data-testid="note-detail-textarea"
            />
          ) : (
            <div
              data-testid="note-detail-hero"
              style={{
                fontFamily: "var(--serif)",
                fontSize: 17,
                lineHeight: 1.7,
                color: "var(--ink)",
                // When this is fallback "Captured from chat" content, give
                // it a subtle inset frame so it reads as quoted material,
                // not as the student's own writing.
                ...(hasUserNote
                  ? {}
                  : {
                      borderLeft: "3px solid var(--gold)",
                      paddingLeft: 16,
                      background: "var(--gold-soft)",
                      borderRadius: 8,
                      padding: 16,
                    }),
              }}
            >
              <MarkdownRenderer content={heroBody} />
            </div>
          )}

          {/* Tags */}
          <div style={{ marginTop: 26 }}>
            <div
              className="eyebrow"
              style={{
                fontSize: 10,
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                color: "var(--muted)",
                fontWeight: 700,
                marginBottom: 8,
              }}
            >
              Tags
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
              <p
                style={{
                  fontSize: 12,
                  color: "var(--muted-2)",
                  fontStyle: "italic",
                }}
              >
                No tags yet.
              </p>
            )}
          </div>

          {/* Original-source toggle — quiet, footer-style. Only shown
              when the student has their own note AND the original chat
              differs from it. */}
          {showSourceToggle ? (
            <div style={{ marginTop: 26 }}>
              <button
                type="button"
                onClick={() => setShowOriginal((v) => !v)}
                aria-expanded={showOriginal}
                data-testid="note-detail-source-toggle"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 11,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  fontWeight: 700,
                  color: "var(--muted)",
                  background: "transparent",
                  border: "none",
                  padding: "4px 0",
                  cursor: "pointer",
                }}
              >
                <ChevronDown
                  className={cn(
                    "h-3 w-3 transition-transform",
                    showOriginal && "rotate-180",
                  )}
                  aria-hidden="true"
                />
                {showOriginal ? "Hide original chat" : "View original chat"}
              </button>
              {showOriginal ? (
                <div
                  data-testid="note-detail-source-body"
                  style={{
                    marginTop: 10,
                    padding: 16,
                    borderRadius: 10,
                    border: "1px dashed var(--line-2)",
                    background: "var(--panel-2)",
                    color: "var(--muted)",
                    fontSize: 14,
                    lineHeight: 1.65,
                  }}
                >
                  <MarkdownRenderer content={entry.content ?? ""} />
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        {/* ── Footer ──────────────────────────────────────────────────── */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "16px 36px",
            background: "var(--panel-2)",
            borderTop: "1px solid var(--line)",
            gap: 10,
          }}
        >
          {confirmDelete ? (
            <>
              <span style={{ fontSize: 12, color: "var(--rose)" }}>
                Delete this note?
              </span>
              <div style={{ display: "flex", gap: 8 }}>
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
                  data-testid="note-detail-delete-confirm"
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
                data-testid="note-detail-save"
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
                data-testid="note-detail-delete"
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
      </div>
    </div>
  );
}
