"use client";

import { HelpCircle } from "lucide-react";
import {
  useMyPreferences,
  useUpdatePreferences,
} from "@/lib/hooks/use-preferences";
import {
  SOCRATIC_LEVEL_LABELS,
  type SocraticLevel,
} from "@/lib/api-client";
import { Popover } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/**
 * Compact popover-triggered control that sets the tutor's socratic intensity
 * on a 0-3 scale. Replaces the binary strict toggle — same footprint in the
 * sidebar, four graded options so students can self-select push intensity.
 *
 * The menu is split out as `SocraticSliderMenu` so it can be rendered
 * standalone in tests without stubbing the Base UI portal.
 */

const LEVEL_DESCRIPTIONS: Record<SocraticLevel, string> = {
  0: "Direct answers by default.",
  1: "One guiding question, then a direct answer.",
  2: "Question first, hints, answer after reasoning.",
  3: "Questions only — never direct answers.",
};

interface SocraticSliderMenuProps {
  level: SocraticLevel;
  onChange: (next: SocraticLevel) => void;
}

export function SocraticSliderMenu({ level, onChange }: SocraticSliderMenuProps) {
  const levels: SocraticLevel[] = [0, 1, 2, 3];
  return (
    <div className="flex flex-col gap-1">
      <div className="px-2 pt-1 pb-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Socratic intensity
        </p>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          How much the tutor pushes you to reason before answering.
        </p>
      </div>
      <div
        role="radiogroup"
        aria-label="Socratic intensity"
        className="flex flex-col gap-0.5"
      >
        {levels.map((lvl) => {
          const selected = lvl === level;
          return (
            <button
              key={lvl}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => {
                if (!selected) onChange(lvl);
              }}
              className={cn(
                "flex items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
                selected
                  ? "bg-primary/10 text-primary"
                  : "hover:bg-accent hover:text-accent-foreground",
              )}
            >
              <span
                className={cn(
                  "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
                  selected
                    ? "border-primary bg-primary/20"
                    : "border-foreground/20",
                )}
                aria-hidden="true"
              >
                {selected && (
                  <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                )}
              </span>
              <span className="flex flex-col gap-0.5">
                <span className="text-xs font-medium capitalize leading-tight">
                  {SOCRATIC_LEVEL_LABELS[lvl]}
                </span>
                <span className="text-[11px] leading-snug text-muted-foreground">
                  {LEVEL_DESCRIPTIONS[lvl]}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function SocraticSlider() {
  const { data: prefs } = useMyPreferences();
  const update = useUpdatePreferences();
  const level = (prefs?.socratic_level ?? 0) as SocraticLevel;
  const active = level > 0;

  return (
    <Popover
      side="top"
      align="end"
      contentClassName="w-64 p-2"
      trigger={
        <button
          type="button"
          aria-label={`Socratic intensity: ${SOCRATIC_LEVEL_LABELS[level]}`}
          title={`Socratic: ${SOCRATIC_LEVEL_LABELS[level]}`}
          className={cn(
            "shrink-0 rounded p-1 transition-colors",
            active
              ? "bg-primary/15 text-primary hover:bg-primary/25"
              : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
          )}
        >
          <HelpCircle className="h-4 w-4" aria-hidden="true" />
        </button>
      }
    >
      <SocraticSliderMenu
        level={level}
        onChange={(next) => update.mutate({ socratic_level: next })}
      />
    </Popover>
  );
}
