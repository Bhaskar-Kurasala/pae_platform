"use client";

import { useEffect, useRef, useState } from "react";
import {
  Bookmark,
  BookOpen,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  MessageSquare,
  RotateCcw,
  Search,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { chatApi, type NotebookEntryOut } from "@/lib/chat-api";
import { toast } from "@/lib/toast";

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const SOURCE_META: Record<
  string,
  { label: string; icon: React.ReactNode; color: string }
> = {
  chat: {
    label: "Chat",
    icon: <MessageSquare className="h-3 w-3" />,
    color: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  },
  quiz: {
    label: "Quiz",
    icon: <BrainCircuit className="h-3 w-3" />,
    color:
      "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
  },
  interview: {
    label: "Interview",
    icon: <BookOpen className="h-3 w-3" />,
    color:
      "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  },
  career: {
    label: "Career",
    icon: <Bookmark className="h-3 w-3" />,
    color:
      "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  },
};

function SourceBadge({
  sourceType,
  topic,
}: {
  sourceType: string | null;
  topic: string | null;
}) {
  const meta = SOURCE_META[sourceType ?? "chat"] ?? SOURCE_META.chat;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
        meta.color,
      )}
    >
      {meta.icon}
      {meta.label}
      {topic && <span className="opacity-70">· {topic}</span>}
    </span>
  );
}

// ── Inline annotation editor ──────────────────────────────────────────────────

function InlineNote({
  entryId,
  initial,
  onSaved,
}: {
  entryId: string;
  initial: string | null;
  onSaved: (note: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(initial ?? "");
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  const save = async () => {
    setSaving(true);
    try {
      await chatApi.patchNotebookEntry(entryId, { user_note: value || null });
      onSaved(value);
      setEditing(false);
    } catch {
      toast.error("Could not save note");
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => {
          setEditing(true);
          setTimeout(() => ref.current?.focus(), 50);
        }}
        className={cn(
          "w-full rounded-md border border-dashed px-3 py-2 text-left text-xs transition-colors",
          value
            ? "border-primary/30 bg-primary/5 text-foreground"
            : "border-border/50 text-muted-foreground/60 hover:border-primary/40 hover:text-muted-foreground",
        )}
      >
        {value || "Add your own takeaway…"}
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        rows={3}
        placeholder="Write your own takeaway or key insight…"
        className="w-full resize-none rounded-md border border-primary/40 bg-background px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
      />
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving}
          className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={() => {
            setValue(initial ?? "");
            setEditing(false);
          }}
          className="rounded-md px-3 py-1 text-xs text-muted-foreground hover:text-foreground"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Notebook Card ─────────────────────────────────────────────────────────────

function NotebookCard({
  entry,
  onDelete,
  onAnnotationSave,
  onReviewed,
}: {
  entry: NotebookEntryOut;
  onDelete: (id: string) => void;
  onAnnotationSave: (id: string, note: string) => void;
  onReviewed: (id: string) => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [marking, setMarking] = useState(false);

  const preview = entry.content.slice(0, 280);
  const truncated = entry.content.length > 280;

  const chatUrl =
    entry.conversation_id
      ? `/portal/chat?cid=${entry.conversation_id}&mid=${entry.message_id}`
      : null;

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await chatApi.deleteNotebookEntry(entry.id);
      onDelete(entry.id);
      toast.success("Entry deleted");
    } catch {
      toast.error("Could not delete — try again");
    } finally {
      setDeleting(false);
    }
  };

  const handleMarkReviewed = async () => {
    setMarking(true);
    try {
      await chatApi.markNotebookReviewed(entry.id);
      onReviewed(entry.id);
      toast.success("Marked as reviewed");
    } catch {
      toast.error("Could not mark as reviewed");
    } finally {
      setMarking(false);
    }
  };

  return (
    <div className="group flex flex-col gap-3 rounded-xl border border-border/60 bg-card px-5 py-4 shadow-sm hover:border-primary/30 hover:shadow-md transition-all duration-150">
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1 min-w-0">
          {entry.title && (
            <p className="text-sm font-semibold text-foreground truncate">
              {entry.title}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <SourceBadge
              sourceType={entry.source_type}
              topic={entry.topic}
            />
            <span className="text-[11px] text-muted-foreground/60">
              {formatDate(entry.created_at)}
            </span>
            {entry.last_reviewed_at && (
              <span className="text-[11px] text-muted-foreground/50">
                · reviewed {formatDate(entry.last_reviewed_at)}
              </span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex shrink-0 items-center gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
          {chatUrl && (
            <a
              href={chatUrl}
              aria-label="Open source chat"
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
          <button
            type="button"
            onClick={() => void handleMarkReviewed()}
            disabled={marking}
            aria-label="Mark as reviewed"
            className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40 transition-colors"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => void handleDelete()}
            disabled={deleting}
            aria-label="Delete notebook entry"
            className="rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:opacity-40 transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* AI content */}
      <div className="text-sm text-muted-foreground leading-relaxed">
        {expanded ? entry.content : preview}
        {truncated && !expanded && (
          <span className="text-muted-foreground/50">…</span>
        )}
      </div>
      {truncated && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1 text-xs text-primary/70 hover:text-primary transition-colors"
        >
          {expanded ? (
            <>
              <ChevronUp className="h-3 w-3" /> Show less
            </>
          ) : (
            <>
              <ChevronDown className="h-3 w-3" /> Show more
            </>
          )}
        </button>
      )}

      {/* Student annotation */}
      <div className="border-t border-border/40 pt-2">
        <p className="mb-1.5 text-[11px] font-medium text-muted-foreground/70 uppercase tracking-wide">
          My Takeaway
        </p>
        <InlineNote
          entryId={entry.id}
          initial={entry.user_note}
          onSaved={(note) => onAnnotationSave(entry.id, note)}
        />
      </div>
    </div>
  );
}

// ── Review Tab ────────────────────────────────────────────────────────────────

function ReviewTab({
  entries,
  onDelete,
  onAnnotationSave,
  onReviewed,
}: {
  entries: NotebookEntryOut[];
  onDelete: (id: string) => void;
  onAnnotationSave: (id: string, note: string) => void;
  onReviewed: (id: string) => void;
}) {
  const STALE_DAYS = 7;
  const now = Date.now();
  const due = entries.filter((e) => {
    if (!e.last_reviewed_at) return true;
    const ms = now - new Date(e.last_reviewed_at).getTime();
    return ms > STALE_DAYS * 86_400_000;
  });

  if (due.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-20 text-center">
        <CheckCircle2 className="mb-4 h-12 w-12 text-muted-foreground/30" />
        <p className="text-base font-medium text-muted-foreground">
          You&apos;re all caught up!
        </p>
        <p className="mt-1 text-sm text-muted-foreground/60">
          No notes are due for review. Check back in a few days.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        {due.length} {due.length === 1 ? "note" : "notes"} due for review
        (not reviewed in {STALE_DAYS}+ days)
      </p>
      {due.map((entry) => (
        <NotebookCard
          key={entry.id}
          entry={entry}
          onDelete={onDelete}
          onAnnotationSave={onAnnotationSave}
          onReviewed={onReviewed}
        />
      ))}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

type Tab = "all" | "review";

export default function NotebookPage() {
  const [entries, setEntries] = useState<NotebookEntryOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("all");
  const [search, setSearch] = useState("");
  const [topicFilter, setTopicFilter] = useState<string>("all");

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const data = await chatApi.listNotebook();
        if (alive) setEntries(data);
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const handleDelete = (id: string) =>
    setEntries((prev) => prev.filter((e) => e.id !== id));

  const handleAnnotationSave = (id: string, note: string) =>
    setEntries((prev) =>
      prev.map((e) => (e.id === id ? { ...e, user_note: note } : e)),
    );

  const handleReviewed = (id: string) =>
    setEntries((prev) =>
      prev.map((e) =>
        e.id === id ? { ...e, last_reviewed_at: new Date().toISOString() } : e,
      ),
    );

  // Unique topics for filter chips
  const topics = Array.from(
    new Set(entries.map((e) => e.topic).filter(Boolean) as string[]),
  );

  const filtered = entries.filter((e) => {
    const matchesTopic =
      topicFilter === "all" || e.topic === topicFilter;
    const q = search.toLowerCase();
    const matchesSearch =
      !q ||
      e.content.toLowerCase().includes(q) ||
      (e.title ?? "").toLowerCase().includes(q) ||
      (e.user_note ?? "").toLowerCase().includes(q) ||
      (e.topic ?? "").toLowerCase().includes(q);
    return matchesTopic && matchesSearch;
  });

  const dueCnt = entries.filter((e) => {
    if (!e.last_reviewed_at) return true;
    return (
      Date.now() - new Date(e.last_reviewed_at).getTime() >
      7 * 86_400_000
    );
  }).length;

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
      {/* Page header */}
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
          <Bookmark className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-foreground">Notebook</h1>
          <p className="text-sm text-muted-foreground">
            Your saved insights — annotated and ready to review
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="mb-5 flex items-center gap-1 border-b border-border">
        {(
          [
            { key: "all", label: "All Notes", icon: <Bookmark className="h-3.5 w-3.5" /> },
            {
              key: "review",
              label: `Review${dueCnt > 0 ? ` (${dueCnt})` : ""}`,
              icon: <RotateCcw className="h-3.5 w-3.5" />,
            },
          ] as const
        ).map(({ key, label, icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={cn(
              "flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors",
              tab === key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {icon}
            {label}
          </button>
        ))}
      </div>

      {/* Filter bar (All Notes tab only) */}
      {tab === "all" && (
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/50" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search notes…"
              className="w-full rounded-lg border border-border bg-background py-1.5 pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40"
            />
          </div>
          {topics.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {["all", ...topics].map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTopicFilter(t)}
                  className={cn(
                    "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                    topicFilter === t
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:bg-muted/70",
                  )}
                >
                  {t === "all" ? "All topics" : t}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-44 animate-pulse rounded-xl border border-border/40 bg-muted/30"
            />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center">
          <p className="text-sm text-destructive">{error}</p>
        </div>
      ) : tab === "review" ? (
        <ReviewTab
          entries={entries}
          onDelete={handleDelete}
          onAnnotationSave={handleAnnotationSave}
          onReviewed={handleReviewed}
        />
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-20 text-center">
          <Bookmark className="mb-4 h-12 w-12 text-muted-foreground/40" />
          <p className="text-base font-medium text-muted-foreground">
            {entries.length === 0 ? "No saved notes yet." : "No notes match your filter."}
          </p>
          <p className="mt-1 text-sm text-muted-foreground/60">
            {entries.length === 0
              ? "Save messages from your chat to build your notebook."
              : "Try a different search or topic."}
          </p>
        </div>
      ) : (
        <>
          <p className="mb-4 text-xs text-muted-foreground">
            {filtered.length} {filtered.length === 1 ? "note" : "notes"}
          </p>
          <div className="space-y-4">
            {filtered.map((entry) => (
              <NotebookCard
                key={entry.id}
                entry={entry}
                onDelete={handleDelete}
                onAnnotationSave={handleAnnotationSave}
                onReviewed={handleReviewed}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
