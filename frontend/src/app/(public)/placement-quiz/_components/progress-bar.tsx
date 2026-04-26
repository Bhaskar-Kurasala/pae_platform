"use client";

interface ProgressBarProps {
  /** Percent 0..100. Component animates fill on change. */
  pct: number;
  /** Extra Tailwind classes for outer wrapper. */
  className?: string;
  /** Pulses opacity when true (used on loading screen). */
  pulse?: boolean;
}

export function ProgressBar({ pct, className = "", pulse = false }: ProgressBarProps) {
  const safe = Math.max(0, Math.min(100, pct));
  return (
    <div
      className={`h-1 w-full overflow-hidden rounded-full bg-white/5 ${className}`}
      role="progressbar"
      aria-valuenow={Math.round(safe)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={`h-full bg-gradient-to-r from-[#244f39] via-[#4e9470] to-[#8fd6b1] transition-[width] duration-500 ease-out ${
          pulse ? "animate-pulse" : ""
        }`}
        style={{ width: `${safe}%` }}
      />
    </div>
  );
}
