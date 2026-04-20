"use client";

import { startTransition, useCallback, useEffect, useRef, useState } from "react";
import {
  BookmarkPlus,
  Coffee,
  Crown,
  Flame,
  Lock,
  Play,
  Star,
  Swords,
  Trophy,
  UserCheck,
  X,
  Zap,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface StudioStats {
  runs: number;
  reviewCount: number;
  notebookSaves: number;
  challengesDone: number;
}

interface BadgeDefinition {
  id: string;
  label: string;
  description: string;
  Icon: React.ElementType;
  condition: (stats: StudioStats, streak: number) => boolean;
}

// ---------------------------------------------------------------------------
// Badge definitions
// ---------------------------------------------------------------------------

const BADGES: BadgeDefinition[] = [
  {
    id: "first-run",
    label: "First Run",
    description: "Ran code for the first time",
    Icon: Play,
    condition: (s) => s.runs >= 1,
  },
  {
    id: "streak-3",
    label: "3-Day Streak",
    description: "Used Studio 3 days in a row",
    Icon: Flame,
    condition: (_s, streak) => streak >= 3,
  },
  {
    id: "streak-7",
    label: "Week Warrior",
    description: "7-day streak",
    Icon: Trophy,
    condition: (_s, streak) => streak >= 7,
  },
  {
    id: "first-review",
    label: "Code Reviewed",
    description: "Got your first senior review",
    Icon: UserCheck,
    condition: (s) => s.reviewCount >= 1,
  },
  {
    id: "runs-10",
    label: "10 Runs",
    description: "Ran code 10 times",
    Icon: Zap,
    condition: (s) => s.runs >= 10,
  },
  {
    id: "runs-50",
    label: "Power User",
    description: "Ran code 50 times",
    Icon: Star,
    condition: (s) => s.runs >= 50,
  },
  {
    id: "saved-notebook",
    label: "Note Taker",
    description: "Saved first Studio result to Notebook",
    Icon: BookmarkPlus,
    condition: (s) => s.notebookSaves >= 1,
  },
  {
    id: "first-warmup",
    label: "Warmed Up",
    description: "Completed a warm-up challenge",
    Icon: Coffee,
    condition: (s) => s.challengesDone >= 1,
  },
  {
    id: "challenges-5",
    label: "Challenge Accepted",
    description: "Completed 5 challenges",
    Icon: Swords,
    condition: (s) => s.challengesDone >= 5,
  },
  {
    id: "challenges-15",
    label: "Challenge Master",
    description: "Completed all 15 challenges",
    Icon: Crown,
    condition: (s) => s.challengesDone >= 15,
  },
];

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

const STATS_KEY = "studio-stats";
const EARNED_KEY = "studio-badges-earned";
const STREAK_KEY = "studio-streak";

function loadStats(): StudioStats {
  try {
    const raw = localStorage.getItem(STATS_KEY);
    if (!raw) return { runs: 0, reviewCount: 0, notebookSaves: 0, challengesDone: 0 };
    return JSON.parse(raw) as StudioStats;
  } catch {
    return { runs: 0, reviewCount: 0, notebookSaves: 0, challengesDone: 0 };
  }
}

function saveStats(stats: StudioStats): void {
  try {
    localStorage.setItem(STATS_KEY, JSON.stringify(stats));
  } catch {
    // quota exceeded — silent
  }
}

function loadEarned(): string[] {
  try {
    const raw = localStorage.getItem(EARNED_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function saveEarned(ids: string[]): void {
  try {
    localStorage.setItem(EARNED_KEY, JSON.stringify(ids));
  } catch {
    // quota exceeded — silent
  }
}

function loadStreak(): number {
  try {
    const raw = localStorage.getItem(STREAK_KEY);
    if (!raw) return 0;
    const data = JSON.parse(raw) as { count: number };
    return data.count ?? 0;
  } catch {
    return 0;
  }
}

// ---------------------------------------------------------------------------
// Badge unlock notification
// ---------------------------------------------------------------------------

interface UnlockNotification {
  badge: BadgeDefinition;
  key: number;
}

function BadgeToast({
  notification,
  onDismiss,
}: {
  notification: UnlockNotification;
  onDismiss: () => void;
}) {
  const [visible, setVisible] = useState(false);
  const { badge } = notification;
  const { Icon } = badge;

  useEffect(() => {
    const t = setTimeout(() => setVisible(true), 16);
    const dismiss = setTimeout(() => {
      setVisible(false);
      setTimeout(onDismiss, 300);
    }, 4000);
    return () => {
      clearTimeout(t);
      clearTimeout(dismiss);
    };
  }, [onDismiss]);

  function handleDismiss() {
    setVisible(false);
    setTimeout(onDismiss, 300);
  }

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className={`fixed bottom-4 left-1/2 z-50 flex max-w-sm -translate-x-1/2 items-center gap-3 rounded-lg border border-yellow-500/40 bg-yellow-500/20 px-4 py-3 shadow-lg transition-all duration-300 ${
        visible ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0"
      }`}
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-yellow-500/30 text-yellow-700">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wider text-yellow-700">
          Badge unlocked!
        </p>
        <p className="truncate font-semibold text-yellow-800">{badge.label}</p>
        <p className="text-xs text-yellow-800/70">{badge.description}</p>
      </div>
      <button
        type="button"
        onClick={handleDismiss}
        aria-label="Dismiss badge notification"
        className="shrink-0 rounded p-0.5 text-yellow-700 hover:bg-yellow-500/30"
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// BadgeSystem — notification manager
// ---------------------------------------------------------------------------

export function BadgeSystem() {
  const [notifications, setNotifications] = useState<UnlockNotification[]>([]);
  const counterRef = useRef(0);

  const checkBadges = useCallback(() => {
    const stats = loadStats();
    const streak = loadStreak();
    const earned = new Set(loadEarned());

    const newlyEarned: string[] = [];
    const newNotifications: UnlockNotification[] = [];

    for (const badge of BADGES) {
      if (!earned.has(badge.id) && badge.condition(stats, streak)) {
        newlyEarned.push(badge.id);
        newNotifications.push({ badge, key: ++counterRef.current });
      }
    }

    if (newlyEarned.length > 0) {
      saveEarned([...Array.from(earned), ...newlyEarned]);
      setNotifications((prev) => [...prev, ...newNotifications]);
    }
  }, []);

  // Check on mount
  useEffect(() => {
    startTransition(() => { checkBadges(); });
  }, [checkBadges]);

  // Listen for custom events that signal stat changes
  useEffect(() => {
    function handleRunSuccess() {
      // Increment runs in localStorage
      const stats = loadStats();
      saveStats({ ...stats, runs: stats.runs + 1 });
      checkBadges();
    }

    function handleNotebookSaved() {
      const stats = loadStats();
      saveStats({ ...stats, notebookSaves: stats.notebookSaves + 1 });
      checkBadges();
    }

    function handleReviewDone() {
      const stats = loadStats();
      saveStats({ ...stats, reviewCount: stats.reviewCount + 1 });
      checkBadges();
    }

    function handleChallengeDone() {
      const stats = loadStats();
      saveStats({ ...stats, challengesDone: stats.challengesDone + 1 });
      checkBadges();
    }

    window.addEventListener("studio:run-success", handleRunSuccess);
    window.addEventListener("studio:notebook-saved", handleNotebookSaved);
    window.addEventListener("studio:review-done", handleReviewDone);
    window.addEventListener("studio:challenge-done", handleChallengeDone);

    return () => {
      window.removeEventListener("studio:run-success", handleRunSuccess);
      window.removeEventListener("studio:notebook-saved", handleNotebookSaved);
      window.removeEventListener("studio:review-done", handleReviewDone);
      window.removeEventListener("studio:challenge-done", handleChallengeDone);
    };
  }, [checkBadges]);

  function dismissNotification(key: number) {
    setNotifications((prev) => prev.filter((n) => n.key !== key));
  }

  // Show only the first pending notification at a time
  const current = notifications[0];

  return current ? (
    <BadgeToast
      key={current.key}
      notification={current}
      onDismiss={() => dismissNotification(current.key)}
    />
  ) : null;
}

// ---------------------------------------------------------------------------
// BadgeGallery — full badge grid
// ---------------------------------------------------------------------------

export function BadgeGallery() {
  const [earned, setEarned] = useState<string[]>([]);
  const [stats, setStats] = useState<StudioStats>({ runs: 0, reviewCount: 0, notebookSaves: 0, challengesDone: 0 });
  const [streak, setStreak] = useState(0);

  useEffect(() => {
    startTransition(() => {
      setEarned(loadEarned());
      setStats(loadStats());
      setStreak(loadStreak());
    });
  }, []);

  const earnedSet = new Set(earned);

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
      {BADGES.map((badge) => {
        const { Icon } = badge;
        const isEarned = earnedSet.has(badge.id);
        const isUnlockable = !isEarned && badge.condition(stats, streak);
        return (
          <div
            key={badge.id}
            title={badge.description}
            className={`flex flex-col items-center gap-2 rounded-lg border p-3 text-center transition ${
              isEarned
                ? "border-yellow-500/40 bg-yellow-500/10"
                : isUnlockable
                  ? "border-primary/30 bg-primary/5"
                  : "border-border bg-muted/30 opacity-50"
            }`}
          >
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-full ${
                isEarned
                  ? "bg-yellow-500/20 text-yellow-700"
                  : isUnlockable
                    ? "bg-primary/15 text-primary"
                    : "bg-muted text-muted-foreground"
              }`}
            >
              {isEarned || isUnlockable ? (
                <Icon className="h-5 w-5" aria-hidden="true" />
              ) : (
                <Lock className="h-4 w-4" aria-hidden="true" />
              )}
            </div>
            <div>
              <p className="text-xs font-semibold leading-tight">{badge.label}</p>
              <p className="mt-0.5 text-[10px] leading-tight text-muted-foreground">
                {badge.description}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
