"use client";

import { useMemo } from "react";
import {
  AlertTriangle,
  Briefcase,
  Gauge,
  Radar,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { SIGNALS, type Signal, type SignalKind } from "@/lib/data/signals-fixture";
import { cn } from "@/lib/utils";

const KIND_META: Record<SignalKind, { icon: LucideIcon; label: string; accent: string }> = {
  job: {
    icon: Briefcase,
    label: "Market signal",
    accent: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  },
  incident: {
    icon: AlertTriangle,
    label: "Production lesson",
    accent: "bg-rose-500/10 text-rose-400 border-rose-500/20",
  },
  shift: {
    icon: Radar,
    label: "Industry shift",
    accent: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  },
  bench: {
    icon: Gauge,
    label: "Benchmark",
    accent: "bg-violet-500/10 text-violet-400 border-violet-500/20",
  },
  tool: {
    icon: Wrench,
    label: "Tooling",
    accent: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  },
};

function dayOfYear(d: Date): number {
  const start = new Date(d.getFullYear(), 0, 0);
  const diff = d.getTime() - start.getTime();
  return Math.floor(diff / 86_400_000);
}

function pickSignal(list: Signal[], d: Date): Signal {
  if (list.length === 0) {
    return {
      kind: "shift",
      headline: "Signal feed is warming up",
      body: "Check back tomorrow — we're curating today's reality check.",
      source: "PAE",
      recordedAt: new Date().toISOString(),
    };
  }
  const idx = dayOfYear(d) % list.length;
  return list[idx];
}

export function TodaySignal() {
  const signal = useMemo(() => pickSignal(SIGNALS, new Date()), []);
  const meta = KIND_META[signal.kind];
  const Icon = meta.icon;
  const recordedLabel = new Date(signal.recordedAt).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });

  return (
    <div
      aria-labelledby="signal-heading"
      className="rounded-xl border border-foreground/[0.07] bg-foreground/[0.02] px-4 py-3"
    >
      <div className="flex items-start gap-3">
        <div className={cn("shrink-0 mt-0.5 rounded-lg p-1.5 border", meta.accent)}>
          <Icon className="h-3 w-3" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {meta.label}
            </span>
            <span className="text-[10px] text-muted-foreground/60 tabular-nums">{recordedLabel}</span>
          </div>
          <h2
            id="signal-heading"
            className="mt-0.5 text-xs font-semibold leading-snug line-clamp-1"
          >
            {signal.headline}
          </h2>
          <p className="mt-0.5 text-[11px] text-muted-foreground leading-snug line-clamp-2">
            {signal.body}
          </p>
        </div>
      </div>
    </div>
  );
}
