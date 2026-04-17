import { type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { GradientMesh } from "./gradient-mesh";
import { MotionFade } from "./motion-fade";

interface SectionHeroProps {
  /** Optional badge text shown above the headline. */
  badge?: string;
  /** Main headline — can be a ReactNode for styled text. */
  title: ReactNode;
  /** Supporting subtitle text. */
  subtitle: string;
  /** CTA button(s) row. */
  actions: ReactNode;
  /** Optional additional content below the actions (e.g. social proof). */
  children?: ReactNode;
  className?: string;
}

/**
 * Marketing section hero wrapper.
 *
 * Renders a centered section with GradientMesh background and
 * MotionFade entrance animations. Used on the landing page and
 * other Zone 1 (marketing) pages.
 *
 * Usage:
 *   <SectionHero
 *     badge="Now in Beta"
 *     title={<>Learn <span className="text-primary">GenAI</span> Engineering</>}
 *     subtitle="20 AI agents teach you production-grade AI — on your schedule."
 *     actions={<><Button>Start Free</Button><Button variant="outline">See Agents</Button></>}
 *   />
 */
export function SectionHero({
  badge,
  title,
  subtitle,
  actions,
  children,
  className,
}: SectionHeroProps) {
  return (
    <section
      className={cn(
        "relative overflow-hidden py-24 px-4",
        className,
      )}
    >
      <GradientMesh />

      <div className="max-w-4xl mx-auto text-center">
        {badge && (
          <MotionFade delay={0}>
            <div className="inline-flex items-center rounded-full border border-border bg-muted px-3 py-1 text-xs font-medium text-muted-foreground mb-6">
              {badge}
            </div>
          </MotionFade>
        )}

        <MotionFade delay={0.05}>
          <h1 className="text-[clamp(2.5rem,5vw,4rem)] font-bold tracking-tight leading-[1.1] mb-4">
            {title}
          </h1>
        </MotionFade>

        <MotionFade delay={0.1}>
          <p className="text-lg text-muted-foreground leading-7 max-w-2xl mx-auto mb-8">
            {subtitle}
          </p>
        </MotionFade>

        <MotionFade delay={0.15}>
          <div className="flex flex-wrap items-center justify-center gap-3">
            {actions}
          </div>
        </MotionFade>

        {children && (
          <MotionFade delay={0.2}>
            <div className="mt-12">{children}</div>
          </MotionFade>
        )}
      </div>
    </section>
  );
}
