"use client";

import { useEffect, useState } from "react";
import { Bookmark, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { chatApi, type NotebookEntryOut } from "@/lib/chat-api";
import { toast } from "@/lib/toast";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function NotebookCard({
  entry,
  onDelete,
}: {
  entry: NotebookEntryOut;
  onDelete: (id: string) => void;
}) {
  const [deleting, setDeleting] = useState(false);

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

  const preview = entry.content.slice(0, 200);
  const truncated = entry.content.length > 200;

  return (
    <div className="group relative flex flex-col gap-2 rounded-xl border border-border/60 bg-card px-5 py-4 shadow-sm hover:border-primary/40 hover:shadow-md transition-all duration-150">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Bookmark className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          {entry.title ? (
            <p className="text-sm font-semibold truncate text-foreground">{entry.title}</p>
          ) : (
            <p className="text-xs text-muted-foreground">{formatDate(entry.created_at)}</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => void handleDelete()}
          disabled={deleting}
          aria-label="Delete notebook entry"
          className={cn(
            "shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors",
            "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
            "hover:bg-destructive/10 hover:text-destructive",
            "disabled:opacity-40 disabled:cursor-not-allowed",
          )}
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>

      {/* Content preview */}
      <p className="text-sm text-muted-foreground leading-relaxed line-clamp-4">
        {preview}
        {truncated && <span className="text-muted-foreground/60">…</span>}
      </p>

      {/* Footer */}
      {entry.title && (
        <p className="text-[11px] text-muted-foreground/60 mt-1">
          {formatDate(entry.created_at)}
        </p>
      )}
    </div>
  );
}

export default function NotebookPage() {
  const [entries, setEntries] = useState<NotebookEntryOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
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

  const handleDelete = (id: string) => {
    setEntries((prev) => prev.filter((e) => e.id !== id));
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Page header */}
      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
          <Bookmark className="h-5 w-5 text-primary" aria-hidden="true" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-foreground">Notebook</h1>
          <p className="text-sm text-muted-foreground">
            Your saved messages from AI Tutor
          </p>
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="h-36 animate-pulse rounded-xl border border-border/40 bg-muted/30"
            />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center">
          <p className="text-sm text-destructive">{error}</p>
        </div>
      ) : entries.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-20 text-center">
          <Bookmark className="mb-4 h-12 w-12 text-muted-foreground/40" aria-hidden="true" />
          <p className="text-base font-medium text-muted-foreground">No saved notes yet.</p>
          <p className="mt-1 text-sm text-muted-foreground/60">
            Save messages from your chat to build your notebook.
          </p>
        </div>
      ) : (
        <>
          <p className="mb-4 text-xs text-muted-foreground">
            {entries.length} {entries.length === 1 ? "entry" : "entries"}
          </p>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {entries.map((entry) => (
              <NotebookCard key={entry.id} entry={entry} onDelete={handleDelete} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
