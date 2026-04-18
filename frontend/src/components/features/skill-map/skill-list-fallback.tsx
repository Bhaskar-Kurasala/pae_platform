"use client";

import { useMemo } from "react";
import type { MasteryLevel } from "@/lib/api-client";
import { useMySkillStates, useSkillGraph } from "@/lib/hooks/use-skills";

const MASTERY_DOT: Record<MasteryLevel, string> = {
  unknown: "bg-muted",
  novice: "bg-amber-400",
  learning: "bg-blue-400",
  proficient: "bg-emerald-400",
  mastered: "bg-emerald-600",
};

export function SkillListFallback() {
  const { data: graph, isLoading } = useSkillGraph();
  const { data: states } = useMySkillStates();

  const masteryById = useMemo(() => {
    const map = new Map<string, MasteryLevel>();
    for (const s of states ?? []) map.set(s.skill_id, s.mastery_level);
    return map;
  }, [states]);

  if (isLoading || !graph) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading skills…</div>
    );
  }

  return (
    <ul className="divide-y divide-border" aria-label="Skill list">
      {graph.nodes.map((n) => {
        const mastery = masteryById.get(n.id) ?? "unknown";
        return (
          <li key={n.id} className="flex items-center gap-3 px-5 py-3">
            <span
              aria-hidden="true"
              className={`h-2.5 w-2.5 rounded-full ${MASTERY_DOT[mastery]}`}
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{n.name}</p>
              <p className="truncate text-xs text-muted-foreground">
                {n.description}
              </p>
            </div>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
              L{n.difficulty}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
