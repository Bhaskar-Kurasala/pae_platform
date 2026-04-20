"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Info,
  Loader2,
  RefreshCw,
  Target,
  XCircle,
} from "lucide-react";
import { useMisconceptions } from "@/lib/hooks/use-misconceptions";
import { useStudio } from "./studio-context";

// ---------------------------------------------------------------------------
// Mental Model Check panel
//
// State machine:
//   "predict"  → code present, not yet run → show prediction textarea
//   "compare"  → hasRunOnce && predictedOutput was captured → show comparison
//   "idle"     → no code, or ran without capturing a prediction
//
// Misconceptions analysis (LLM-powered) is shown below the comparison.
// ---------------------------------------------------------------------------

type PanelPhase = "predict" | "compare" | "idle";

export function MisconceptionsPanel() {
  const { code, result, hasRunOnce, run, running } = useStudio();
  const { mutate, data, isPending, error, reset } = useMisconceptions();

  // The text the student typed before running
  const [draft, setDraft] = useState("");
  // Locked-in prediction (set when "Lock in & Run" is clicked)
  const [predictedOutput, setPredictedOutput] = useState<string | null>(null);
  // Track whether this particular run was preceded by a prediction
  const predictionRunRef = useRef(false);

  // Reset prediction state when code changes significantly (new session)
  const prevCodeRef = useRef(code);
  useEffect(() => {
    if (prevCodeRef.current !== code && !hasRunOnce) {
      // Code changed before any run — clear old prediction
      setPredictedOutput(null);
      predictionRunRef.current = false;
      setDraft("");
    }
    prevCodeRef.current = code;
  }, [code, hasRunOnce]);

  // Auto-run misconceptions analysis on first mount if code exists
  useEffect(() => {
    if (code.trim()) mutate(code);
    return () => reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Determine current phase
  const phase: PanelPhase = (() => {
    if (!code.trim()) return "idle";
    if (hasRunOnce && predictedOutput !== null) return "compare";
    if (!hasRunOnce && code.trim().length > 0) return "predict";
    return "idle";
  })();

  // -------------------------------------------------------------------------
  // Handlers
  // -------------------------------------------------------------------------

  function handleLockAndRun() {
    const trimmedDraft = draft.trim();
    if (trimmedDraft) {
      setPredictedOutput(trimmedDraft);
      predictionRunRef.current = true;
    }
    void run();
  }

  // -------------------------------------------------------------------------
  // Comparison helpers
  // -------------------------------------------------------------------------

  const actualOutput = result?.stdout?.trim() ?? "";
  const isExactMatch =
    predictedOutput !== null &&
    actualOutput === predictedOutput.trim();

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  if (phase === "idle") {
    return (
      <div className="flex h-full items-center justify-center p-4 text-xs text-muted-foreground">
        Write some code to activate the mental model check.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-auto p-3 text-sm">
      {/* ------------------------------------------------------------------ */}
      {/* Phase: predict — student hasn't run yet                             */}
      {/* ------------------------------------------------------------------ */}
      {phase === "predict" && (
        <section aria-label="Predict output before running" className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
            <Target className="h-4 w-4 text-primary" aria-hidden="true" />
            <span>What do you expect this code to output?</span>
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Write your prediction <strong>before</strong> running. This trains your mental model
            by forcing you to think through the code first.
          </p>
          <textarea
            aria-label="Write your prediction of the output here"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="e.g. 5&#10;Hello, world!"
            rows={4}
            className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 font-mono text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleLockAndRun}
              disabled={running || draft.trim().length === 0}
              aria-label="Lock in prediction and run code"
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {running ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <Brain className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              Lock in prediction &amp; Run
            </button>
            <button
              type="button"
              onClick={() => { void run(); }}
              disabled={running}
              aria-label="Skip prediction and run code"
              className="text-xs text-muted-foreground underline-offset-2 hover:underline disabled:opacity-50"
            >
              Skip — just run
            </button>
          </div>
        </section>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Phase: compare — show prediction vs actual                          */}
      {/* ------------------------------------------------------------------ */}
      {phase === "compare" && predictedOutput !== null && (
        <section aria-label="Prediction comparison" className="flex flex-col gap-2">
          {/* Match / mismatch banner */}
          <div
            className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs font-semibold ${
              isExactMatch
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                : "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400"
            }`}
            role="status"
            aria-live="polite"
          >
            {isExactMatch ? (
              <>
                <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>Exact match! Great mental model 🎯</span>
              </>
            ) : (
              <>
                <XCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>Not quite — compare below to understand the gap.</span>
              </>
            )}
          </div>

          {/* Side-by-side (stacked on narrow panels) */}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                You predicted
              </p>
              <pre className="overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted/30 px-2 py-2 font-mono text-[11px] text-foreground">
                {predictedOutput}
              </pre>
            </div>
            <div className="flex flex-col gap-1">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Actual output
              </p>
              <pre className="overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted/30 px-2 py-2 font-mono text-[11px] text-foreground">
                {actualOutput || <span className="italic text-muted-foreground">(no output)</span>}
              </pre>
            </div>
          </div>

          {/* Reset — let student try again with a new prediction */}
          <button
            type="button"
            onClick={() => {
              setPredictedOutput(null);
              setDraft("");
              predictionRunRef.current = false;
            }}
            aria-label="Clear prediction and try again"
            className="self-start text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            Clear prediction
          </button>
        </section>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Misconceptions analysis (shown in both predict + compare phases)    */}
      {/* ------------------------------------------------------------------ */}
      <section aria-label="Misconceptions analysis" className="flex flex-col gap-2">
        <header className="flex shrink-0 items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Brain className="h-4 w-4" aria-hidden="true" />
            <span>
              {isPending
                ? "Analyzing mental models…"
                : (data?.summary ?? "Click refresh to check for misconceptions.")}
            </span>
          </div>
          <button
            type="button"
            onClick={() => mutate(code)}
            disabled={isPending}
            aria-label="Re-check mental models"
            className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-xs font-medium transition hover:bg-muted disabled:opacity-50"
          >
            {isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-3 w-3" aria-hidden="true" />
            )}
            Re-check
          </button>
        </header>

        {error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5 text-xs text-destructive">
            {error.message}
          </div>
        )}

        {data && data.items.length === 0 && !isPending && (
          <div className="rounded-md border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
            No misconception patterns detected. Your mental model for what the code is doing
            lines up with what Python actually does here.
          </div>
        )}

        {data && data.items.length > 0 && (
          <ul className="space-y-2 rounded-md border border-border bg-muted/30 p-2 text-xs">
            {data.items.map((m, idx) => {
              const isWarning = m.severity === "warning";
              const Icon = isWarning ? AlertTriangle : Info;
              return (
                <li
                  key={`${m.code}-${m.line}-${idx}`}
                  className="rounded border border-border/60 bg-background/60 p-2"
                >
                  <div className="flex items-start gap-2">
                    <Icon
                      className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
                        isWarning ? "text-amber-500" : "text-muted-foreground"
                      }`}
                      aria-hidden="true"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
                        <span>line {m.line}</span>
                        <span className="rounded bg-foreground/5 px-1 py-0.5 text-foreground">
                          {m.code}
                        </span>
                      </div>
                      <p className="mt-0.5 font-semibold leading-snug text-foreground">{m.title}</p>
                      <div className="mt-1 space-y-1 leading-snug">
                        <p>
                          <span className="text-muted-foreground">You probably think:</span>{" "}
                          <span className="italic">&ldquo;{m.you_think}&rdquo;</span>
                        </p>
                        <p>
                          <span className="text-muted-foreground">Actually:</span> {m.actually}
                        </p>
                        <p className="text-primary">↪ {m.fix_hint}</p>
                      </div>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
