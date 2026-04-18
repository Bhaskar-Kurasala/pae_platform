import { cn } from "@/lib/utils";

export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Pre-built shapes. For custom, omit and use className. */
  shape?: "text" | "title" | "avatar" | "button" | "card" | "chip";
  /** Number of stacked shapes. Only applies to shape=text. Default 1. */
  lines?: number;
}

const SHAPE_CLASSES: Record<NonNullable<SkeletonProps["shape"]>, string> = {
  text: "h-4 w-full rounded",
  title: "h-6 w-2/3 rounded-md",
  avatar: "h-8 w-8 rounded-full",
  button: "h-8 w-24 rounded-lg",
  card: "h-32 w-full rounded-2xl",
  chip: "h-5 w-16 rounded-full",
};

export function Skeleton({
  shape,
  lines = 1,
  className,
  ...props
}: SkeletonProps) {
  const base = "bg-foreground/[0.06] animate-pulse";
  if (shape === "text" && lines > 1) {
    return (
      <div className="space-y-2" {...props}>
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className={cn(
              base,
              SHAPE_CLASSES.text,
              i === lines - 1 && "w-4/5",
              className,
            )}
            aria-hidden="true"
          />
        ))}
      </div>
    );
  }
  return (
    <div
      className={cn(base, shape && SHAPE_CLASSES[shape], className)}
      aria-hidden="true"
      {...props}
    />
  );
}
