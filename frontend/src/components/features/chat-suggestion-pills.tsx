"use client";

import { cn } from "@/lib/utils";

export interface SuggestionPill {
  key: string;
  label: string;
}

export interface ChatSuggestionPillsProps {
  pills: SuggestionPill[];
  onPick: (pill: SuggestionPill, index: number) => void;
  variant?: "clarify" | "followup";
  disabled?: boolean;
}

export function ChatSuggestionPills({
  pills,
  onPick,
  variant = "clarify",
  disabled = false,
}: ChatSuggestionPillsProps) {
  if (pills.length === 0) return null;

  const isClarify = variant === "clarify";
  const label = isClarify ? "How should I answer?" : "Keep going with…";
  const telemetryName = isClarify
    ? "tutor.clarify_pill_clicked"
    : "tutor.followup_clicked";

  return (
    <div
      className="mt-3 mb-4"
      role="group"
      aria-label={label}
      data-testid={`chat-pills-${variant}`}
    >
      <p className="text-xs text-muted-foreground mb-2 select-none">{label}</p>
      <div className="flex flex-wrap gap-2">
        {pills.map((pill, index) => (
          <button
            key={pill.key}
            type="button"
            onClick={() => {
              if (typeof window !== "undefined") {
                window.dispatchEvent(
                  new CustomEvent(telemetryName, {
                    detail: { pill_key: pill.key, pill_index: index },
                  }),
                );
              }
              onPick(pill, index);
            }}
            disabled={disabled}
            className={cn(
              "rounded-full border px-3.5 py-1.5 text-sm transition-colors",
              "border-border bg-background text-foreground/90",
              "hover:bg-muted hover:text-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:border-primary",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              isClarify &&
                "border-primary/30 bg-primary/5 hover:bg-primary/10 text-primary",
            )}
          >
            {pill.label}
          </button>
        ))}
      </div>
    </div>
  );
}
