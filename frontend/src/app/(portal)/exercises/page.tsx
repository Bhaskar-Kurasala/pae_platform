"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { exercisesApi, type ExerciseResponse } from "@/lib/api-client";

const DIFFICULTY_LABEL: Record<string, string> = {
  beginner: "Beginner",
  easy: "Beginner",
  intermediate: "Intermediate",
  medium: "Intermediate",
  advanced: "Advanced",
  hard: "Advanced",
};

const DIFFICULTY_RANK: Record<string, number> = {
  beginner: 0,
  easy: 0,
  intermediate: 1,
  medium: 1,
  advanced: 2,
  hard: 2,
};

function pickCapstone(list: ExerciseResponse[]): ExerciseResponse | null {
  if (list.length === 0) return null;
  return [...list].sort((a, b) => {
    const da = DIFFICULTY_RANK[a.difficulty] ?? 1;
    const db = DIFFICULTY_RANK[b.difficulty] ?? 1;
    if (db !== da) return db - da;
    return (b.points ?? 0) - (a.points ?? 0);
  })[0];
}

function ExerciseRow({ ex, index }: { ex: ExerciseResponse; index: number }) {
  const delay = index % 3 === 0 ? "" : ` delay-${index % 3}`;
  const tagline =
    ex.description?.split(/(?<=[.!?])\s+/)[0]?.slice(0, 110) ?? ex.exercise_type;
  return (
    <Link
      href={`/exercises/${ex.id}`}
      aria-label={`Start exercise: ${ex.title}`}
      className={`ex-row reveal${delay}`}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="ex-row-t">{ex.title}</div>
        <div className="ex-row-s">
          {DIFFICULTY_LABEL[ex.difficulty] ?? ex.difficulty} · {tagline}
        </div>
      </div>
      <span className="ex-row-cta" aria-hidden="true">
        Start <span className="ex-arrow">→</span>
      </span>
    </Link>
  );
}

export default function ExercisesPage() {
  const { data, isLoading, error } = useQuery<ExerciseResponse[]>({
    queryKey: ["exercises", "list"],
    queryFn: () => exercisesApi.list(),
  });

  const { capstone, practice } = useMemo(() => {
    const list = data ?? [];
    const cap = pickCapstone(list);
    return {
      capstone: cap,
      practice: list.filter((e) => e.id !== cap?.id),
    };
  }, [data]);

  return (
    <section className="screen active" id="screen-exercises">
      <div className="pad ex-pad">
        <header className="ex-header reveal">
          <div className="ex-eyebrow-top">Forge</div>
          <h2 className="ex-title">
            Exercises you&apos;ll <i>actually</i> remember.
          </h2>
          <p className="ex-lede">
            Hand-picked challenges that mirror the work senior AI engineers do every day. Each one
            ships with a rubric, hidden tests, and a senior review when you submit.
          </p>
        </header>

        {isLoading && (
          <div className="ex-status reveal" role="status" aria-live="polite">
            <span className="ex-spinner" aria-hidden="true" />
            Loading the practice set…
          </div>
        )}

        {error && (
          <div className="ex-error reveal" role="alert">
            We couldn&apos;t load exercises right now. Refresh or try again in a moment.
          </div>
        )}

        {data && data.length === 0 && (
          <div className="ex-empty reveal">
            No exercises yet. Once your course is configured, hand-picked reps will appear here.
          </div>
        )}

        {capstone && (
          <Link
            href={`/exercises/${capstone.id}`}
            className="ex-hero reveal"
            aria-label={`Open capstone exercise: ${capstone.title}`}
          >
            <div className="ex-eye">Capstone · Required for promotion</div>
            <div className="ex-t">{capstone.title}</div>
            <div className="ex-s">
              {capstone.description?.trim() ||
                "The most demanding rep on the board. Senior review on submission — this is the work your promotion interview is built on."}
            </div>
            <span className="ex-hero-cta">
              Open in Studio <span aria-hidden="true">→</span>
            </span>
          </Link>
        )}

        {practice.length > 0 && (
          <>
            <div className="ex-section-h reveal">Practice exercises</div>
            <div className="ex-list">
              {practice.map((ex, idx) => (
                <ExerciseRow key={ex.id} ex={ex} index={idx} />
              ))}
            </div>
          </>
        )}
      </div>

      <style jsx global>{`
        .ex-pad {
          padding: 32px clamp(20px, 4vw, 56px) 64px;
          max-width: 980px;
          margin: 0 auto;
        }
        .ex-header {
          margin-bottom: 28px;
          padding-bottom: 22px;
          border-bottom: 1px solid var(--line);
        }
        .ex-eyebrow-top {
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.18em;
          text-transform: uppercase;
          color: var(--forest-2);
          margin-bottom: 8px;
        }
        .ex-title {
          font-family: var(--display);
          font-weight: 500;
          font-size: clamp(28px, 3.6vw, 38px);
          line-height: 1.18;
          letter-spacing: -0.015em;
          color: var(--ink);
          margin: 0 0 10px;
        }
        .ex-title i {
          color: var(--forest-2);
          font-style: italic;
        }
        .ex-lede {
          color: var(--muted);
          font-size: 14.5px;
          line-height: 1.6;
          max-width: 620px;
          margin: 0;
        }

        .ex-hero {
          display: block;
          background: var(--panel);
          border: 1px solid var(--line);
          border-left: 4px solid var(--gold-2, #c89a4a);
          border-radius: 16px;
          padding: 28px 30px;
          margin-bottom: 28px;
          text-decoration: none;
          color: inherit;
          transition:
            transform 0.18s ease,
            box-shadow 0.18s ease,
            border-color 0.18s ease;
        }
        .ex-hero:hover {
          transform: translateY(-2px);
          box-shadow: 0 12px 32px rgba(184, 134, 45, 0.12);
        }
        .ex-eye {
          font-size: 10.5px;
          letter-spacing: 0.22em;
          text-transform: uppercase;
          color: var(--gold-2, #c89a4a);
          margin-bottom: 10px;
          font-weight: 700;
        }
        .ex-t {
          font-family: var(--display);
          font-size: clamp(20px, 2.4vw, 26px);
          font-weight: 500;
          letter-spacing: -0.02em;
          color: var(--ink);
          margin-bottom: 8px;
          line-height: 1.25;
        }
        .ex-s {
          font-size: 13.5px;
          color: var(--muted);
          margin-bottom: 18px;
          line-height: 1.6;
          max-width: 640px;
        }
        .ex-hero-cta {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          background: linear-gradient(135deg, var(--forest), var(--forest-3));
          color: #fff;
          padding: 11px 18px;
          border-radius: 12px;
          font-size: 13px;
          font-weight: 700;
          letter-spacing: 0.01em;
          box-shadow: 0 10px 24px rgba(53, 109, 80, 0.18);
        }

        .ex-section-h {
          font-family: var(--display);
          font-size: 18px;
          font-weight: 500;
          color: var(--ink);
          margin: 8px 0 14px;
          letter-spacing: -0.01em;
        }
        .ex-list {
          display: grid;
          gap: 8px;
        }
        .ex-row {
          background: var(--panel);
          border: 1px solid var(--line);
          border-radius: 12px;
          padding: 18px 22px;
          display: flex;
          align-items: center;
          gap: 16px;
          text-decoration: none;
          color: inherit;
          transition:
            transform 0.16s ease,
            box-shadow 0.16s ease,
            border-color 0.16s ease;
        }
        .ex-row:hover {
          transform: translateY(-1px);
          border-color: rgba(36, 79, 57, 0.22);
          box-shadow: 0 6px 20px rgba(16, 18, 14, 0.05);
        }
        .ex-row-t {
          font-family: var(--display);
          font-size: 15.5px;
          font-weight: 500;
          letter-spacing: -0.01em;
          color: var(--ink);
        }
        .ex-row-s {
          font-size: 12px;
          color: var(--muted);
          margin-top: 3px;
          line-height: 1.5;
        }
        .ex-row-cta {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-size: 12.5px;
          font-weight: 600;
          color: var(--forest);
          background: var(--forest-soft);
          padding: 7px 14px;
          border-radius: 999px;
          border: 1px solid rgba(36, 79, 57, 0.12);
          white-space: nowrap;
        }
        .ex-row:hover .ex-arrow {
          transform: translateX(2px);
        }
        .ex-arrow {
          transition: transform 0.18s ease;
          display: inline-block;
        }

        .ex-status {
          display: inline-flex;
          align-items: center;
          gap: 10px;
          color: var(--muted);
          font-size: 14px;
          padding: 24px 0;
        }
        .ex-spinner {
          width: 14px;
          height: 14px;
          border-radius: 50%;
          border: 2px solid var(--line);
          border-top-color: var(--forest-2);
          animation: ex-spin 0.8s linear infinite;
          display: inline-block;
        }
        @keyframes ex-spin {
          to {
            transform: rotate(360deg);
          }
        }
        .ex-error {
          color: var(--ink);
          background: rgba(232, 190, 114, 0.1);
          border: 1px solid rgba(232, 190, 114, 0.24);
          padding: 14px 18px;
          border-radius: 12px;
          font-size: 13.5px;
          max-width: 560px;
        }
        .ex-empty {
          border: 1px dashed var(--line);
          border-radius: 14px;
          padding: 24px 26px;
          color: var(--muted);
          background: var(--panel-2);
          max-width: 600px;
          font-size: 13.5px;
          line-height: 1.6;
        }
      `}</style>
    </section>
  );
}
