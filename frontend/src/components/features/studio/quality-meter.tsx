"use client";

import { useStudio } from "./studio-context";

function barColor(score: number): string {
  if (score >= 80) return "bg-emerald-500";
  if (score >= 50) return "bg-amber-500";
  return "bg-red-500";
}

export function QualityMeter() {
  const { result, hasRunOnce } = useStudio();

  if (!hasRunOnce) return null;

  const rawScore = result?.quality?.score ?? 100;
  const score = Math.max(0, Math.min(100, Math.round(rawScore)));
  const color = barColor(score);

  return (
    <div
      className="inline-flex w-20 flex-col gap-0.5 rounded-md border border-border bg-background px-2 py-1"
      aria-label={`Code quality score: ${score} out of 100`}
      title={`Quality: ${score}/100`}
    >
      <span className="text-[10px] font-semibold leading-none text-muted-foreground">
        Quality: {score}
      </span>
      <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${score}%` }}
          aria-hidden="true"
        />
      </div>
    </div>
  );
}
