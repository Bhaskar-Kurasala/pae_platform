"use client";

import { useEffect } from "react";
import { AlertTriangle, Brain, Info, Loader2, RefreshCw } from "lucide-react";
import { useMisconceptions } from "@/lib/hooks/use-misconceptions";
import { useStudio } from "./studio-context";

export function MisconceptionsPanel() {
  const { code } = useStudio();
  const { mutate, data, isPending, error, reset } = useMisconceptions();

  // Auto-run on first mount if there's code to analyze; thereafter the user
  // hits the refresh button. Avoids thrashing the endpoint on every keystroke.
  useEffect(() => {
    if (code.trim()) mutate(code);
    return () => reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!code.trim()) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-xs text-muted-foreground">
        Write some code, then run the mental-model check.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-2 overflow-hidden p-3 text-sm">
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
        <div className="shrink-0 rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5 text-xs text-destructive">
          {error.message}
        </div>
      )}

      {data && data.items.length === 0 && !isPending && (
        <div className="flex-1 overflow-auto rounded-md border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
          No misconception patterns detected. Your mental model for what the code is doing
          lines up with what Python actually does here.
        </div>
      )}

      {data && data.items.length > 0 && (
        <ul className="flex-1 space-y-2 overflow-auto rounded-md border border-border bg-muted/30 p-2 text-xs">
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
    </div>
  );
}
