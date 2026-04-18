"use client";

import type { Motivation } from "@/lib/api-client";

const MOTIVATION_LABEL: Record<Motivation, string> = {
  career_switch: "Career switch",
  skill_up: "Skill up",
  interview: "Interview prep",
  curiosity: "Curiosity",
};

interface PathLegendProps {
  motivation: Motivation | null;
  highlighted: number;
  total: number;
}

export function PathLegend({ motivation, highlighted, total }: PathLegendProps) {
  const label = motivation ? MOTIVATION_LABEL[motivation] : "Default (skill up)";
  return (
    <div className="absolute left-3 top-3 z-10 rounded-md border border-border bg-card/95 px-3 py-2 text-xs shadow-sm backdrop-blur">
      <div className="font-semibold text-card-foreground">
        Path: {label}
      </div>
      <div className="text-muted-foreground">
        {highlighted} of {total} skills recommended
      </div>
    </div>
  );
}
