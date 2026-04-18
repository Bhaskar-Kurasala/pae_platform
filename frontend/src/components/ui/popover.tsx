"use client";

import * as React from "react";
import { Popover as PopoverPrimitive } from "@base-ui/react/popover";
import { cn } from "@/lib/utils";

/**
 * Popover wrapper around Base UI.
 *
 * Layered compound API — use Root/Trigger/Content when you need full control,
 * or the convenience <Popover trigger={...}>content</Popover> for simple cases.
 */

export const PopoverRoot = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverPortal = PopoverPrimitive.Portal;
export const PopoverClose = PopoverPrimitive.Close;

export interface PopoverContentProps
  extends React.ComponentProps<typeof PopoverPrimitive.Popup> {
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  sideOffset?: number;
  /** Popup width. Default "auto". */
  width?: number | string;
  /** Elevation level. Default 3 (Stripe-style shadow stack). */
  elevation?: 2 | 3 | 4 | 5;
}

export function PopoverContent({
  className,
  children,
  side = "bottom",
  align = "start",
  sideOffset = 6,
  width,
  elevation = 3,
  style,
  ...props
}: PopoverContentProps) {
  const elevationClass =
    elevation === 2
      ? "shadow-[var(--elevation-2)]"
      : elevation === 4
        ? "shadow-[var(--elevation-4)]"
        : elevation === 5
          ? "shadow-[var(--elevation-5)]"
          : "shadow-[var(--elevation-3)]";
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Positioner
        side={side}
        align={align}
        sideOffset={sideOffset}
      >
        <PopoverPrimitive.Popup
          className={cn(
            "z-50 min-w-[12rem] rounded-xl border border-foreground/10 bg-popover p-1 text-popover-foreground outline-none",
            elevationClass,
            "origin-[var(--transform-origin)]",
            "data-[starting-style]:opacity-0 data-[starting-style]:scale-95 data-[starting-style]:-translate-y-1",
            "data-[ending-style]:opacity-0 data-[ending-style]:scale-95 data-[ending-style]:-translate-y-1",
            "transition-[opacity,scale,translate] duration-fast ease-out-quad",
            className,
          )}
          style={{ width, ...style }}
          {...props}
        >
          {children}
        </PopoverPrimitive.Popup>
      </PopoverPrimitive.Positioner>
    </PopoverPrimitive.Portal>
  );
}

// Convenience shorthand
export interface PopoverProps {
  trigger: React.ReactNode;
  children: React.ReactNode;
  side?: PopoverContentProps["side"];
  align?: PopoverContentProps["align"];
  sideOffset?: number;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  elevation?: PopoverContentProps["elevation"];
  contentClassName?: string;
}

export function Popover({
  trigger,
  children,
  side,
  align,
  sideOffset,
  defaultOpen,
  open,
  onOpenChange,
  elevation,
  contentClassName,
}: PopoverProps) {
  return (
    <PopoverRoot
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
    >
      <PopoverTrigger render={<>{trigger}</>} />
      <PopoverContent
        side={side}
        align={align}
        sideOffset={sideOffset}
        elevation={elevation}
        className={contentClassName}
      >
        {children}
      </PopoverContent>
    </PopoverRoot>
  );
}
