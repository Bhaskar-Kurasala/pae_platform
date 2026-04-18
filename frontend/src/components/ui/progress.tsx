"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 0–100. Set to null for indeterminate progress. */
  value: number | null;
  /** Max value. Default 100. */
  max?: number;
  size?: "xs" | "sm" | "md" | "lg";
  tone?: "primary" | "success" | "warning" | "destructive";
  /** Accessible label. */
  label?: string;
}

const SIZE_MAP: Record<NonNullable<ProgressProps["size"]>, string> = {
  xs: "h-1",
  sm: "h-1.5",
  md: "h-2",
  lg: "h-3",
};

const TONE_MAP: Record<NonNullable<ProgressProps["tone"]>, string> = {
  primary: "bg-primary",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  destructive: "bg-destructive",
};

export function Progress({
  value,
  max = 100,
  size = "sm",
  tone = "primary",
  label,
  className,
  ...props
}: ProgressProps) {
  const isIndeterminate = value === null;
  const pct = isIndeterminate
    ? null
    : Math.min(100, Math.max(0, (value / max) * 100));

  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={isIndeterminate ? undefined : value}
      className={cn(
        "relative w-full overflow-hidden rounded-full bg-foreground/[0.08]",
        SIZE_MAP[size],
        className,
      )}
      {...props}
    >
      {isIndeterminate ? (
        <div
          className={cn(
            "absolute inset-y-0 w-1/3 rounded-full",
            TONE_MAP[tone],
            "animate-[progress-indeterminate_1.4s_ease-in-out_infinite]",
          )}
          aria-hidden="true"
        />
      ) : (
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-base ease-out-quad",
            TONE_MAP[tone],
          )}
          style={{ width: `${pct}%` }}
          aria-hidden="true"
        />
      )}
    </div>
  );
}
