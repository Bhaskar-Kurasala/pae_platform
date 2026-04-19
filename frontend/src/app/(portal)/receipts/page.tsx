"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  CalendarCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Mail,
  Sparkles,
} from "lucide-react";
import { useMyReceipts, useCurrentWeekReceipt } from "@/lib/hooks/use-receipts";
import {
  useMarkNotificationRead,
  useMyNotifications,
} from "@/lib/hooks/use-notifications";
import { PortfolioAutopsyWidget } from "@/components/features/portfolio-autopsy-widget";
import { ReceiptsWowCard } from "@/components/features/receipts-wow-card";
import { ReceiptsSkillCoverage } from "@/components/features/receipts-skill-coverage";
import { ReceiptsTimeChart } from "@/components/features/receipts-time-chart";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { AppNotification, GrowthSnapshot } from "@/lib/api-client";

function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-xl bg-muted", className)}
      aria-hidden="true"
    />
  );
}

function formatWeekRange(weekEnding: string): string {
  const end = new Date(`${weekEnding}T00:00:00Z`);
  const start = new Date(end.getTime() - 6 * 86400000);
  const fmt = (d: Date) =>
    d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
  return `${fmt(start)} – ${fmt(end)}`;
}

function relativeLabel(weekEnding: string): string {
  const end = new Date(`${weekEnding}T00:00:00Z`);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - end.getTime()) / 86400000);
  if (diffDays < 7) return "This week";
  if (diffDays < 14) return "Last week";
  const weeks = Math.floor(diffDays / 7);
  return `${weeks} weeks ago`;
}

function Stat({
  label,
  value,
  suffix,
  sub,
  icon,
}: {
  label: string;
  value: number;
  suffix?: string;
  sub?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg bg-muted/40 p-3">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="mt-1 font-mono text-2xl font-semibold text-foreground">
        {value}
        {suffix && (
          <span className="ml-1 text-sm font-normal text-muted-foreground">
            {suffix}
          </span>
        )}
      </div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

type LetterBlock =
  | { kind: "heading"; level: 3 | 4; text: string }
  | { kind: "bullet"; text: string }
  | { kind: "rule" }
  | { kind: "space" }
  | { kind: "paragraph"; text: string }
  | { kind: "code"; language: string | null; lines: string[] };

function parseLetter(markdown: string): LetterBlock[] {
  // DISC-51 — support triple-backtick fenced code blocks. The parser walks
  // line-by-line, flips an `inFence` flag on opening/closing fences, and
  // emits a single `code` block per fence. Everything else keeps the
  // original lightweight behavior (headings, bullets, bold, hr, blank).
  const blocks: LetterBlock[] = [];
  const lines = markdown.split("\n");
  let inFence = false;
  let fenceLang: string | null = null;
  let fenceLines: string[] = [];

  const flushFence = () => {
    blocks.push({ kind: "code", language: fenceLang, lines: fenceLines });
    fenceLang = null;
    fenceLines = [];
  };

  for (const line of lines) {
    const fenceMatch = line.match(/^```(\w*)\s*$/);
    if (fenceMatch) {
      if (inFence) {
        flushFence();
        inFence = false;
      } else {
        inFence = true;
        fenceLang = fenceMatch[1] || null;
        fenceLines = [];
      }
      continue;
    }
    if (inFence) {
      fenceLines.push(line);
      continue;
    }
    if (line.startsWith("# ")) {
      blocks.push({ kind: "heading", level: 3, text: line.slice(2) });
      continue;
    }
    if (line.startsWith("## ")) {
      blocks.push({ kind: "heading", level: 4, text: line.slice(3) });
      continue;
    }
    if (line.startsWith("- ")) {
      blocks.push({ kind: "bullet", text: line.slice(2) });
      continue;
    }
    if (line.trim() === "---") {
      blocks.push({ kind: "rule" });
      continue;
    }
    if (line.trim() === "") {
      blocks.push({ kind: "space" });
      continue;
    }
    blocks.push({ kind: "paragraph", text: line });
  }
  // Tolerate an unclosed fence — flush whatever we collected rather than
  // dropping it silently.
  if (inFence) {
    flushFence();
  }
  return blocks;
}

function LetterBody({ markdown }: { markdown: string }) {
  const blocks = useMemo(() => parseLetter(markdown), [markdown]);
  return (
    <div className="space-y-2 text-sm leading-relaxed text-foreground/90">
      {blocks.map((block, i) => {
        if (block.kind === "heading") {
          const className =
            block.level === 3
              ? "mt-2 text-base font-semibold text-foreground"
              : "mt-3 text-sm font-semibold text-foreground";
          return block.level === 3 ? (
            <h3 key={i} className={className}>
              {block.text}
            </h3>
          ) : (
            <h4 key={i} className={className}>
              {block.text}
            </h4>
          );
        }
        if (block.kind === "bullet") {
          return (
            <div key={i} className="ml-4 text-foreground/85">
              • {block.text}
            </div>
          );
        }
        if (block.kind === "rule") {
          return <hr key={i} className="my-2 border-border" />;
        }
        if (block.kind === "space") {
          return <div key={i} className="h-1" />;
        }
        if (block.kind === "code") {
          return (
            <pre
              key={i}
              className="my-2 overflow-x-auto rounded-md bg-muted/60 p-3 text-xs"
            >
              <code
                className={
                  block.language
                    ? `language-${block.language} font-mono`
                    : "font-mono"
                }
              >
                {block.lines.join("\n")}
              </code>
            </pre>
          );
        }
        // paragraph with inline **bold**
        const parts = block.text.split(/(\*\*[^*]+\*\*)/g);
        return (
          <p key={i}>
            {parts.map((part, j) =>
              part.startsWith("**") && part.endsWith("**") ? (
                <strong key={j} className="font-semibold text-foreground">
                  {part.slice(2, -2)}
                </strong>
              ) : (
                <span key={j}>{part}</span>
              ),
            )}
          </p>
        );
      })}
    </div>
  );
}

function ReceiptCard({
  snap,
  letter,
  onLetterOpen,
}: {
  snap: GrowthSnapshot;
  letter: AppNotification | null;
  onLetterOpen: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(letter !== null && !letter.is_read);
  const payload = snap.payload as {
    quiz_attempts?: number;
    quiz_avg_score?: number | null;
    reflections?: number;
  };
  const showQuiz = (payload.quiz_attempts ?? 0) > 0;
  const showReflections = (payload.reflections ?? 0) > 0;

  // DISC-50 — when a letter auto-expands on mount because it's unread, we
  // also need to mark it read. The original code only called `onLetterOpen`
  // inside the toggle handler, so users who landed with the letter already
  // open had to click twice for the DB state to flip. Guard with a ref so
  // we fire exactly once per mount even if the query refetches.
  const autoReadFiredRef = useRef(false);
  useEffect(() => {
    if (autoReadFiredRef.current) return;
    if (expanded && letter && !letter.is_read) {
      autoReadFiredRef.current = true;
      onLetterOpen(letter.id);
    }
  }, [expanded, letter, onLetterOpen]);

  function handleToggleLetter() {
    const next = !expanded;
    setExpanded(next);
    if (next && letter && !letter.is_read) {
      onLetterOpen(letter.id);
    }
  }

  return (
    <Card className="border-border">
      <CardHeader className="flex flex-row items-start justify-between gap-4 pb-3">
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {relativeLabel(snap.week_ending)}
          </div>
          <div className="mt-1 text-sm text-foreground">
            {formatWeekRange(snap.week_ending)}
          </div>
        </div>
        {snap.top_concept && (
          <div
            className="flex items-center gap-1.5 rounded-full bg-purple-500/10 px-3 py-1 text-xs font-medium text-purple-700 dark:text-purple-400"
            title="Highest-confidence skill you touched this week"
          >
            <Sparkles className="h-3 w-3" aria-hidden="true" />
            {snap.top_concept}
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat
            label="Lessons"
            value={snap.lessons_completed}
            icon={<BookOpen className="h-4 w-4" aria-hidden="true" />}
          />
          <Stat
            label="Skills touched"
            value={snap.skills_touched}
            icon={<CheckCircle2 className="h-4 w-4" aria-hidden="true" />}
          />
          <Stat
            label="Active days"
            value={snap.streak_days}
            suffix={snap.streak_days === 1 ? "day" : "days"}
            icon={<CalendarCheck className="h-4 w-4" aria-hidden="true" />}
          />
          {showQuiz && (
            <Stat
              label="Quiz attempts"
              value={payload.quiz_attempts ?? 0}
              sub={
                payload.quiz_avg_score != null
                  ? `avg ${Math.round(payload.quiz_avg_score * 100)}%`
                  : undefined
              }
            />
          )}
          {!showQuiz && showReflections && (
            <Stat label="Reflections" value={payload.reflections ?? 0} />
          )}
          {!showQuiz && !showReflections && (
            <div className="hidden sm:block" aria-hidden="true" />
          )}
        </div>

        {letter && (
          <div className="rounded-lg border border-border bg-muted/20">
            <button
              type="button"
              onClick={handleToggleLetter}
              className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left hover:bg-muted/40"
              aria-expanded={expanded}
              aria-label={
                expanded ? "Hide weekly letter" : "Show weekly letter"
              }
            >
              <div className="flex items-center gap-2">
                <Mail
                  className="h-4 w-4 text-primary"
                  aria-hidden="true"
                />
                <span className="text-sm font-medium text-foreground">
                  A note from your coach
                </span>
                {!letter.is_read && (
                  <span
                    className="inline-flex h-2 w-2 rounded-full bg-primary"
                    aria-label="unread"
                  />
                )}
              </div>
              {expanded ? (
                <ChevronDown
                  className="h-4 w-4 text-muted-foreground"
                  aria-hidden="true"
                />
              ) : (
                <ChevronRight
                  className="h-4 w-4 text-muted-foreground"
                  aria-hidden="true"
                />
              )}
            </button>
            {expanded && (
              <div className="border-t border-border px-4 py-4">
                <LetterBody markdown={letter.body} />
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function EmptyState() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
        <CalendarCheck
          className="h-8 w-8 text-muted-foreground"
          aria-hidden="true"
        />
        <div className="font-medium text-foreground">No receipts yet</div>
        <p className="max-w-md text-sm text-muted-foreground">
          Receipts are generated automatically every Sunday. They capture what
          you actually did in the week — lessons completed, skills practiced,
          days active. Come back after you&apos;ve been learning for a week to
          see your first one.
        </p>
      </CardContent>
    </Card>
  );
}

export default function ReceiptsPage() {
  const { data: receipts, isLoading, isError } = useMyReceipts(12);
  const { data: weekReceipt } = useCurrentWeekReceipt();
  const { data: notifications } = useMyNotifications({ limit: 50 });
  const markRead = useMarkNotificationRead();

  // Pair each receipt with its weekly letter (by week_ending in metadata).
  const letterByWeek = useMemo(() => {
    const map = new Map<string, AppNotification>();
    for (const n of notifications ?? []) {
      if (n.notification_type !== "weekly_letter") continue;
      // Metadata isn't in the typed response; derive week_ending from body
      // title heuristic or action_url isn't reliable — fall back to scanning
      // the body's first H1 line, else the first ISO date in it.
      const match = n.body.match(/\d{4}-\d{2}-\d{2}|[A-Z][a-z]+ \d+, \d{4}/);
      if (!match) continue;
      // Normalise e.g. "April 12, 2026" → "2026-04-12"
      let key = match[0];
      if (/[A-Z][a-z]+ \d+, \d{4}/.test(key)) {
        const d = new Date(`${key} UTC`);
        if (!Number.isNaN(d.getTime())) {
          key = d.toISOString().slice(0, 10);
        }
      }
      if (!map.has(key)) map.set(key, n);
    }
    return map;
  }, [notifications]);

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <header>
        <h1 className="text-2xl font-semibold text-foreground">Receipts</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          A weekly record of what you actually did — plus a short note from
          your AI coach. Generated every Sunday.
        </p>
      </header>

      <PortfolioAutopsyWidget />

      {/* ── P3B: This-week enriched view ── */}
      {weekReceipt && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-foreground">This week</h2>

          {/* #75 Week-on-week diff */}
          <ReceiptsWowCard wow={weekReceipt.week_over_week} />

          {/* #76 Concept coverage */}
          <ReceiptsSkillCoverage skills={weekReceipt.skills_touched_detail} />

          {/* #79 Portfolio items */}
          {weekReceipt.portfolio_items.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold">Completed this week</h2>
              <ul className="space-y-1">
                {weekReceipt.portfolio_items.map((item) => (
                  <li key={item.id} className="flex items-center gap-2 text-sm">
                    <CheckCircle2
                      className="h-3.5 w-3.5 text-primary"
                      aria-hidden="true"
                    />
                    {item.exercise_title}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* #81 Reflection aggregation */}
          {weekReceipt.reflection_summary.dominant_mood !== "none" && (
            <div className="rounded-md bg-muted/50 px-4 py-3 text-sm">
              <span className="font-medium">This week&apos;s mood: </span>
              <span className="capitalize">
                {weekReceipt.reflection_summary.dominant_mood}
              </span>
              {" · "}
              <span className="text-muted-foreground">
                {Object.entries(weekReceipt.reflection_summary.mood_counts)
                  .map(([mood, count]) => `${mood}: ${count}`)
                  .join(", ")}
              </span>
            </div>
          )}

          {/* #82 Time investment chart */}
          <ReceiptsTimeChart data={weekReceipt.daily_activity} />

          {/* #83 Next-week suggestion */}
          {weekReceipt.next_week_suggestion && (
            <div className="rounded-md border border-primary/30 bg-primary/5 p-4">
              <p className="text-sm font-medium text-primary">
                Next week: focus on
              </p>
              <p className="mt-1 text-base font-semibold">
                {weekReceipt.next_week_suggestion.skill_name}
              </p>
              <p className="text-xs text-muted-foreground">
                Current mastery:{" "}
                {Math.round(
                  weekReceipt.next_week_suggestion.current_mastery * 100,
                )}
                %
              </p>
            </div>
          )}
        </section>
      )}

      {isLoading && (
        <div className="space-y-4">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      )}

      {isError && (
        <Card>
          <CardContent className="py-6 text-sm text-destructive">
            Couldn&apos;t load receipts. Try refreshing the page.
          </CardContent>
        </Card>
      )}

      {!isLoading && !isError && (receipts?.length ?? 0) === 0 && <EmptyState />}

      {!isLoading && !isError && (receipts?.length ?? 0) > 0 && (
        <div className="space-y-4">
          {receipts!.map((snap) => (
            <ReceiptCard
              key={snap.id}
              snap={snap}
              letter={letterByWeek.get(snap.week_ending) ?? null}
              onLetterOpen={(id) => markRead.mutate(id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
