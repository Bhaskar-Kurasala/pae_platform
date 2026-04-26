"use client";

import { useMemo, useState } from "react";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { useNotebookEntries, useNotebookSummary } from "@/lib/hooks/use-notebook";
import { useDueCards } from "@/lib/hooks/use-srs";
import { useAuthStore } from "@/stores/auth-store";
import { NoteDetailDrawer } from "@/components/features/notebook/note-detail-drawer";
import type {
  NotebookEntryOut,
  NotebookGraduatedFilter,
} from "@/lib/chat-api";

interface NotePreview {
  entry: NotebookEntryOut;
  eyebrow: string;
  title: string;
  preview: string;
  tags: string[];
  graduated: boolean;
}

const SOURCE_LABEL: Record<string, string> = {
  chat: "Chat",
  quiz: "Quiz",
  interview: "Interview",
  career: "Career",
  studio: "Studio",
};

const PREVIEW_CHAR_LIMIT = 180;

function firstNonEmptyLine(text: string): string {
  for (const ln of text.split("\n")) {
    const trimmed = ln.trim().replace(/^[-*•#>\s]+/, "").trim();
    if (trimmed) return trimmed;
  }
  return text.trim();
}

function buildPreview(entry: NotebookEntryOut): NotePreview {
  const sourceKey = entry.source_type ?? "chat";
  const source = SOURCE_LABEL[sourceKey] ?? "Notebook";
  const topic = entry.topic ?? entry.title ?? "Insight";
  const graduated = entry.graduated_at !== null;
  const status = graduated ? "Graduated" : "In review";

  const body = entry.user_note?.trim() || entry.content || "";
  const titleSource =
    entry.title?.trim() || firstNonEmptyLine(body) || "Untitled note";
  const title =
    titleSource.length > 80 ? `${titleSource.slice(0, 77).trimEnd()}…` : titleSource;

  // Preview = the first 180 chars of the body, *excluding* the title line so
  // we don't repeat ourselves.
  let previewSource = body;
  if (entry.title?.trim() && previewSource.startsWith(entry.title.trim())) {
    previewSource = previewSource.slice(entry.title.trim().length).trim();
  }
  const collapsed = previewSource
    .split("\n")
    .map((ln) => ln.trim().replace(/^[-*•]\s*/, "• "))
    .filter(Boolean)
    .join("  ");
  const preview =
    collapsed.length > PREVIEW_CHAR_LIMIT
      ? `${collapsed.slice(0, PREVIEW_CHAR_LIMIT - 1).trimEnd()}…`
      : collapsed;

  return {
    entry,
    eyebrow: `${status} · ${source} · ${topic}`,
    title,
    preview,
    tags: [...(entry.tags ?? [])],
    graduated,
  };
}

function delayClass(index: number): string {
  const mod = index % 3;
  if (mod === 0) return "";
  return ` delay-${mod}`;
}

const FILTER_LABELS: Record<NotebookGraduatedFilter, string> = {
  all: "All",
  graduated: "Graduated",
  in_review: "In review",
};

const FILTERS: NotebookGraduatedFilter[] = ["all", "graduated", "in_review"];

export function NotebookScreen() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  const [filter, setFilter] = useState<NotebookGraduatedFilter>("all");
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<NotebookEntryOut | null>(
    null,
  );

  const summaryQ = useNotebookSummary();
  const entriesQ = useNotebookEntries({
    source: sourceFilter ?? undefined,
    graduated: filter,
  });
  const { data: dueCards } = useDueCards(50);

  const summary = summaryQ.data;
  const entries = entriesQ.data;

  const totalNotes = summary?.total ?? 0;
  const graduatedPct = Math.round(summary?.graduation_percentage ?? 0);
  // Ghost card now reflects notes still in review — the original implementation
  // was reading total SRS due cards, which conflated unrelated review queues.
  const inReview = summary?.in_review ?? Math.min(dueCards?.length ?? 0, totalNotes);
  const sources = summary?.by_source ?? [];

  useSetV8Topbar({
    eyebrow: "Notebook",
    titleHtml:
      "Notes graduate here when recall makes them <i>stick</i>.",
    chips: [
      { label: `${totalNotes} note${totalNotes === 1 ? "" : "s"}`, variant: "ink" },
      { label: `${summary?.graduated ?? 0} graduated`, variant: "forest" },
    ],
    progress: graduatedPct,
  });

  const notes: ReadonlyArray<NotePreview> = useMemo(() => {
    if (!isAuthed) return [];
    if (entries === undefined) return [];
    return entries.map(buildPreview);
  }, [entries, isAuthed]);

  const showEmptyHint = isAuthed && entries !== undefined && notes.length === 0;
  const showLoading = isAuthed && entriesQ.isLoading && notes.length === 0;

  return (
    <section className="screen active" id="screen-notebook">
      <div className="pad">
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
            flexWrap: "wrap",
            margin: "0 0 16px",
          }}
          aria-label="Notebook filters"
        >
          {FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={`mini-chip${filter === f ? " active" : ""}`}
              style={{
                background: filter === f ? "#1D9E75" : undefined,
                color: filter === f ? "white" : undefined,
                cursor: "pointer",
              }}
              aria-pressed={filter === f}
            >
              {FILTER_LABELS[f]}
            </button>
          ))}
          {sources.length > 0 && (
            <span
              style={{
                marginLeft: 8,
                color: "#6B7280",
                fontSize: 11,
              }}
            >
              ·
            </span>
          )}
          {sources.map((s) => (
            <button
              key={s.source}
              type="button"
              onClick={() =>
                setSourceFilter((curr) => (curr === s.source ? null : s.source))
              }
              className={`mini-chip${sourceFilter === s.source ? " active" : ""}`}
              style={{
                background: sourceFilter === s.source ? "#7C3AED" : undefined,
                color: sourceFilter === s.source ? "white" : undefined,
                cursor: "pointer",
              }}
              aria-pressed={sourceFilter === s.source}
            >
              {(SOURCE_LABEL[s.source] ?? s.source)} · {s.count}
            </button>
          ))}
        </div>

        <div className="notebook">
          {showLoading && (
            <article className="note reveal" aria-busy="true">
              <div className="eyebrow">Loading your notebook…</div>
              <p>Bookmarked messages and graduated insights will appear here.</p>
            </article>
          )}

          {!isAuthed && (
            <article className="note reveal">
              <div className="eyebrow">Notebook · Sign in</div>
              <p>Log in to see the notes you&apos;ve saved from chats, quizzes, and interviews.</p>
            </article>
          )}

          {showEmptyHint && (
            <article className="note reveal">
              <div className="eyebrow">Notebook · {FILTER_LABELS[filter]}</div>
              <p>
                {filter === "graduated"
                  ? "Nothing has graduated yet — keep reviewing the cards in your warm-up and the strongest ones land here."
                  : filter === "in_review"
                    ? "Nothing in active review. Bookmark an assistant reply from chat to start your notebook."
                    : "Bookmark an assistant reply (the bookmark icon on any chat bubble) to start your notebook."}
              </p>
            </article>
          )}

          {notes.map((note, idx) => (
            <button
              key={`${note.entry.id}-${idx}`}
              type="button"
              onClick={() => setSelectedEntry(note.entry)}
              className={`note note-clickable reveal${delayClass(idx)}`}
              style={{
                textAlign: "left",
                cursor: "pointer",
                background: "transparent",
                border: "none",
                padding: 0,
                font: "inherit",
                color: "inherit",
                display: "block",
                width: "100%",
              }}
              aria-label={`Open note: ${note.title}`}
            >
              <div className="note-card-inner">
                <div className="eyebrow">{note.eyebrow}</div>
                <div
                  style={{
                    fontWeight: 600,
                    fontSize: 14,
                    margin: "4px 0 6px",
                    color: "#111827",
                  }}
                >
                  {note.title}
                </div>
                {note.preview && (
                  <p
                    style={{
                      margin: 0,
                      fontSize: 13,
                      color: "#6B7280",
                      lineHeight: 1.5,
                    }}
                  >
                    {note.preview}
                  </p>
                )}
                {note.tags.length > 0 && (
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: 4,
                      marginTop: 8,
                    }}
                  >
                    {note.tags.slice(0, 5).map((t) => (
                      <span
                        key={t}
                        style={{
                          background: "#F3F4F6",
                          color: "#374151",
                          padding: "2px 8px",
                          borderRadius: 999,
                          fontSize: 11,
                          fontWeight: 500,
                        }}
                      >
                        {t}
                      </span>
                    ))}
                    {note.tags.length > 5 && (
                      <span
                        style={{
                          color: "#6B7280",
                          fontSize: 11,
                          alignSelf: "center",
                        }}
                      >
                        +{note.tags.length - 5}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </button>
          ))}

          <article
            className={`note note-ghost reveal${delayClass(notes.length)}`}
          >
            <div className="ghost-icon" aria-hidden="true">
              <svg
                width="22"
                height="22"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7v5l3 2" />
              </svg>
            </div>
            <div className="ghost-count">{inReview}</div>
            <div className="ghost-label">
              {inReview === 1 ? "note still in review" : "notes still in review"}
            </div>
            <div className="ghost-hint">
              They graduate here once the SRS card behind them earns at least
              two successful recalls.
            </div>
          </article>
        </div>
      </div>

      <NoteDetailDrawer
        open={selectedEntry !== null}
        onOpenChange={(next) => {
          if (!next) setSelectedEntry(null);
        }}
        entry={selectedEntry}
      />
    </section>
  );
}
