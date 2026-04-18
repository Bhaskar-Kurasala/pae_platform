import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export interface SpinnerProps extends React.SVGAttributes<SVGSVGElement> {
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  tone?: "default" | "muted" | "primary" | "destructive";
  /** Accessible label. Defaults to "Loading". */
  label?: string;
}

const SIZE_MAP: Record<NonNullable<SpinnerProps["size"]>, string> = {
  xs: "h-3 w-3",
  sm: "h-3.5 w-3.5",
  md: "h-4 w-4",
  lg: "h-5 w-5",
  xl: "h-6 w-6",
};

const TONE_MAP: Record<NonNullable<SpinnerProps["tone"]>, string> = {
  default: "text-foreground",
  muted: "text-muted-foreground",
  primary: "text-primary",
  destructive: "text-destructive",
};

export function Spinner({
  size = "md",
  tone = "muted",
  label = "Loading",
  className,
  ...props
}: SpinnerProps) {
  return (
    <Loader2
      role="status"
      aria-label={label}
      className={cn("animate-spin", SIZE_MAP[size], TONE_MAP[tone], className)}
      {...props}
    />
  );
}
