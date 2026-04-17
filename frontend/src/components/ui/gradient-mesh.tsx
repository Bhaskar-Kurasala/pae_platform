import { cn } from "@/lib/utils";

interface GradientMeshProps {
  className?: string;
}

/**
 * CSS-only radial-gradient mesh for hero sections.
 * Uses OKLCH brand colors at low opacity (0.12–0.15).
 * No canvas, no particles library, no JS — pure CSS.
 *
 * Usage:
 *   <section className="relative overflow-hidden">
 *     <GradientMesh />
 *     ...content...
 *   </section>
 */
export function GradientMesh({ className }: GradientMeshProps) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute inset-0 -z-10 select-none",
        className,
      )}
      style={{
        background: [
          "radial-gradient(ellipse at 20% 50%, oklch(0.63 0.13 164 / 0.15) 0%, transparent 50%)",
          "radial-gradient(ellipse at 80% 20%, oklch(0.52 0.25 283 / 0.12) 0%, transparent 40%)",
          "radial-gradient(ellipse at 60% 80%, oklch(0.63 0.13 164 / 0.08) 0%, transparent 45%)",
        ].join(", "),
      }}
    />
  );
}
