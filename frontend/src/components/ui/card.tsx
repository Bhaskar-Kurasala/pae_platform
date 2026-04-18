import * as React from "react"

import { cn } from "@/lib/utils"

export type CardVariant = "default" | "interactive" | "ghost" | "elevated"

function Card({
  className,
  size = "default",
  variant = "default",
  loading = false,
  ...props
}: React.ComponentProps<"div"> & {
  size?: "default" | "sm"
  /**
   * - default: static bordered card.
   * - interactive: hover lift + subtle ring change — use when clickable.
   * - ghost: borderless / shell-only — use inside already-bordered containers.
   * - elevated: drops ring and applies elevation-3 (Stripe-style shadow).
   */
  variant?: CardVariant
  /** When true, overlay is dimmed and a skeleton-style pulse animates. */
  loading?: boolean
}) {
  const variantClass =
    variant === "interactive"
      ? "ring-1 ring-foreground/10 hover:ring-foreground/20 hover:-translate-y-0.5 hover:shadow-[var(--elevation-2)] transition-[transform,box-shadow,--tw-ring-color] duration-base ease-out-quad cursor-pointer"
      : variant === "ghost"
        ? ""
        : variant === "elevated"
          ? "shadow-[var(--elevation-3)]"
          : "ring-1 ring-foreground/10"
  return (
    <div
      data-slot="card"
      data-size={size}
      data-variant={variant}
      data-loading={loading || undefined}
      aria-busy={loading || undefined}
      className={cn(
        "group/card relative flex flex-col gap-4 overflow-hidden rounded-xl bg-card py-4 text-sm text-card-foreground has-data-[slot=card-footer]:pb-0 has-[>img:first-child]:pt-0 data-[size=sm]:gap-3 data-[size=sm]:py-3 data-[size=sm]:has-data-[slot=card-footer]:pb-0 *:[img:first-child]:rounded-t-xl *:[img:last-child]:rounded-b-xl",
        variantClass,
        loading && "pointer-events-none",
        className
      )}
      {...props}
    />
  )
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        "group/card-header @container/card-header grid auto-rows-min items-start gap-1 rounded-t-xl px-4 group-data-[size=sm]/card:px-3 has-data-[slot=card-action]:grid-cols-[1fr_auto] has-data-[slot=card-description]:grid-rows-[auto_auto] [.border-b]:pb-4 group-data-[size=sm]/card:[.border-b]:pb-3",
        className
      )}
      {...props}
    />
  )
}

function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-title"
      className={cn(
        "font-heading text-base leading-snug font-medium group-data-[size=sm]/card:text-sm",
        className
      )}
      {...props}
    />
  )
}

function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-action"
      className={cn(
        "col-start-2 row-span-2 row-start-1 self-start justify-self-end",
        className
      )}
      {...props}
    />
  )
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={cn("px-4 group-data-[size=sm]/card:px-3", className)}
      {...props}
    />
  )
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn(
        "flex items-center rounded-b-xl border-t bg-muted/50 p-4 group-data-[size=sm]/card:p-3",
        className
      )}
      {...props}
    />
  )
}

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
}
