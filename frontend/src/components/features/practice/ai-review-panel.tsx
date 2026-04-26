"use client";

import { CheckCircle2, AlertTriangle, Sparkles, Info } from "lucide-react";
import type { SeniorReview, SeniorReviewSeverity } from "@/lib/api-client";

const VERDICT_LABEL: Record<SeniorReview["verdict"], string> = {
  approve: "Approve",
  request_changes: "Request changes",
  comment: "Comment",
};

const VERDICT_CLASS: Record<SeniorReview["verdict"], string> = {
  approve:
    "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
  request_changes:
    "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30",
  comment: "bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30",
};

const SEVERITY_LABEL: Record<SeniorReviewSeverity, string> = {
  nit: "Nit",
  suggestion: "Suggestion",
  concern: "Concern",
  blocking: "Blocking",
};

const SEVERITY_CLASS: Record<SeniorReviewSeverity, string> = {
  nit: "text-muted-foreground",
  suggestion: "text-sky-600 dark:text-sky-400",
  concern: "text-amber-600 dark:text-amber-400",
  blocking: "text-destructive",
};

interface AiReviewPanelProps {
  review: SeniorReview | null;
  loading: boolean;
  error: string | null;
  onJumpToLine: (line: number) => void;
}

export function AiReviewPanel({
  review,
  loading,
  error,
  onJumpToLine,
}: AiReviewPanelProps) {
  if (loading) {
    return (
      <div
        data-testid="ai-review-loading"
        className="flex items-center gap-2 p-4 text-sm text-muted-foreground"
      >
        <Sparkles className="h-4 w-4 animate-pulse" aria-hidden="true" />
        Senior engineer is reviewing your code…
      </div>
    );
  }

  if (error) {
    return (
      <div
        data-testid="ai-review-error"
        className="m-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300"
      >
        {error}
      </div>
    );
  }

  if (!review) {
    return (
      <div
        data-testid="ai-review-empty"
        className="p-6 text-sm text-muted-foreground"
      >
        Click <span className="font-medium">Get AI Review</span> for feedback
        from a senior engineer.
      </div>
    );
  }

  // Group comments by line.
  const byLine = new Map<number, SeniorReview["comments"]>();
  for (const c of review.comments) {
    const arr = byLine.get(c.line) ?? [];
    arr.push(c);
    byLine.set(c.line, arr);
  }
  const lines = [...byLine.keys()].sort((a, b) => a - b);

  return (
    <div data-testid="ai-review-content" className="space-y-4 p-4">
      <div className="flex items-start gap-3">
        <span
          data-testid="ai-review-verdict"
          className={`inline-flex shrink-0 items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${VERDICT_CLASS[review.verdict]}`}
        >
          {VERDICT_LABEL[review.verdict]}
        </span>
        <h3
          data-testid="ai-review-headline"
          className="text-sm font-semibold leading-snug text-foreground"
        >
          {review.headline}
        </h3>
      </div>

      {review.strengths.length > 0 && (
        <section data-testid="ai-review-strengths">
          <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            Strengths
          </p>
          <ul className="ml-5 list-disc space-y-1 text-sm text-foreground">
            {review.strengths.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </section>
      )}

      {lines.length > 0 && (
        <section data-testid="ai-review-comments">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-amber-700 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
            Comments
          </p>
          <ul className="space-y-2">
            {lines.map((line) => {
              const items = byLine.get(line) ?? [];
              return (
                <li
                  key={line}
                  className="rounded-md border border-border/60 bg-card p-2.5"
                >
                  <button
                    type="button"
                    data-testid={`ai-review-line-${line}`}
                    onClick={() => onJumpToLine(line)}
                    className="text-xs font-mono text-primary hover:underline"
                    aria-label={`Jump to line ${line}`}
                  >
                    Line {line}
                  </button>
                  <ul className="mt-1.5 space-y-1.5">
                    {items.map((c, i) => (
                      <li key={i} className="text-sm">
                        <span
                          className={`mr-1.5 text-xs font-semibold uppercase ${SEVERITY_CLASS[c.severity]}`}
                        >
                          {SEVERITY_LABEL[c.severity]}
                        </span>
                        <span className="text-foreground">{c.message}</span>
                        {c.suggested_change && (
                          <pre className="mt-1.5 overflow-x-auto rounded bg-muted px-2 py-1 font-mono text-xs">
                            {c.suggested_change}
                          </pre>
                        )}
                      </li>
                    ))}
                  </ul>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section
        data-testid="ai-review-next-step"
        className="rounded-lg border border-primary/20 bg-primary/5 p-3"
      >
        <p className="mb-0.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-primary">
          <Info className="h-3.5 w-3.5" aria-hidden="true" />
          Next step
        </p>
        <p className="text-sm text-foreground">{review.next_step}</p>
      </section>
    </div>
  );
}
