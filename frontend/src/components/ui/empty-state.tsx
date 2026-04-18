import * as React from "react";
import { cn } from "@/lib/utils";

export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  /** Primary action — usually a <Button />. */
  action?: React.ReactNode;
  /** Secondary action rendered next to the primary. */
  secondaryAction?: React.ReactNode;
  /** Visual density. `compact` reduces padding for inline contexts. */
  size?: "compact" | "default" | "spacious";
  /** Render a bordered card container. Default true. */
  bordered?: boolean;
}

const SIZE_MAP: Record<NonNullable<EmptyStateProps["size"]>, string> = {
  compact: "p-5 gap-3",
  default: "p-8 md:p-10 gap-4",
  spacious: "p-12 md:p-16 gap-5",
};

export function EmptyState({
  icon,
  title,
  description,
  action,
  secondaryAction,
  size = "default",
  bordered = true,
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        bordered && "rounded-2xl border border-foreground/10 bg-card",
        SIZE_MAP[size],
        className,
      )}
      {...props}
    >
      {icon ? (
        <div
          className="flex h-11 w-11 items-center justify-center rounded-xl bg-foreground/[0.04] text-muted-foreground"
          aria-hidden="true"
        >
          {icon}
        </div>
      ) : null}
      <div className="max-w-sm space-y-1">
        <h3 className="text-base font-semibold leading-snug">{title}</h3>
        {description ? (
          <p className="text-sm text-muted-foreground leading-relaxed">
            {description}
          </p>
        ) : null}
      </div>
      {(action || secondaryAction) && (
        <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
          {action}
          {secondaryAction}
        </div>
      )}
    </div>
  );
}
