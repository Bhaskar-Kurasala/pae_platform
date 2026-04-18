"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Circle, Loader2, Target, XCircle } from "lucide-react";
import {
  retrievalQuizApi,
  type RetrievalQuestion,
  type RetrievalQuizResult,
} from "@/lib/api-client";
import { cn } from "@/lib/utils";

export interface RetrievalQuizInlineProps {
  lessonId: string;
}

export function RetrievalQuizInline({ lessonId }: RetrievalQuizInlineProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [questions, setQuestions] = useState<RetrievalQuestion[] | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<RetrievalQuizResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    retrievalQuizApi
      .get(lessonId)
      .then((res) => {
        if (cancelled) return;
        setQuestions(res.questions);
      })
      .catch(() => {
        if (cancelled) return;
        setError("Couldn't load the retrieval quiz. You can still continue.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [lessonId]);

  async function handleSubmit() {
    if (!questions || questions.length === 0) return;
    setSubmitting(true);
    try {
      const graded = await retrievalQuizApi.submit(lessonId, answers);
      setResult(graded);
    } catch {
      setError("Could not grade the quiz. Your progress is saved either way.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div
        className="rounded-xl border bg-card p-5 text-sm text-muted-foreground flex items-center gap-2"
        aria-live="polite"
      >
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Building your retrieval quiz…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        {error}
      </div>
    );
  }

  // Empty-bank fallback: a reflection prompt (ticket edge-case).
  if (!questions || questions.length === 0) {
    return (
      <div className="rounded-xl border bg-card p-5 space-y-2">
        <div className="flex items-center gap-2">
          <Target className="h-4 w-4 text-primary" aria-hidden="true" />
          <h2 className="font-semibold">Quick reflection</h2>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">
          No quiz is queued for this lesson yet. In one sentence — what is the
          single most important thing you want to remember from this lesson a
          week from now?
        </p>
      </div>
    );
  }

  if (result) {
    return (
      <div className="rounded-xl border bg-card p-5 space-y-4">
        <div className="flex items-center gap-2">
          <Target className="h-4 w-4 text-primary" aria-hidden="true" />
          <h2 className="font-semibold">
            Retrieval quiz — {result.correct} / {result.total} correct
          </h2>
        </div>
        <ul className="space-y-3">
          {result.graded.map((g, i) => {
            const q = questions.find((qq) => qq.id === g.mcq_id);
            return (
              <li key={g.mcq_id} className="text-sm">
                <div className="flex items-start gap-2">
                  {g.correct ? (
                    <CheckCircle2
                      className="h-4 w-4 mt-0.5 text-primary shrink-0"
                      aria-hidden="true"
                    />
                  ) : (
                    <XCircle
                      className="h-4 w-4 mt-0.5 text-destructive shrink-0"
                      aria-hidden="true"
                    />
                  )}
                  <div className="flex-1">
                    <p className="font-medium text-foreground">
                      {i + 1}. {q?.question ?? "Question"}
                    </p>
                    {!g.correct && (
                      <p className="mt-1 text-muted-foreground">
                        Correct answer:{" "}
                        <span className="font-medium text-foreground">
                          {g.correct_answer}
                        </span>
                      </p>
                    )}
                    {g.explanation && (
                      <p className="mt-1 text-muted-foreground text-xs leading-relaxed">
                        {g.explanation}
                      </p>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    );
  }

  const allAnswered = questions.every((q) => answers[q.id]);

  return (
    <div className="rounded-xl border bg-card p-5 space-y-4">
      <div>
        <div className="flex items-center gap-2">
          <Target className="h-4 w-4 text-primary" aria-hidden="true" />
          <h2 className="font-semibold">Retrieval quiz</h2>
        </div>
        <p className="text-xs text-muted-foreground mt-1">
          Two-minute recall check. You remember twice as much when you retrieve
          than when you re-read.
        </p>
      </div>

      <ol className="space-y-5">
        {questions.map((q, idx) => (
          <li key={q.id} className="space-y-2">
            <p className="text-sm font-medium">
              {idx + 1}. {q.question}
            </p>
            <ul
              className="space-y-1.5"
              role="radiogroup"
              aria-label={`Question ${idx + 1} options`}
            >
              {Object.entries(q.options).map(([key, text]) => {
                const selected = answers[q.id] === key;
                return (
                  <li key={key}>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      onClick={() =>
                        setAnswers((prev) => ({ ...prev, [q.id]: key }))
                      }
                      disabled={submitting}
                      className={cn(
                        "w-full flex items-start gap-2 text-left rounded-lg border px-3 py-2 text-sm transition-colors",
                        "hover:bg-muted disabled:opacity-60",
                        selected
                          ? "border-primary bg-primary/5"
                          : "border-border bg-background",
                      )}
                    >
                      {selected ? (
                        <CheckCircle2
                          className="h-4 w-4 mt-0.5 text-primary shrink-0"
                          aria-hidden="true"
                        />
                      ) : (
                        <Circle
                          className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0"
                          aria-hidden="true"
                        />
                      )}
                      <span>
                        <span className="font-medium text-foreground mr-2">
                          {key}.
                        </span>
                        {String(text)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </li>
        ))}
      </ol>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={submitting || !allAnswered}
          className="inline-flex items-center gap-2 h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60 transition-colors"
        >
          {submitting && (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          )}
          {submitting ? "Grading…" : "Check answers"}
        </button>
      </div>
    </div>
  );
}
