"use client";

import { useEffect, useState } from "react";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { useDueCards } from "@/lib/hooks/use-srs";
import { chatApi, type NotebookEntryOut } from "@/lib/chat-api";

interface NoteSpec {
  eyebrow: string;
  body: string;
}

const FALLBACK_NOTES: ReadonlyArray<NoteSpec> = [
  {
    eyebrow: "Graduated · Lesson 2 · OOP",
    body: "Type hints make Python feel like a contract with my future self — they tell the caller what to expect, and they help the IDE catch the slip before it becomes debugging later.",
  },
  {
    eyebrow: "Graduated · Tutor · Retrieval",
    body: "HNSW is like a skip-list for vector space — it lets semantic search feel fast enough to be part of real products, not just demos.",
  },
  {
    eyebrow: "Graduated · Lesson 4 · SQL",
    body: "Window functions are the moment SQL stops feeling like spreadsheets and starts feeling like a language — running totals, ranks, and lag/lead in one pass.",
  },
  {
    eyebrow: "Graduated · Lab · Stats",
    body: "p-values answer “would I see this by chance?” — not “is this important?”. Effect size is the question I usually actually meant to ask.",
  },
];

const SOURCE_LABEL: Record<string, string> = {
  chat: "Chat",
  quiz: "Quiz",
  interview: "Interview",
  career: "Career",
};

function entryToNote(entry: NotebookEntryOut): NoteSpec {
  const sourceKey = entry.source_type ?? "chat";
  const source = SOURCE_LABEL[sourceKey] ?? "Notebook";
  const topic = entry.topic ?? entry.title ?? "Insight";
  const body = entry.user_note?.trim() || entry.content;
  return {
    eyebrow: `Graduated · ${source} · ${topic}`,
    body,
  };
}

function delayClass(index: number): string {
  const mod = index % 3;
  if (mod === 0) return "";
  return ` delay-${mod}`;
}

export function NotebookScreen() {
  const [entries, setEntries] = useState<NotebookEntryOut[] | null>(null);
  const { data: dueCards } = useDueCards(50);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const data = await chatApi.listNotebook();
        if (alive) setEntries(data);
      } catch {
        if (alive) setEntries([]);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const notes: ReadonlyArray<NoteSpec> =
    entries && entries.length > 0
      ? entries.map(entryToNote)
      : entries === null
        ? FALLBACK_NOTES
        : [
            {
              eyebrow: "Notebook · Nothing graduated yet",
              body: "Notes graduate here when recall proves they belong in long-term memory.",
            },
          ];

  const ghostCount = dueCards?.length ?? 0;

  useSetV8Topbar({
    eyebrow: "Notebook",
    titleHtml: "Notes graduate here when recall makes them <i>stick</i>.",
    chips: [],
    progress: 88,
  });

  return (
    <section className="screen active" id="screen-notebook">
      <div className="pad">
        <div className="notebook">
          {notes.map((note, idx) => (
            <article key={`${note.eyebrow}-${idx}`} className={`note reveal${delayClass(idx)}`}>
              <div className="eyebrow">{note.eyebrow}</div>
              <p>{note.body}</p>
            </article>
          ))}
          <article className={`note note-ghost reveal${delayClass(notes.length)}`}>
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
            <div className="ghost-count">{ghostCount}</div>
            <div className="ghost-label">notes still in review</div>
            <div className="ghost-hint">
              They graduate here once recall proves they belong in long-term memory.
            </div>
          </article>
        </div>
      </div>
    </section>
  );
}
