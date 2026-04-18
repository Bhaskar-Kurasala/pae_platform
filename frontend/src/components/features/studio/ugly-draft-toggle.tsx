"use client";

import { FileWarning } from "lucide-react";
import {
  useMyPreferences,
  useUpdatePreferences,
} from "@/lib/hooks/use-preferences";
import { cn } from "@/lib/utils";

/**
 * Toggle for ugly-draft mode, displayed in the Studio Tutor pane header.
 * Writes the shared user-preferences row so the setting persists across
 * sessions and devices. Visually understated but identifiable (amber
 * accent when on).
 */
export function UglyDraftToggle() {
  const { data: prefs } = useMyPreferences();
  const update = useUpdatePreferences();
  const on = prefs?.ugly_draft_mode === true;

  return (
    <button
      type="button"
      onClick={() => update.mutate({ ugly_draft_mode: !on })}
      aria-pressed={on}
      aria-label={
        on ? "Disable ugly-draft mode" : "Enable ugly-draft mode"
      }
      title={
        on
          ? "Ugly-draft mode: tutor is locked until you run your first attempt"
          : "Ugly-draft mode is off"
      }
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
        on
          ? "bg-amber-500/15 text-amber-700 dark:text-amber-300 hover:bg-amber-500/25"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      <FileWarning className="h-3 w-3" aria-hidden="true" />
      <span>Ugly draft</span>
    </button>
  );
}
