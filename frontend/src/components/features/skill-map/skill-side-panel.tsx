"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import type { MasteryLevel, SkillNode } from "@/lib/api-client";
import { useSkillGraph } from "@/lib/hooks/use-skills";

interface Props {
  skill: SkillNode;
  mastery: MasteryLevel;
  confidence: number;
  allSkills: SkillNode[];
  masteryById: Map<string, { mastery: MasteryLevel; confidence: number }>;
  onClose: () => void;
  onMarkTouched: () => void;
  isTouching: boolean;
  onSkillSelect: (skillId: string) => void;
}

const MASTERED_LEVELS: Set<MasteryLevel> = new Set(["proficient", "mastered"]);

export function SkillSidePanel({
  skill,
  mastery,
  confidence,
  allSkills,
  masteryById,
  onClose,
  onMarkTouched,
  isTouching,
  onSkillSelect,
}: Props) {
  const [query, setQuery] = useState("");
  const { data: graph } = useSkillGraph();

  // Compute prerequisite skills for the selected skill
  const prereqSkills = useMemo(() => {
    if (!graph) return [];
    const prereqIds = graph.edges
      .filter((e) => e.edge_type === "prereq" && e.to_skill_id === skill.id)
      .map((e) => e.from_skill_id);
    return allSkills.filter((s) => prereqIds.includes(s.id));
  }, [graph, skill.id, allSkills]);

  const unmetPrereqs = useMemo(
    () =>
      prereqSkills.filter(
        (s) => !MASTERED_LEVELS.has(masteryById.get(s.id)?.mastery ?? "unknown"),
      ),
    [prereqSkills, masteryById],
  );

  // Search filtered skills list
  const filteredSkills = useMemo(
    () =>
      query.trim().length === 0
        ? []
        : allSkills.filter((s) =>
            s.name.toLowerCase().includes(query.toLowerCase().trim()),
          ),
    [allSkills, query],
  );

  return (
    <aside
      aria-label={`Details for ${skill.name}`}
      className="absolute right-0 top-0 z-10 flex h-full w-80 flex-col border-l border-border bg-background shadow-lg"
    >
      {/* Header */}
      <div className="flex items-start justify-between border-b border-border p-4">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Skill · Difficulty {skill.difficulty}
          </p>
          <h2 className="mt-1 text-lg font-semibold leading-tight">{skill.name}</h2>
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

      {/* Search box */}
      <div className="relative border-b border-border p-3">
        <input
          type="search"
          placeholder="Search skills…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          aria-label="Search skills"
        />
        {filteredSkills.length > 0 && (
          <ul
            role="listbox"
            aria-label="Skill search results"
            className="absolute left-3 right-3 top-full z-20 mt-0.5 max-h-48 overflow-auto rounded-md border border-border bg-popover shadow-md"
          >
            {filteredSkills.map((s) => (
              <li key={s.id} role="option" aria-selected={s.id === skill.id}>
                <button
                  type="button"
                  className="w-full px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground"
                  aria-label={`Navigate to skill: ${s.name}`}
                  onClick={() => {
                    onSkillSelect(s.id);
                    setQuery("");
                  }}
                >
                  {s.name}
                  <span className="ml-2 text-[10px] text-muted-foreground">
                    L{s.difficulty}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Prereq warning */}
      {unmetPrereqs.length > 0 && (
        <div
          className="flex items-start gap-2 border-b border-border bg-yellow-50 p-3 dark:bg-yellow-950/20"
          role="alert"
          aria-label="Prerequisite warning"
        >
          <AlertTriangle
            className="mt-0.5 h-4 w-4 shrink-0 text-yellow-600 dark:text-yellow-400"
            aria-hidden="true"
          />
          <div className="text-xs text-yellow-800 dark:text-yellow-200">
            <p className="font-medium">Prerequisite skills not yet mastered</p>
            <p className="mt-0.5">
              You haven&apos;t mastered{" "}
              {unmetPrereqs.map((s, i) => (
                <span key={s.id}>
                  <button
                    type="button"
                    className="font-semibold underline"
                    aria-label={`Go to prerequisite skill: ${s.name}`}
                    onClick={() => onSkillSelect(s.id)}
                  >
                    {s.name}
                  </button>
                  {i < unmetPrereqs.length - 1 ? " and " : ""}
                </span>
              ))}{" "}
              — this skill may be harder.
            </p>
          </div>
        </div>
      )}

      {/* Skill details */}
      <div className="flex-1 overflow-y-auto p-4">
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

        {/* Prerequisites list */}
        {prereqSkills.length > 0 && (
          <div className="mt-5">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Prerequisites
            </p>
            <ul className="mt-2 space-y-1">
              {prereqSkills.map((s) => {
                const prereqMastery = masteryById.get(s.id)?.mastery ?? "unknown";
                const done = MASTERED_LEVELS.has(prereqMastery);
                return (
                  <li key={s.id} className="flex items-center gap-2 text-sm">
                    <span
                      className={`h-2 w-2 rounded-full ${done ? "bg-emerald-500" : "bg-yellow-400"}`}
                      aria-hidden="true"
                    />
                    <button
                      type="button"
                      className="text-left text-sm hover:underline"
                      aria-label={`Go to prerequisite skill: ${s.name}`}
                      onClick={() => onSkillSelect(s.id)}
                    >
                      {s.name}
                    </button>
                    <span className="ml-auto text-[10px] capitalize text-muted-foreground">
                      {prereqMastery}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>

      {/* Action */}
      <div className="border-t border-border p-4">
        <button
          type="button"
          onClick={onMarkTouched}
          disabled={isTouching}
          aria-label={`Mark ${skill.name} as touched`}
          className="w-full rounded-md border border-border bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
        >
          {isTouching ? "Marking…" : "Mark as touched"}
        </button>
      </div>
    </aside>
  );
}
