import { cn } from "@/lib/utils";

/**
 * PageShell — the single source of truth for page content width & padding.
 *
 * Use this instead of ad-hoc `max-w-*` / `mx-auto` classes on page roots.
 * Changing the width of every `default` page is one edit here.
 *
 * Variants (Tailwind max-widths):
 *   narrow  → 42rem (672px)  — forms, onboarding, reading-optimized text
 *   default → 64rem (1024px) — most pages: lists, dashboards, detail pages
 *   wide    → 80rem (1280px) — chat, interview, code-heavy surfaces
 *   full    → none            — edge-to-edge (studio, editors, full canvases)
 *
 * Density:
 *   comfortable (default) → p-6 md:p-8
 *   compact               → p-4 md:p-6   (chat headers, tight toolbars)
 *   flush                 → no padding   (when a child manages its own padding)
 */

type PageShellVariant = "narrow" | "default" | "wide" | "full";
type PageShellDensity = "comfortable" | "compact" | "flush";

interface PageShellProps {
  children: React.ReactNode;
  variant?: PageShellVariant;
  density?: PageShellDensity;
  /** Pin the shell to the viewport height (good for chat/interview). */
  fullHeight?: boolean;
  /** Extra classes merged onto the shell — escape hatch, prefer props. */
  className?: string;
}

const variantClasses: Record<PageShellVariant, string> = {
  narrow: "max-w-2xl",
  default: "max-w-5xl",
  wide: "max-w-7xl",
  full: "",
};

const densityClasses: Record<PageShellDensity, string> = {
  comfortable: "p-6 md:p-8",
  compact: "p-4 md:p-6",
  flush: "",
};

export function PageShell({
  children,
  variant = "default",
  density = "comfortable",
  fullHeight = false,
  className,
}: PageShellProps) {
  return (
    <div
      className={cn(
        "mx-auto w-full",
        variantClasses[variant],
        densityClasses[density],
        fullHeight && "h-[calc(100vh-4rem)] flex flex-col gap-4",
        className,
      )}
    >
      {children}
    </div>
  );
}
