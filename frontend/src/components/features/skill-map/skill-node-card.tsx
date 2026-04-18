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

/** Map mastery level to a 0–1 progress value for the ring. */
const MASTERY_PROGRESS: Record<MasteryLevel, number> = {
  unknown: 0,
  novice: 0.25,
  learning: 0.5,
  proficient: 0.75,
  mastered: 1,
};

export interface SkillNodeData {
  name: string;
  slug: string;
  difficulty: number;
  mastery: MasteryLevel;
  onPath: boolean;
  hasUnmetPrereqs?: boolean;
  [key: string]: unknown;
}

interface ProgressRingProps {
  progress: number; // 0–1
  size?: number;
}

function ProgressRing({ progress, size = 32 }: ProgressRingProps) {
  const r = (size - 4) / 2;
  const circumference = 2 * Math.PI * r;
  const filled = circumference * (1 - progress);
  return (
    <svg
      width={size}
      height={size}
      className="-rotate-90"
      aria-hidden="true"
      role="img"
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="currentColor"
        strokeWidth={3}
        className="text-muted"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="currentColor"
        strokeWidth={3}
        strokeDasharray={circumference}
        strokeDashoffset={filled}
        strokeLinecap="round"
        className="text-primary transition-all duration-500"
      />
    </svg>
  );
}

export function SkillNodeCard({ data }: { data: SkillNodeData }) {
  const border = MASTERY_BORDER[data.mastery];
  const dim = data.onPath ? "" : "opacity-30 grayscale";
  const progress = MASTERY_PROGRESS[data.mastery];

  return (
    <div
      className={`relative min-w-[180px] max-w-[220px] rounded-md border-2 ${border} bg-card px-3 py-2 text-card-foreground shadow-sm transition-opacity ${dim}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-muted-foreground" />

      {/* Prereq warning badge */}
      {data.hasUnmetPrereqs && (
        <span
          className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-yellow-400 text-[9px] font-bold text-yellow-900"
          title="Prerequisite skills not yet mastered"
          aria-label="Prerequisite skills not yet mastered"
        >
          !
        </span>
      )}

      <div className="flex items-center gap-2">
        {/* Progress ring */}
        <div
          className="shrink-0"
          aria-label={`Mastery progress: ${MASTERY_LABEL[data.mastery]}`}
        >
          <ProgressRing progress={progress} size={28} />
        </div>

        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            {MASTERY_LABEL[data.mastery]} · L{data.difficulty}
          </div>
          <div className="mt-0.5 text-sm font-semibold leading-tight">{data.name}</div>
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-muted-foreground"
      />
    </div>
  );
}
