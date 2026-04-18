"use client";

import * as React from "react";
import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";
import { cn } from "@/lib/utils";

/**
 * Tooltip wrapper around Base UI.
 *
 * Conventions:
 *  - 300ms open / 100ms close — fast enough to feel responsive, slow enough
 *    to not flicker when the cursor sweeps across UI.
 *  - Tooltips are for *supplementary* information — never essential text,
 *    because they're inaccessible on touch devices.
 *
 * Usage:
 *   <Tooltip content="Save changes" shortcut="mod+s">
 *     <Button size="icon"><Save /></Button>
 *   </Tooltip>
 *
 * For apps with many tooltips, wrap the tree in <TooltipProvider> once to
 * share delays and avoid re-triggering per-tooltip timers.
 */

export interface TooltipProviderProps {
  children: React.ReactNode;
  /** Milliseconds before showing. Default 300. */
  delay?: number;
  /** Milliseconds before hiding. Default 100. */
  closeDelay?: number;
}

export function TooltipProvider({
  children,
  delay = 300,
  closeDelay = 100,
}: TooltipProviderProps) {
  return (
    <TooltipPrimitive.Provider delay={delay} closeDelay={closeDelay}>
      {children}
    </TooltipPrimitive.Provider>
  );
}

export interface TooltipProps {
  children: React.ReactNode;
  content: React.ReactNode;
  /** Optional keyboard shortcut string to render after content. e.g. "mod+s" */
  shortcut?: string;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  sideOffset?: number;
  /** Render the tooltip with a bit of extra lift. */
  elevated?: boolean;
  disabled?: boolean;
  className?: string;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function Tooltip({
  children,
  content,
  shortcut,
  side = "top",
  align = "center",
  sideOffset = 6,
  elevated = false,
  disabled,
  className,
  open,
  defaultOpen,
  onOpenChange,
}: TooltipProps) {
  return (
    <TooltipPrimitive.Root
      disabled={disabled}
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
    >
      <TooltipPrimitive.Trigger render={<>{children}</>} />
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Positioner
          side={side}
          align={align}
          sideOffset={sideOffset}
        >
          <TooltipPrimitive.Popup
            className={cn(
              "z-50 max-w-xs rounded-md border border-foreground/10 bg-popover px-2 py-1 text-xs text-popover-foreground",
              elevated ? "shadow-[var(--elevation-3)]" : "shadow-[var(--elevation-2)]",
              "origin-[var(--transform-origin)] data-[starting-style]:opacity-0 data-[starting-style]:scale-95",
              "data-[ending-style]:opacity-0 data-[ending-style]:scale-95",
              "transition-[opacity,scale] duration-fast ease-out-quad",
              className,
            )}
          >
            <div className="flex items-center gap-2">
              <span>{content}</span>
              {shortcut ? <TooltipShortcut keys={shortcut} /> : null}
            </div>
          </TooltipPrimitive.Popup>
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

function TooltipShortcut({ keys }: { keys: string }) {
  const parts = keys.split("+").map((p) => p.trim());
  return (
    <span className="inline-flex items-center gap-0.5 text-muted-foreground">
      {parts.map((p, i) => (
        <kbd
          key={i}
          className="inline-flex h-4 min-w-[1rem] items-center justify-center rounded border border-foreground/10 bg-foreground/[0.04] px-1 font-mono text-[10px]"
        >
          {p === "mod" ? "⌘" : p.length === 1 ? p.toUpperCase() : p}
        </kbd>
      ))}
    </span>
  );
}
