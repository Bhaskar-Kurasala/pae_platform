"use client";

import { startTransition, useEffect, useState } from "react";
import { Flame } from "lucide-react";

interface StreakData {
  lastDate: string;
  count: number;
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function yesterdayISO(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

function loadAndUpdateStreak(): number {
  const today = todayISO();
  const yesterday = yesterdayISO();

  try {
    const raw = localStorage.getItem("studio-streak");
    if (!raw) {
      const initial: StreakData = { lastDate: today, count: 1 };
      localStorage.setItem("studio-streak", JSON.stringify(initial));
      return 1;
    }

    const data = JSON.parse(raw) as StreakData;

    if (data.lastDate === today) {
      return data.count;
    }

    if (data.lastDate === yesterday) {
      const updated: StreakData = { lastDate: today, count: data.count + 1 };
      localStorage.setItem("studio-streak", JSON.stringify(updated));
      return updated.count;
    }

    // Streak broken — reset
    const reset: StreakData = { lastDate: today, count: 1 };
    localStorage.setItem("studio-streak", JSON.stringify(reset));
    return 1;
  } catch {
    return 1;
  }
}

export function StreakBadge() {
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    const streak = loadAndUpdateStreak();
    startTransition(() => {
      setCount(streak);
    });
  }, []);

  if (count === null) return null;

  return (
    <div
      className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2.5 py-1 text-xs font-semibold text-amber-600"
      aria-label={`${count}-day coding streak`}
      title={`${count}-day coding streak`}
    >
      <Flame className="h-3.5 w-3.5" aria-hidden="true" />
      <span>{count}</span>
    </div>
  );
}
