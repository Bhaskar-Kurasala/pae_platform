"use client";

import { Handle, Position } from "@xyflow/react";
import type { MasteryLevel } from "@/lib/api-client";

const MASTERY_BORDER: Record<MasteryLevel, string> = {
  unknown: "border-border",
  novice: "border-amber-400/60",
  learning: "border-blue-400/70",
  proficient: "border-emerald-400/70",
  mastered: "border-emerald-500",
};

const MASTERY_LABEL: Record<MasteryLevel, string> = {
  unknown: "Not started",
  novice: "Novice",
  learning: "Learning",
  proficient: "Proficient",
  mastered: "Mastered",
};

export interface SkillNodeData {
  name: string;
  slug: string;
  difficulty: number;
  mastery: MasteryLevel;
  onPath: boolean;
  [key: string]: unknown;
}

export function SkillNodeCard({ data }: { data: SkillNodeData }) {
  const border = MASTERY_BORDER[data.mastery];
  const dim = data.onPath ? "" : "opacity-30 grayscale";
  return (
    <div
      className={`min-w-[180px] max-w-[220px] rounded-md border-2 ${border} bg-card px-3 py-2 text-card-foreground shadow-sm transition-opacity ${dim}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-muted-foreground" />
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {MASTERY_LABEL[data.mastery]} · L{data.difficulty}
      </div>
      <div className="mt-1 text-sm font-semibold leading-tight">{data.name}</div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-muted-foreground"
      />
    </div>
  );
}
