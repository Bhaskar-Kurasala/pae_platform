"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  Loader2,
  Lightbulb,
  Microscope,
  XCircle,
} from "lucide-react";
import {
  portfolioAutopsyApi,
  type PortfolioAutopsy,
} from "@/lib/api-client";

function scoreTone(score: number, max: number): string {
  const pct = score / max;
  if (pct >= 0.8) return "text-emerald-500";
  if (pct >= 0.5) return "text-amber-500";
  return "text-destructive";
}

function AxisRow({
  label,
  score,
  assessment,
}: {
  label: string;
  score: number;
  assessment: string;
}) {
  const tone = scoreTone(score, 5);
  return (
    <div className="rounded-md border border-border/60 bg-background/60 p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">{label}</span>
        <span className={`font-mono text-xs font-semibold ${tone}`}>
          {score}/5
        </span>
      </div>
      <p className="mt-1 text-[11px] leading-snug text-muted-foreground">
        {assessment}
      </p>
    </div>
  );
}

export function PortfolioAutopsyWidget() {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [code, setCode] = useState("");
  const [wentWell, setWentWell] = useState("");
  const [wasHard, setWasHard] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<PortfolioAutopsy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || description.trim().length < 20 || submitting) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const autopsy = await portfolioAutopsyApi.create({
        project_title: title.trim(),
        project_description: description.trim(),
        code: code.trim() || undefined,
        what_went_well_self: wentWell.trim() || undefined,
        what_was_hard_self: wasHard.trim() || undefined,
      });
      setResult(autopsy);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Autopsy failed");
    } finally {
      setSubmitting(false);
    }
  }

  function handleReset() {
    setResult(null);
    setError(null);
  }

  if (!expanded && !result) {
    return (
      <section className="rounded-xl border bg-card p-5">
        <div className="flex items-start gap-3">
          <Microscope
            className="mt-0.5 h-5 w-5 text-primary"
            aria-hidden="true"
          />
          <div className="flex-1">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Portfolio autopsy
            </h2>
            <p className="mt-1 text-sm leading-relaxed">
              Just shipped something? Run an autopsy — a senior engineer&apos;s
              honest read of what you&apos;d do differently if you built it
              again now. Not a grade. A retro.
            </p>
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium transition hover:bg-muted"
            >
              Start an autopsy
            </button>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section
      className="rounded-xl border bg-card p-5"
      aria-labelledby="autopsy-heading"
    >
      <header className="flex items-center gap-2">
        <Microscope className="h-4 w-4 text-primary" aria-hidden="true" />
        <h2
          id="autopsy-heading"
          className="text-sm font-semibold uppercase tracking-wider text-muted-foreground"
        >
          Portfolio autopsy
        </h2>
      </header>

      {!result && (
        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <div>
            <label
              htmlFor="autopsy-title"
              className="block text-xs font-medium"
            >
              Project title
            </label>
            <input
              id="autopsy-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. RAG chatbot over company docs"
              maxLength={200}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              disabled={submitting}
            />
          </div>
          <div>
            <label
              htmlFor="autopsy-description"
              className="block text-xs font-medium"
            >
              What did you build? (design, stack, goal)
            </label>
            <textarea
              id="autopsy-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              placeholder="A FastAPI endpoint that takes a question, embeds it, looks up top-3 chunks in pgvector, and streams a Claude answer. Users are our internal support team…"
              maxLength={8_000}
              className="mt-1 w-full resize-y rounded-md border border-border bg-background p-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              disabled={submitting}
            />
            <p className="mt-1 text-[11px] text-muted-foreground">
              Minimum 20 characters. The more specific, the sharper the
              feedback.
            </p>
          </div>
          <div>
            <label htmlFor="autopsy-code" className="block text-xs font-medium">
              Code (optional — paste the core module)
            </label>
            <textarea
              id="autopsy-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              rows={6}
              placeholder="The main handler, the retry logic, whatever you want the reviewer to actually see."
              maxLength={40_000}
              className="mt-1 w-full resize-y rounded-md border border-border bg-background p-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-primary/50"
              disabled={submitting}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label
                htmlFor="autopsy-went-well"
                className="block text-xs font-medium"
              >
                What you think went well (optional)
              </label>
              <textarea
                id="autopsy-went-well"
                value={wentWell}
                onChange={(e) => setWentWell(e.target.value)}
                rows={3}
                maxLength={2_000}
                className="mt-1 w-full resize-y rounded-md border border-border bg-background p-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                disabled={submitting}
              />
            </div>
            <div>
              <label
                htmlFor="autopsy-was-hard"
                className="block text-xs font-medium"
              >
                What felt hard (optional)
              </label>
              <textarea
                id="autopsy-was-hard"
                value={wasHard}
                onChange={(e) => setWasHard(e.target.value)}
                rows={3}
                maxLength={2_000}
                className="mt-1 w-full resize-y rounded-md border border-border bg-background p-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                disabled={submitting}
              />
            </div>
          </div>
          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </div>
          )}
          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={
                submitting ||
                !title.trim() ||
                description.trim().length < 20
              }
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
            >
              {submitting ? (
                <Loader2
                  className="h-3.5 w-3.5 animate-spin"
                  aria-hidden="true"
                />
              ) : (
                <Microscope className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              {submitting ? "Running autopsy…" : "Run autopsy"}
            </button>
            <button
              type="button"
              onClick={() => setExpanded(false)}
              disabled={submitting}
              className="text-xs font-medium text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {result && (
        <div className="mt-4 space-y-4">
          <div className="rounded-md border border-border bg-background/60 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Gauge className="h-3.5 w-3.5" aria-hidden="true" />
                Overall
              </div>
              <div
                className={`font-mono text-2xl font-semibold ${scoreTone(
                  result.overall_score,
                  100,
                )}`}
              >
                {result.overall_score}
                <span className="ml-0.5 text-sm text-muted-foreground">
                  /100
                </span>
              </div>
            </div>
            <p className="mt-2 text-sm leading-relaxed">{result.headline}</p>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <AxisRow
              label="Architecture"
              score={result.architecture.score}
              assessment={result.architecture.assessment}
            />
            <AxisRow
              label="Failure handling"
              score={result.failure_handling.score}
              assessment={result.failure_handling.assessment}
            />
            <AxisRow
              label="Observability"
              score={result.observability.score}
              assessment={result.observability.assessment}
            />
            <AxisRow
              label="Scope discipline"
              score={result.scope_discipline.score}
              assessment={result.scope_discipline.assessment}
            />
          </div>

          {result.what_worked.length > 0 && (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs">
              <div className="flex items-center gap-1.5 font-semibold text-emerald-500">
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                What worked — keep doing this
              </div>
              <ul className="mt-1.5 list-inside list-disc space-y-0.5 leading-relaxed">
                {result.what_worked.map((item, idx) => (
                  <li key={idx}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs">
            <div className="flex items-center gap-1.5 font-semibold text-amber-500">
              <Lightbulb className="h-3.5 w-3.5" aria-hidden="true" />
              What to do differently next time
            </div>
            <div className="mt-2 space-y-2">
              {result.what_to_do_differently.map((f, idx) => (
                <div
                  key={idx}
                  className="rounded-md border border-border/60 bg-background/50 p-2.5"
                >
                  <div className="text-xs font-semibold">{f.issue}</div>
                  <p className="mt-1 text-[11px] leading-snug text-muted-foreground">
                    Why it matters: {f.why_it_matters}
                  </p>
                  <p className="mt-1 text-[11px] leading-snug text-emerald-600 dark:text-emerald-400">
                    ↪ {f.what_to_do_differently}
                  </p>
                </div>
              ))}
            </div>
          </div>

          {result.production_gaps.length > 0 && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs">
              <div className="flex items-center gap-1.5 font-semibold text-destructive">
                <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
                Blockers to shipping this to production
              </div>
              <ul className="mt-1.5 list-inside list-disc space-y-0.5 leading-relaxed">
                {result.production_gaps.map((gap, idx) => (
                  <li key={idx}>{gap}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="rounded-md border border-primary/30 bg-primary/5 p-3 text-xs">
            <div className="flex items-center gap-1.5 font-semibold text-primary">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
              Try this next
            </div>
            <p className="mt-1 leading-relaxed">{result.next_project_seed}</p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleReset}
              className="rounded-md border border-border px-3 py-1.5 text-xs font-medium transition hover:bg-muted"
            >
              Run another autopsy
            </button>
            <button
              type="button"
              onClick={() => {
                setExpanded(false);
                setResult(null);
              }}
              className="text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
