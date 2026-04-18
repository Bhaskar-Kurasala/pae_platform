"use client";

import { HelpCircle } from "lucide-react";
import {
  useMyPreferences,
  useUpdatePreferences,
} from "@/lib/hooks/use-preferences";
import { cn } from "@/lib/utils";

/**
 * Compact toggle that switches the tutor between "standard" and
 * "socratic_strict" modes. When strict, the tutor never gives direct answers —
 * only questions. The UI weight here is deliberately small: it sits in the
 * sidebar footer so it's always reachable but never in the way.
 */
export function TutorModeToggle() {
  const { data: prefs } = useMyPreferences();
  const update = useUpdatePreferences();
  const strict = prefs?.tutor_mode === "socratic_strict";

  function toggle() {
    update.mutate({
      tutor_mode: strict ? "standard" : "socratic_strict",
    });
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={strict}
      aria-label={
        strict
          ? "Disable Socratic strict mode"
          : "Enable Socratic strict mode (questions only)"
      }
      title={
        strict
          ? "Socratic strict: tutor asks questions only"
          : "Tutor mode: standard"
      }
      className={cn(
        "shrink-0 rounded p-1 transition-colors",
        strict
          ? "bg-primary/15 text-primary hover:bg-primary/25"
          : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
      )}
    >
      <HelpCircle className="h-4 w-4" aria-hidden="true" />
    </button>
  );
}
