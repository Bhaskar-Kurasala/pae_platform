"use client";

import { useSyncExternalStore } from "react";
import { cn } from "@/lib/utils";

/**
 * <Kbd keys="mod+k" /> renders the shortcut as platform-correct chips:
 *   mac: ⌘ K
 *   win: Ctrl K
 *
 * Accepts the same shortcut string format as useShortcut.
 */

const KEY_DISPLAY: Record<string, { mac: string; other: string }> = {
  mod: { mac: "⌘", other: "Ctrl" },
  meta: { mac: "⌘", other: "⊞" },
  ctrl: { mac: "⌃", other: "Ctrl" },
  shift: { mac: "⇧", other: "Shift" },
  alt: { mac: "⌥", other: "Alt" },
  enter: { mac: "↵", other: "Enter" },
  escape: { mac: "Esc", other: "Esc" },
  esc: { mac: "Esc", other: "Esc" },
  backspace: { mac: "⌫", other: "Backspace" },
  delete: { mac: "⌦", other: "Del" },
  tab: { mac: "⇥", other: "Tab" },
  space: { mac: "Space", other: "Space" },
  up: { mac: "↑", other: "↑" },
  down: { mac: "↓", other: "↓" },
  left: { mac: "←", other: "←" },
  right: { mac: "→", other: "→" },
  arrowup: { mac: "↑", other: "↑" },
  arrowdown: { mac: "↓", other: "↓" },
  arrowleft: { mac: "←", other: "←" },
  arrowright: { mac: "→", other: "→" },
};

function detectMac(): boolean {
  if (typeof navigator === "undefined") return false;
  return /Mac|iPhone|iPad|iPod/i.test(navigator.platform);
}

// SSR returns false; client resolves synchronously on first render.
// useSyncExternalStore picks up the difference cleanly.
function subscribePlatform(): () => void {
  return () => {};
}
function getPlatformSnapshot(): boolean {
  return detectMac();
}
function getPlatformServerSnapshot(): boolean {
  return false;
}

function displayKey(key: string, mac: boolean): string {
  const lower = key.toLowerCase();
  const mapping = KEY_DISPLAY[lower];
  if (mapping) return mac ? mapping.mac : mapping.other;
  return key.length === 1 ? key.toUpperCase() : key;
}

export interface KbdProps extends React.HTMLAttributes<HTMLSpanElement> {
  keys: string;
  size?: "sm" | "md";
  /** Render all key chips inside a single outer span for tighter inline use. */
  compact?: boolean;
}

export function Kbd({
  keys,
  size = "sm",
  compact = false,
  className,
  ...props
}: KbdProps) {
  const mac = useSyncExternalStore(
    subscribePlatform,
    getPlatformSnapshot,
    getPlatformServerSnapshot,
  );

  const parts = keys.split("+").map((p) => p.trim());
  const base = cn(
    "inline-flex items-center justify-center rounded-md border border-foreground/10 bg-foreground/[0.04]",
    "font-mono text-muted-foreground tabular-nums select-none",
    size === "sm" ? "min-w-[1.25rem] h-5 px-1 text-[10px]" : "min-w-[1.5rem] h-6 px-1.5 text-xs",
    className,
  );

  if (compact) {
    return (
      <span className={base} {...props}>
        {parts.map((p, i) => (
          <span key={i} className={i > 0 ? "ml-0.5" : ""}>
            {displayKey(p, mac)}
          </span>
        ))}
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1" {...props}>
      {parts.map((p, i) => (
        <span key={i} className={base}>
          {displayKey(p, mac)}
        </span>
      ))}
    </span>
  );
}
