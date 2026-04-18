"use client";

import { X } from "lucide-react";
import type { MasteryLevel, SkillNode } from "@/lib/api-client";

interface Props {
  skill: SkillNode;
  mastery: MasteryLevel;
  confidence: number;
  onClose: () => void;
  onMarkTouched: () => void;
  isTouching: boolean;
}

export function SkillSidePanel({
  skill,
  mastery,
  confidence,
  onClose,
  onMarkTouched,
  isTouching,
}: Props) {
  return (
    <aside
      aria-label={`Details for ${skill.name}`}
      className="absolute right-0 top-0 z-10 flex h-full w-80 flex-col border-l border-border bg-background p-5 shadow-lg"
    >
      <div className="mb-3 flex items-start justify-between">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Skill · Difficulty {skill.difficulty}
          </p>
          <h2 className="mt-1 text-lg font-semibold leading-tight">
            {skill.name}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close skill details"
          className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <p className="text-sm text-muted-foreground">{skill.description}</p>
      <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">Mastery</dt>
          <dd className="font-medium capitalize">{mastery}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Confidence</dt>
          <dd className="font-medium">{(confidence * 100).toFixed(0)}%</dd>
        </div>
      </dl>
      <div className="mt-auto pt-5">
        <button
          type="button"
          onClick={onMarkTouched}
          disabled={isTouching}
          className="w-full rounded-md border border-border bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
        >
          {isTouching ? "Marking…" : "Mark as touched"}
        </button>
      </div>
    </aside>
  );
}
