"use client";

import { useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Mic, Sparkles, XCircle } from "lucide-react";
import {
  teachBackApi,
  type TeachBackEvaluation,
} from "@/lib/api-client";

function AxisRow({
  label,
  score,
  evidence,
}: {
  label: string;
  score: number;
  evidence: string;
}) {
  const tone =
    score >= 4 ? "text-emerald-500" : score >= 3 ? "text-amber-500" : "text-destructive";
  return (
    <div className="rounded-md border border-border/60 bg-background/60 p-2.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">{label}</span>
        <span className={`font-mono text-xs font-semibold ${tone}`}>{score}/5</span>
      </div>
      <p className="mt-1 text-[11px] leading-snug text-muted-foreground">{evidence}</p>
    </div>
  );
}

export function TeachBackWidget() {
  const [concept, setConcept] = useState("");
  const [explanation, setExplanation] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<TeachBackEvaluation | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!concept.trim() || !explanation.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const ev = await teachBackApi.evaluate({
        concept: concept.trim(),
        explanation: explanation.trim(),
      });
      setResult(ev);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Evaluation failed");
    } finally {
      setSubmitting(false);
    }
  }

  function handleReset() {
    setResult(null);
    setError(null);
    setExplanation("");
  }

  return (
    <section className="rounded-xl border bg-card p-5" aria-labelledby="teach-back-heading">
      <header className="flex items-center gap-2">
        <Mic className="h-4 w-4 text-primary" aria-hidden="true" />
        <h2
          id="teach-back-heading"
          className="text-sm font-semibold uppercase tracking-wider text-muted-foreground"
        >
          Teach it back
        </h2>
      </header>
      <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
        Pick a concept you think you&apos;ve learned. Explain it as if you&apos;re teaching a
        beginner. If you can&apos;t explain it plainly, you don&apos;t own it yet.
      </p>

      {!result && (
        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <div>
            <label htmlFor="teach-back-concept" className="block text-xs font-medium">
              Concept
            </label>
            <input
              id="teach-back-concept"
              type="text"
              value={concept}
              onChange={(e) => setConcept(e.target.value)}
              placeholder="e.g. Embeddings, RAG, attention"
              maxLength={300}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              disabled={submitting}
            />
          </div>
          <div>
            <label htmlFor="teach-back-explanation" className="block text-xs font-medium">
              Your explanation (plain language)
            </label>
            <textarea
              id="teach-back-explanation"
              value={explanation}
              onChange={(e) => setExplanation(e.target.value)}
              rows={6}
              placeholder="Imagine you're explaining this to a friend with no ML background…"
              maxLength={8_000}
              className="mt-1 w-full resize-y rounded-md border border-border bg-background p-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              disabled={submitting}
            />
          </div>
          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={submitting || !concept.trim() || !explanation.trim()}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
          >
            {submitting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {submitting ? "Evaluating…" : "Get feedback"}
          </button>
        </form>
      )}

      {result && (
        <div className="mt-4 space-y-3">
          <div
            className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${
              result.would_beginner_understand
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-500"
                : "border-amber-500/30 bg-amber-500/10 text-amber-500"
            }`}
          >
            {result.would_beginner_understand ? (
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            ) : (
              <AlertCircle className="h-4 w-4" aria-hidden="true" />
            )}
            <span>
              {result.would_beginner_understand
                ? "A beginner would understand this."
                : "A beginner would still be confused."}
            </span>
          </div>

          <div className="grid gap-2 sm:grid-cols-3">
            <AxisRow label="Accuracy" score={result.accuracy.score} evidence={result.accuracy.evidence} />
            <AxisRow
              label="Completeness"
              score={result.completeness.score}
              evidence={result.completeness.evidence}
            />
            <AxisRow
              label="Beginner clarity"
              score={result.beginner_clarity.score}
              evidence={result.beginner_clarity.evidence}
            />
          </div>

          {result.best_sentence && (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs">
              <div className="flex items-center gap-1.5 font-semibold text-emerald-500">
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                Strongest line
              </div>
              <p className="mt-1 italic leading-relaxed">&ldquo;{result.best_sentence}&rdquo;</p>
            </div>
          )}

          {result.missing_ideas.length > 0 && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs">
              <div className="flex items-center gap-1.5 font-semibold text-amber-500">
                <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
                You skipped
              </div>
              <ul className="mt-1 list-inside list-disc space-y-0.5 leading-relaxed">
                {result.missing_ideas.map((idea, idx) => (
                  <li key={idx}>{idea}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="rounded-md border border-primary/30 bg-primary/5 p-3 text-xs">
            <div className="font-semibold text-primary">Go deeper</div>
            <p className="mt-1 leading-relaxed">{result.follow_up}</p>
          </div>

          <button
            type="button"
            onClick={handleReset}
            className="rounded-md border border-border px-3 py-1.5 text-xs font-medium transition hover:bg-muted"
          >
            Try another concept
          </button>
        </div>
      )}
    </section>
  );
}
