"use client";

import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { useStudio } from "./studio-context";

function scoreTone(score: number): string {
  if (score >= 85) return "text-emerald-500";
  if (score >= 65) return "text-amber-500";
  return "text-destructive";
}

export function QualityPanel() {
  const { result } = useStudio();
  const quality = result?.quality;

  if (!quality) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-xs text-muted-foreground">
        Run your code to see style and production-readiness feedback.
      </div>
    );
  }

  const { issues, score, summary } = quality;
  const warnings = issues.filter((i) => i.severity === "warning");
  const infos = issues.filter((i) => i.severity === "info");

  return (
    <div className="flex h-full flex-col gap-2 overflow-hidden p-3 text-sm">
      <header className="flex shrink-0 items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {issues.length === 0 ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-hidden="true" />
          ) : warnings.length > 0 ? (
            <AlertTriangle className="h-4 w-4 text-amber-500" aria-hidden="true" />
          ) : (
            <Info className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          )}
          <span className="text-xs text-muted-foreground">{summary}</span>
        </div>
        <span className={`font-mono text-xs font-semibold ${scoreTone(score)}`}>
          {score}/100
        </span>
      </header>

      {issues.length === 0 ? (
        <div className="flex-1 overflow-auto rounded-md border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
          No style or production-readiness issues detected. A senior reviewer would ship this.
        </div>
      ) : (
        <ul className="flex-1 space-y-1.5 overflow-auto rounded-md border border-border bg-muted/30 p-2 text-xs">
          {issues.map((issue, idx) => {
            const isWarning = issue.severity === "warning";
            const Icon = isWarning ? AlertTriangle : Info;
            return (
              <li
                key={`${issue.rule}-${issue.line}-${idx}`}
                className="flex items-start gap-2 rounded border border-border/60 bg-background/60 px-2 py-1.5"
              >
                <Icon
                  className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
                    isWarning ? "text-amber-500" : "text-muted-foreground"
                  }`}
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
                    <span>line {issue.line}</span>
                    <span className="rounded bg-foreground/5 px-1 py-0.5 text-foreground">
                      {issue.rule}
                    </span>
                  </div>
                  <p className="mt-0.5 leading-snug text-foreground">{issue.message}</p>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {(warnings.length > 0 || infos.length > 0) && (
        <footer className="shrink-0 text-[11px] text-muted-foreground">
          {warnings.length} warning{warnings.length === 1 ? "" : "s"} ·{" "}
          {infos.length} suggestion{infos.length === 1 ? "" : "s"}
        </footer>
      )}
    </div>
  );
}
