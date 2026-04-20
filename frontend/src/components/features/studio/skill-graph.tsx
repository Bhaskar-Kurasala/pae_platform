"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  Variable,
  SquareFunction,
  GitBranch,
  List,
  ShieldAlert,
  FileText,
  Braces,
  Box,
  Sparkles,
  Zap,
  Tag,
  Globe,
  Radio,
  Lock,
  CheckCircle2,
  Network,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SkillNode {
  id: string;
  label: string;
  tier: 1 | 2 | 3;
  keywords: string[];
  Icon: typeof Variable;
}

// ---------------------------------------------------------------------------
// Static skill definitions
// ---------------------------------------------------------------------------

const SKILL_NODES: SkillNode[] = [
  // Tier 1 — Foundation
  {
    id: "variables-types",
    label: "Variables & Types",
    tier: 1,
    keywords: ["int", "str", "float", "bool", ": int", ": str"],
    Icon: Variable,
  },
  {
    id: "functions-args",
    label: "Functions & Args",
    tier: 1,
    keywords: ["def ", "return", "*args", "**kwargs"],
    Icon: SquareFunction,
  },
  {
    id: "control-flow",
    label: "Control Flow",
    tier: 1,
    keywords: ["if ", "for ", "while ", "elif", "else:"],
    Icon: GitBranch,
  },
  {
    id: "lists-dicts",
    label: "Lists & Dicts",
    tier: 1,
    keywords: ["[", "{", ".append(", ".keys(", ".values("],
    Icon: List,
  },

  // Tier 2 — Intermediate
  {
    id: "error-handling",
    label: "Error Handling",
    tier: 2,
    keywords: ["try:", "except", "raise", "finally:"],
    Icon: ShieldAlert,
  },
  {
    id: "file-io",
    label: "File I/O",
    tier: 2,
    keywords: ["open(", "with open"],
    Icon: FileText,
  },
  {
    id: "comprehensions",
    label: "Comprehensions",
    tier: 2,
    // Detect list/dict comprehension: "for" appearing inside "[" or "{"
    keywords: ["for"],
    Icon: Braces,
  },
  {
    id: "classes-oop",
    label: "Classes & OOP",
    tier: 2,
    keywords: ["class ", "self.", "__init__"],
    Icon: Box,
  },

  // Tier 3 — Advanced
  {
    id: "decorators",
    label: "Decorators",
    tier: 3,
    keywords: ["@"],
    Icon: Sparkles,
  },
  {
    id: "async-await",
    label: "Async/Await",
    tier: 3,
    keywords: ["async def", "await "],
    Icon: Zap,
  },
  {
    id: "type-hints",
    label: "Type Hints",
    tier: 3,
    keywords: ["->", ": int", ": str", ": list", ": dict"],
    Icon: Tag,
  },
  {
    id: "api-integration",
    label: "API Integration",
    tier: 3,
    keywords: ["anthropic", "client.messages"],
    Icon: Globe,
  },
  {
    id: "streaming",
    label: "Streaming",
    tier: 3,
    keywords: [".stream(", "text_stream"],
    Icon: Radio,
  },
];

const TOTAL_SKILLS = SKILL_NODES.length;
const STORAGE_KEY = "studio-skills";
const COUNTS_KEY = "studio-skill-counts";

// ---------------------------------------------------------------------------
// Persistence helpers
// ---------------------------------------------------------------------------

function loadPracticedIds(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function savePracticedIds(ids: string[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // quota exceeded — silent
  }
}

function loadCounts(): Record<string, number> {
  try {
    const raw = localStorage.getItem(COUNTS_KEY);
    return raw ? (JSON.parse(raw) as Record<string, number>) : {};
  } catch {
    return {};
  }
}

function saveCounts(counts: Record<string, number>): void {
  try {
    localStorage.setItem(COUNTS_KEY, JSON.stringify(counts));
  } catch {
    // quota exceeded — silent
  }
}

// ---------------------------------------------------------------------------
// Keyword detection
// ---------------------------------------------------------------------------

function detectPracticed(code: string): string[] {
  const practiced: string[] = [];
  for (const node of SKILL_NODES) {
    if (node.id === "comprehensions") {
      // Special case: detect "[...for..." or "{...for..." pattern
      if (/[\[{][^\]}\n]*\bfor\b/.test(code)) {
        practiced.push(node.id);
      }
    } else if (node.keywords.some((kw) => code.includes(kw))) {
      practiced.push(node.id);
    }
  }
  return practiced;
}

// ---------------------------------------------------------------------------
// Unlock logic
// ---------------------------------------------------------------------------

function isTier2Unlocked(practicedIds: string[]): boolean {
  const tier1Practiced = SKILL_NODES.filter(
    (n) => n.tier === 1 && practicedIds.includes(n.id)
  ).length;
  return tier1Practiced >= 2;
}

function isTier3Unlocked(practicedIds: string[]): boolean {
  const tier2Practiced = SKILL_NODES.filter(
    (n) => n.tier === 2 && practicedIds.includes(n.id)
  ).length;
  return tier2Practiced >= 3;
}

// ---------------------------------------------------------------------------
// Skill Node Card
// ---------------------------------------------------------------------------

interface SkillCardProps {
  node: SkillNode;
  practiced: boolean;
  locked: boolean;
  count: number;
  isNew: boolean;
}

function SkillCard({ node, practiced, locked, count, isNew }: SkillCardProps) {
  const { Icon, label, id } = node;

  const baseClasses =
    "relative flex flex-col items-center gap-1.5 rounded-xl border p-3 text-center transition-all duration-300 select-none";

  const stateClasses = locked
    ? "border-border/40 bg-muted/30 opacity-50 cursor-not-allowed"
    : practiced
      ? "border-emerald-500/40 bg-emerald-500/8 cursor-default"
      : "border-border bg-card cursor-default";

  const animationClasses = isNew ? "animate-skill-pulse" : "";

  const iconClasses = locked
    ? "h-5 w-5 text-muted-foreground/50"
    : practiced
      ? "h-5 w-5 text-emerald-500"
      : "h-5 w-5 text-muted-foreground";

  const labelClasses = locked
    ? "text-[11px] font-medium leading-tight text-muted-foreground/50"
    : practiced
      ? "text-[11px] font-medium leading-tight text-foreground"
      : "text-[11px] font-medium leading-tight text-muted-foreground";

  return (
    <div
      className={`${baseClasses} ${stateClasses} ${animationClasses}`}
      aria-label={`${label}${practiced ? ", practiced" : locked ? ", locked" : ", not yet practiced"}`}
      data-skill-id={id}
    >
      {/* Status indicator top-right */}
      {!locked && (
        <span className="absolute right-1.5 top-1.5" aria-hidden="true">
          {practiced ? (
            <CheckCircle2 className="h-3 w-3 text-emerald-500" />
          ) : (
            <span className="block h-2.5 w-2.5 rounded-full border border-border bg-muted" />
          )}
        </span>
      )}

      {locked && (
        <span className="absolute right-1.5 top-1.5" aria-hidden="true">
          <Lock className="h-3 w-3 text-muted-foreground/40" />
        </span>
      )}

      <Icon className={iconClasses} aria-hidden="true" />
      <span className={labelClasses}>{label}</span>

      {practiced && count > 0 && (
        <span className="text-[9px] font-semibold text-emerald-600 dark:text-emerald-400">
          ×{count}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tier header
// ---------------------------------------------------------------------------

function TierHeader({
  tier,
  unlocked,
  practicedCount,
  totalCount,
  unlockRequirement,
}: {
  tier: 1 | 2 | 3;
  unlocked: boolean;
  practicedCount: number;
  totalCount: number;
  unlockRequirement?: string;
}) {
  const tierLabels: Record<1 | 2 | 3, string> = {
    1: "Foundation",
    2: "Intermediate",
    3: "Advanced",
  };

  return (
    <div className="mb-2 flex items-center justify-between">
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {tierLabels[tier]}
        </span>
        {!unlocked && unlockRequirement && (
          <span className="rounded bg-muted px-1.5 py-0.5 text-[9px] text-muted-foreground">
            {unlockRequirement}
          </span>
        )}
      </div>
      <span className="text-[10px] text-muted-foreground">
        {practicedCount}/{totalCount}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main SkillGraph component
// ---------------------------------------------------------------------------

export function SkillGraph() {
  const [practicedIds, setPracticedIds] = useState<string[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [newlyUnlocked, setNewlyUnlocked] = useState<string[]>([]);

  // Load persisted state on mount
  useEffect(() => {
    setPracticedIds(loadPracticedIds());
    setCounts(loadCounts());
  }, []);

  // Clear pulse animation after it plays
  useEffect(() => {
    if (newlyUnlocked.length === 0) return;
    const timer = setTimeout(() => {
      setNewlyUnlocked([]);
    }, 700);
    return () => clearTimeout(timer);
  }, [newlyUnlocked]);

  // Listen for successful run events
  const handleRunSuccess = useCallback((event: Event) => {
    const customEvent = event as CustomEvent<{ code: string }>;
    const code = customEvent.detail?.code ?? "";
    if (!code) return;

    const detected = detectPracticed(code);
    if (detected.length === 0) return;

    setPracticedIds((prev) => {
      const freshIds = detected.filter((id) => !prev.includes(id));
      const merged = Array.from(new Set([...prev, ...detected]));
      savePracticedIds(merged);

      if (freshIds.length > 0) {
        setNewlyUnlocked(freshIds);
      }
      return merged;
    });

    setCounts((prev) => {
      const updated = { ...prev };
      for (const id of detected) {
        updated[id] = (updated[id] ?? 0) + 1;
      }
      saveCounts(updated);
      return updated;
    });
  }, []);

  useEffect(() => {
    window.addEventListener("studio:run-success", handleRunSuccess);
    return () => {
      window.removeEventListener("studio:run-success", handleRunSuccess);
    };
  }, [handleRunSuccess]);

  // Derived unlock states
  const tier2Unlocked = isTier2Unlocked(practicedIds);
  const tier3Unlocked = isTier3Unlocked(practicedIds);

  const practicedCount = practicedIds.length;

  // Per-tier stats
  const tier1Nodes = SKILL_NODES.filter((n) => n.tier === 1);
  const tier2Nodes = SKILL_NODES.filter((n) => n.tier === 2);
  const tier3Nodes = SKILL_NODES.filter((n) => n.tier === 3);

  const tier1Practiced = tier1Nodes.filter((n) =>
    practicedIds.includes(n.id)
  ).length;
  const tier2Practiced = tier2Nodes.filter((n) =>
    practicedIds.includes(n.id)
  ).length;
  const tier3Practiced = tier3Nodes.filter((n) =>
    practicedIds.includes(n.id)
  ).length;

  return (
    <div className="h-full overflow-y-auto px-4 py-4" aria-label="Skill graph">
      {/* Progress summary */}
      <div className="mb-4 flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          <Network className="h-4 w-4 text-primary" aria-hidden="true" />
          <span className="text-sm font-semibold text-foreground">
            Skill Tree
          </span>
        </div>
        <div className="flex-1" />
        <div
          className="text-xs font-medium text-muted-foreground"
          aria-live="polite"
          aria-label={`${practicedCount} of ${TOTAL_SKILLS} skills practiced`}
        >
          <span className="font-bold text-foreground">{practicedCount}</span>
          <span className="mx-0.5">/</span>
          <span>{TOTAL_SKILLS}</span>
          <span className="ml-1">skills practiced</span>
        </div>
      </div>

      {/* Progress bar — width driven by CSS custom property to avoid inline style */}
      <div
        className="mb-5 h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={practicedCount}
        aria-valuemin={0}
        aria-valuemax={TOTAL_SKILLS}
        aria-label="Overall skill progress"
        style={
          { "--skill-pct": `${Math.round((practicedCount / TOTAL_SKILLS) * 100)}%` } as React.CSSProperties
        }
      >
        <div className="h-full w-[var(--skill-pct)] rounded-full bg-emerald-500 transition-all duration-500" />
      </div>

      {/* 3-column grid — one column per tier */}
      <div className="grid grid-cols-3 gap-4">
        {/* Tier 1 — Foundation (always unlocked) */}
        <div>
          <TierHeader
            tier={1}
            unlocked={true}
            practicedCount={tier1Practiced}
            totalCount={tier1Nodes.length}
          />
          <div className="flex flex-col gap-2">
            {tier1Nodes.map((node) => (
              <SkillCard
                key={node.id}
                node={node}
                practiced={practicedIds.includes(node.id)}
                locked={false}
                count={counts[node.id] ?? 0}
                isNew={newlyUnlocked.includes(node.id)}
              />
            ))}
          </div>
        </div>

        {/* Tier 2 — Intermediate */}
        <div>
          <TierHeader
            tier={2}
            unlocked={tier2Unlocked}
            practicedCount={tier2Practiced}
            totalCount={tier2Nodes.length}
            unlockRequirement="2 Foundation needed"
          />
          <div className="flex flex-col gap-2">
            {tier2Nodes.map((node) => (
              <SkillCard
                key={node.id}
                node={node}
                practiced={practicedIds.includes(node.id)}
                locked={!tier2Unlocked}
                count={counts[node.id] ?? 0}
                isNew={newlyUnlocked.includes(node.id)}
              />
            ))}
          </div>
        </div>

        {/* Tier 3 — Advanced */}
        <div>
          <TierHeader
            tier={3}
            unlocked={tier3Unlocked}
            practicedCount={tier3Practiced}
            totalCount={tier3Nodes.length}
            unlockRequirement="3 Intermediate needed"
          />
          <div className="flex flex-col gap-2">
            {tier3Nodes.map((node) => (
              <SkillCard
                key={node.id}
                node={node}
                practiced={practicedIds.includes(node.id)}
                locked={!tier3Unlocked}
                count={counts[node.id] ?? 0}
                isNew={newlyUnlocked.includes(node.id)}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Empty state hint */}
      {practicedCount === 0 && (
        <p className="mt-6 text-center text-xs text-muted-foreground">
          Run some code to start filling your skill tree.
        </p>
      )}
    </div>
  );
}
