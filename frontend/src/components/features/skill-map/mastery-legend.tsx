const LEGEND_ITEMS = [
  { label: "Mastered", colorClass: "bg-emerald-500" },
  { label: "Proficient", colorClass: "bg-emerald-400/70" },
  { label: "Learning", colorClass: "bg-blue-400/70" },
  { label: "Novice", colorClass: "bg-amber-400/60" },
  { label: "Not started", colorClass: "bg-muted border border-border" },
] as const;

export function MasteryLegend() {
  return (
    <div
      className="flex flex-wrap gap-3 rounded-md border border-border bg-card px-3 py-2"
      aria-label="Mastery level legend"
    >
      {LEGEND_ITEMS.map(({ label, colorClass }) => (
        <div key={label} className="flex items-center gap-1.5">
          <span
            className={`h-3 w-3 rounded-full ${colorClass}`}
            aria-hidden="true"
          />
          <span className="text-xs text-muted-foreground">{label}</span>
        </div>
      ))}
    </div>
  );
}
