"use client";

/**
 * Senior-engineer review UI — floating bot + slide-over panel.
 *
 * Replaces the always-on right rail with a summoned assistant pattern:
 *
 *   • Idle (no run yet)        → dim bot, hover hint "run code first"
 *   • Ready (run completed)    → lit bot with green dot
 *   • Loading (review running) → bot spins
 *   • Open                     → slide-over panel with full structured review
 *
 * The bot character is a Sparkles icon inside a circular gradient surface —
 * branded but not cartoonish. Switching to an illustration later is a
 * single swap of the `<Glyph>` inside `<ReviewBot>`.
 *
 * Editor decorations (Monaco gutter dots) live in {@link buildReviewDecorations}
 * and are applied by the parent screen so the bot/panel and the editor
 * stay loosely coupled.
 */

import { useEffect, useMemo, useState } from "react";
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Info,
  Loader2,
  Sparkles,
  X,
} from "lucide-react";

import type {
  SeniorReview,
  SeniorReviewComment,
  SeniorReviewVerdict,
} from "@/lib/api-client";
import { cn } from "@/lib/utils";

// ── public types ──────────────────────────────────────────────────────

export type BotState = "idle" | "ready" | "loading" | "open";

export interface FailureCopy {
  title: string;
  body: string;
}

/** Maps a thrown error from the practice-review mutation into student-
 * facing copy. Anthropic 429s, parse errors, network hiccups, and 5xx
 * each get a specific message instead of "Something went wrong".
 */
export function classifyReviewError(err: unknown): FailureCopy {
  const message =
    err instanceof Error ? err.message : typeof err === "string" ? err : "";
  const name = err instanceof Error ? err.name : "";
  const lower = message.toLowerCase();

  // The api-client raises an ApiTimeoutError with name="ApiTimeoutError"
  // and a generic message when the 90s wall-clock cap is hit. In
  // practice on this endpoint, every timeout is caused by upstream
  // rate-limit retries — so we map it to the same "at capacity" copy
  // rather than the misleading "request took too long" generic.
  if (
    name === "ApiTimeoutError" ||
    lower.includes("took too long") ||
    lower.includes("aborterror")
  ) {
    return {
      title: "Reviewer is at capacity",
      body:
        "The reviewer is taking longer than usual, likely because the model " +
        "provider is throttling us. Your code is saved — try again in 30–60s.",
    };
  }
  if (lower.includes("429") || lower.includes("rate limit") || lower.includes("overloaded")) {
    return {
      title: "Reviewer is at capacity",
      body: "Your code is saved. Try again in 30–60s — model providers are throttling us.",
    };
  }
  if (lower.includes("503")) {
    return {
      title: "Reviewer is temporarily busy",
      body: "Try again in a few seconds. We retry automatically on the next click.",
    };
  }
  if (lower.includes("schema validation") || lower.includes("parseable")) {
    return {
      title: "Reviewer returned a malformed response",
      body: "This is on us — try once more. If it keeps happening, ping support@aicareeros.com.",
    };
  }
  if (lower.includes("401") || lower.includes("unauthor")) {
    return {
      title: "Sign in to request a review",
      body: "Your code is safe in this tab. Sign in and click again.",
    };
  }
  if (lower.includes("network") || lower.includes("failed to fetch")) {
    return {
      title: "We couldn't reach the reviewer",
      body: "Check your connection and try again. Your code is saved locally.",
    };
  }
  return {
    title: "Review unavailable",
    body: message || "Something glitched. Try again in a moment.",
  };
}

// ── floating bot button ───────────────────────────────────────────────

export interface ReviewBotProps {
  state: BotState;
  /** Number of comments to surface as a small badge in the "ready" state. */
  findingsCount?: number;
  /** Whether the student has run their code at least once this session. */
  hasRunCode: boolean;
  /** Compact inline placement (e.g. inside the editor toolbar) vs.
   * the legacy floating-bottom-right position. Inline is the default
   * now; floating is kept for migration safety but no longer used. */
  variant?: "inline" | "floating";
  onClick: () => void;
}

export function ReviewBot({
  state,
  findingsCount = 0,
  hasRunCode,
  variant = "inline",
  onClick,
}: ReviewBotProps) {
  const disabled = state === "idle" && !hasRunCode;
  const tooltip =
    state === "idle"
      ? hasRunCode
        ? "Open senior review"
        : "Run your code first — I'll review what happens"
      : state === "loading"
        ? "Reading your code…"
        : state === "open"
          ? "Close review"
          : "Open senior review";

  const isFloating = variant === "floating";
  const size = isFloating ? "h-14 w-14" : "h-9 w-9";

  return (
    <button
      type="button"
      aria-label={tooltip}
      title={tooltip}
      onClick={onClick}
      data-testid="review-bot"
      data-state={state}
      data-variant={variant}
      className={cn(
        "group relative flex items-center justify-center rounded-full",
        "transition-all duration-300 ease-out",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--forest-3)] focus-visible:ring-offset-2",
        size,
        isFloating && "fixed bottom-6 right-6 z-40 shadow-[0_18px_60px_rgba(21,19,13,.18)]",
        !isFloating && "shadow-[0_4px_18px_rgba(21,19,13,.10)]",
        state === "idle" &&
          "bg-gradient-to-br from-[var(--panel-2)] to-[var(--panel)] opacity-50 hover:opacity-85 hover:scale-105",
        state === "ready" &&
          "bg-gradient-to-br from-[var(--forest)] to-[var(--forest-2)] opacity-100 hover:scale-110 animate-bot-ready",
        state === "loading" &&
          "bg-gradient-to-br from-[var(--forest)] to-[var(--forest-2)] opacity-95",
        state === "open" &&
          "bg-gradient-to-br from-[var(--forest-2)] to-[var(--forest-3)] opacity-100",
      )}
    >
      <Glyph state={state} compact={!isFloating} />
      {state === "ready" && findingsCount > 0 ? (
        <span
          aria-hidden="true"
          className={cn(
            "absolute grid place-items-center rounded-full font-bold text-white shadow-sm",
            isFloating
              ? "-top-1 -right-1 h-5 w-5 text-[10px]"
              : "-top-1 -right-1 h-4 w-4 text-[9px]",
            "bg-[var(--rose)]",
          )}
          data-testid="review-bot-badge"
        >
          {Math.min(findingsCount, 9)}
        </span>
      ) : state === "ready" ? (
        <span
          aria-hidden="true"
          className={cn(
            "absolute rounded-full bg-[var(--forest-3)] ring-2 ring-[var(--bg)] animate-pulse",
            isFloating ? "-top-0.5 -right-0.5 h-3 w-3" : "-top-0.5 -right-0.5 h-2.5 w-2.5",
          )}
        />
      ) : null}

      {/* Idle nudge — pulse halo (floating variant only; inline gets a
          subtler hover-only treatment) */}
      {isFloating && state === "idle" && !disabled ? (
        <span
          aria-hidden="true"
          className="absolute inset-0 rounded-full ring-1 ring-[var(--line)] animate-pulse-slow"
        />
      ) : null}
    </button>
  );
}

function Glyph({ state, compact }: { state: BotState; compact: boolean }) {
  const cls = compact ? "h-4 w-4" : "h-6 w-6";
  if (state === "loading") {
    return <Loader2 className={cn(cls, "animate-spin text-white")} aria-hidden="true" />;
  }
  if (state === "open") {
    return <X className={cn(cls, "text-white")} aria-hidden="true" />;
  }
  return (
    <Sparkles
      className={cn(cls, state === "ready" ? "text-white" : "text-[var(--ink-2)]")}
      aria-hidden="true"
    />
  );
}

// ── slide-over panel ──────────────────────────────────────────────────

export interface SeniorReviewPanelProps {
  open: boolean;
  loading: boolean;
  error: FailureCopy | null;
  review: SeniorReview | null;
  /** Per-pattern occurrence counts pulled from prior submissions for this
   * problem. Powers the "you've shown this pattern before" header. */
  recurringPatterns?: Array<{ slug: string; count: number }>;
  onClose: () => void;
  /** Called when a student clicks a line chip — parent scrolls Monaco. */
  onJumpToLine?: (line: number) => void;
  /** Called when a student clicks "Try again" on the error state. */
  onRetry?: () => void;
}

export function SeniorReviewPanel({
  open,
  loading,
  error,
  review,
  recurringPatterns = [],
  onClose,
  onJumpToLine,
  onRetry,
}: SeniorReviewPanelProps) {
  // ESC to close. Lightweight — a full <dialog> focus trap would reset
  // the editor focus chain on every open.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  // Hard-unmount when closed. We used to keep the panel in the DOM and
  // slide it with `translate-x-full`, but with `position: fixed` Chrome
  // and Safari still budget the element into the layout in a way that
  // makes the page horizontally scrollable. Unmounting kills the issue
  // entirely; the 300ms transition is good enough as an open animation.
  if (!open) return null;

  return (
    <>
      {/* Scrim */}
      <div
        aria-hidden="true"
        onClick={onClose}
        className="fixed inset-0 z-30 bg-[rgba(16,18,14,0.32)] backdrop-blur-[2px] animate-fade-in"
      />
      {/* Panel */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Senior code review"
        data-testid="senior-review-panel"
        className={cn(
          "fixed top-0 right-0 z-40 h-screen w-full max-w-[440px]",
          "bg-[var(--panel)] border-l border-[var(--line)]",
          "shadow-[0_28px_90px_rgba(21,19,13,.18)]",
          "flex flex-col animate-slide-in-right",
        )}
      >
        <PanelHeader onClose={onClose} />
        <div className="flex-1 overflow-y-auto overflow-x-hidden px-5 py-4">
          {loading ? (
            <PanelLoading />
          ) : error ? (
            <PanelError error={error} onRetry={onRetry} />
          ) : review ? (
            <PanelReview
              review={review}
              recurringPatterns={recurringPatterns}
              onJumpToLine={onJumpToLine}
            />
          ) : (
            <PanelEmpty />
          )}
        </div>
      </aside>
    </>
  );
}

function PanelHeader({ onClose }: { onClose: () => void }) {
  return (
    <header className="flex items-center justify-between border-b border-[var(--line)] px-5 py-4">
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className="grid h-7 w-7 place-items-center rounded-full bg-[var(--forest-soft)]"
        >
          <Sparkles className="h-3.5 w-3.5 text-[var(--forest)]" />
        </span>
        <div>
          <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-[var(--forest)]">
            Senior review
          </div>
          <div className="text-[11px] text-[var(--muted)]">
            Reasoning, not execution
          </div>
        </div>
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label="Close review"
        className="rounded-full p-1.5 text-[var(--muted)] hover:bg-[var(--panel-2)] hover:text-[var(--ink)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--forest-3)]"
      >
        <X className="h-4 w-4" />
      </button>
    </header>
  );
}

function PanelLoading() {
  // Three calibrated phase labels — feels more thoughtful than a spinner
  // alone. The labels rotate every ~3s. Not a streaming response — just
  // intentional pacing.
  const phases = [
    "Reading your code…",
    "Checking patterns from prior submissions…",
    "Drafting review…",
  ];
  const [idx, setIdx] = useTimedRotation(phases.length, 2800);
  useEffect(() => () => setIdx(0), [setIdx]);

  return (
    <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
      <Loader2 className="h-7 w-7 animate-spin text-[var(--forest)]" />
      <p className="text-sm text-[var(--muted)]" data-testid="review-loading-phase">
        {phases[idx]}
      </p>
    </div>
  );
}

function PanelError({
  error,
  onRetry,
}: {
  error: FailureCopy;
  onRetry?: () => void;
}) {
  return (
    <div className="mt-4 rounded-2xl border border-[var(--rose)]/30 bg-[var(--rose)]/5 p-4">
      <div className="flex items-start gap-3">
        <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0 text-[var(--rose)]" />
        <div className="min-w-0 space-y-1">
          <div className="text-sm font-semibold text-[var(--ink)] break-words">
            {error.title}
          </div>
          <p className="text-[13px] leading-relaxed text-[var(--muted)] [overflow-wrap:anywhere]">
            {error.body}
          </p>
        </div>
      </div>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-[var(--ink)] px-3 py-1.5 text-[12px] font-medium text-white hover:bg-[var(--ink-2)]"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}

function PanelEmpty() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
      <Sparkles className="h-8 w-8 text-[var(--muted-2)] opacity-50" />
      <p className="text-sm text-[var(--muted)]">
        No review yet. Run your code, then click the bot.
      </p>
    </div>
  );
}

// ── review body ───────────────────────────────────────────────────────

function PanelReview({
  review,
  recurringPatterns,
  onJumpToLine,
}: {
  review: SeniorReview;
  recurringPatterns: Array<{ slug: string; count: number }>;
  onJumpToLine?: (line: number) => void;
}) {
  const grouped = useMemo(() => groupCommentsBySeverity(review.comments), [
    review.comments,
  ]);
  return (
    <div className="space-y-5 pb-6">
      <VerdictPill verdict={review.verdict} />
      <h2 className="font-[family-name:var(--serif)] text-[19px] leading-[1.35] tracking-[-0.01em] text-[var(--ink)] [overflow-wrap:anywhere]">
        {review.headline}
      </h2>

      {recurringPatterns.length > 0 ? (
        <PatternStrip patterns={recurringPatterns} />
      ) : null}

      {review.strengths.length > 0 ? (
        <Section title="What's working" icon={<CheckCircle2 className="h-3.5 w-3.5 text-[var(--forest)]" />}>
          <ul className="space-y-1.5">
            {review.strengths.map((s, i) => (
              <li key={i} className="flex gap-2 text-[13.5px] leading-relaxed text-[var(--ink-2)]">
                <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-[var(--forest)]" />
                <span className="[overflow-wrap:anywhere]">{s}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {(["blocking", "concern", "suggestion", "nit"] as const).map((sev) =>
        grouped[sev].length > 0 ? (
          <SeverityGroup
            key={sev}
            severity={sev}
            comments={grouped[sev]}
            onJumpToLine={onJumpToLine}
          />
        ) : null,
      )}

      {review.next_step ? (
        <Section
          title="Next step"
          icon={<AlertTriangle className="h-3.5 w-3.5 text-[var(--gold)]" />}
        >
          <p className="rounded-xl bg-[var(--gold-soft)] px-3 py-2.5 text-[13.5px] leading-relaxed text-[var(--ink-2)] [overflow-wrap:anywhere]">
            {review.next_step}
          </p>
        </Section>
      ) : null}
    </div>
  );
}

function VerdictPill({ verdict }: { verdict: SeniorReviewVerdict }) {
  const map: Record<SeniorReviewVerdict, { label: string; cls: string }> = {
    approve: {
      label: "Approved",
      cls: "bg-[var(--forest-soft)] text-[var(--forest)]",
    },
    request_changes: {
      label: "Changes requested",
      cls: "bg-[var(--rose)]/10 text-[var(--rose)]",
    },
    comment: {
      label: "Comments",
      cls: "bg-[var(--panel-2)] text-[var(--muted)]",
    },
  };
  const v = map[verdict] ?? map.comment;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[10px] font-bold uppercase tracking-[0.14em]",
        v.cls,
      )}
    >
      {v.label}
    </span>
  );
}

function PatternStrip({
  patterns,
}: {
  patterns: Array<{ slug: string; count: number }>;
}) {
  return (
    <div className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2.5">
      <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--muted)]">
        Patterns across your submissions
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {patterns.map((p) => (
          <span
            key={p.slug}
            className="inline-flex items-center gap-1 rounded-full bg-[var(--panel)] px-2 py-0.5 text-[11px] font-medium text-[var(--ink-2)] border border-[var(--line)]"
          >
            <code className="font-[family-name:var(--mono)] text-[10.5px]">
              {p.slug}
            </code>
            <span className="text-[var(--muted)]">×{p.count}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--muted)]">
        {icon}
        {title}
      </div>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function SeverityGroup({
  severity,
  comments,
  onJumpToLine,
}: {
  severity: SeverityKey;
  comments: SeniorReviewComment[];
  onJumpToLine?: (line: number) => void;
}) {
  const meta = SEVERITY_META[severity];
  return (
    <Section
      title={`${meta.label} (${comments.length})`}
      icon={<meta.Icon className={cn("h-3.5 w-3.5", meta.iconClass)} />}
    >
      <ul className="space-y-2">
        {comments.map((c, i) => (
          <li
            key={i}
            className={cn(
              "rounded-xl border bg-[var(--panel)] px-3 py-2.5",
              meta.borderClass,
            )}
          >
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em]",
                  meta.chipClass,
                )}
              >
                {meta.label}
              </span>
              {c.line ? (
                <button
                  type="button"
                  onClick={() => onJumpToLine?.(c.line)}
                  className="inline-flex items-center gap-1 rounded-md bg-[var(--panel-2)] px-1.5 py-0.5 font-[family-name:var(--mono)] text-[10.5px] text-[var(--ink-2)] hover:bg-[var(--panel-3)]"
                  title={`Jump to line ${c.line}`}
                  data-testid="comment-line-chip"
                >
                  line {c.line}
                </button>
              ) : (
                <span className="text-[10px] uppercase tracking-wider text-[var(--muted)]">
                  whole file
                </span>
              )}
            </div>
            <p className="mt-2 text-[13.5px] leading-relaxed text-[var(--ink)] [overflow-wrap:anywhere]">
              {c.message}
            </p>
            {c.suggested_change ? (
              <pre className="mt-2 overflow-x-auto rounded-lg bg-[var(--ink)] p-2.5 text-[12px] leading-relaxed text-[var(--panel-2)] font-[family-name:var(--mono)]">
                {c.suggested_change}
              </pre>
            ) : null}
          </li>
        ))}
      </ul>
    </Section>
  );
}

// ── severity metadata ─────────────────────────────────────────────────

type SeverityKey = "blocking" | "concern" | "suggestion" | "nit";

const SEVERITY_META: Record<
  SeverityKey,
  {
    label: string;
    Icon: typeof AlertOctagon;
    iconClass: string;
    chipClass: string;
    borderClass: string;
  }
> = {
  blocking: {
    label: "Blocking",
    Icon: AlertOctagon,
    iconClass: "text-[var(--rose)]",
    chipClass: "bg-[var(--rose)]/15 text-[var(--rose)]",
    borderClass: "border-[var(--rose)]/30",
  },
  concern: {
    label: "Concern",
    Icon: AlertTriangle,
    iconClass: "text-[var(--gold)]",
    chipClass: "bg-[var(--gold-soft)] text-[var(--gold)]",
    borderClass: "border-[var(--gold)]/30",
  },
  suggestion: {
    label: "Suggestion",
    Icon: Info,
    iconClass: "text-[var(--forest)]",
    chipClass: "bg-[var(--forest-soft)] text-[var(--forest)]",
    borderClass: "border-[var(--line)]",
  },
  nit: {
    label: "Nit",
    Icon: Info,
    iconClass: "text-[var(--muted)]",
    chipClass: "bg-[var(--panel-2)] text-[var(--muted)]",
    borderClass: "border-[var(--line)]",
  },
};

function groupCommentsBySeverity(
  comments: SeniorReviewComment[],
): Record<SeverityKey, SeniorReviewComment[]> {
  const empty: Record<SeverityKey, SeniorReviewComment[]> = {
    blocking: [],
    concern: [],
    suggestion: [],
    nit: [],
  };
  for (const c of comments) {
    const key = (c.severity in empty ? c.severity : "suggestion") as SeverityKey;
    empty[key].push(c);
  }
  return empty;
}

// ── Monaco decoration helper (decoupled — no monaco import here) ──────

export interface ReviewDecorationInput {
  line: number;
  severity: SeniorReviewComment["severity"];
  message: string;
}

/** Build the decoration descriptor list the parent screen feeds into
 * Monaco's `editor.deltaDecorations(...)`. We don't import monaco from
 * this file because it lives in a dynamic-imported shell — keeping this
 * helper pure means it tree-shakes cleanly on the server. */
export function buildReviewDecorations(
  comments: SeniorReviewComment[],
): ReviewDecorationInput[] {
  return comments
    .filter((c) => c.line && c.line >= 1)
    .map((c) => ({
      line: c.line,
      severity: c.severity,
      message: c.message,
    }));
}

/** Map a severity to the Monaco gutter class name. Wired into globals.css
 * (see .review-gutter-* classes). */
export function severityGutterClass(
  severity: SeniorReviewComment["severity"],
): string {
  switch (severity) {
    case "blocking":
      return "review-gutter-blocking";
    case "concern":
      return "review-gutter-concern";
    case "suggestion":
      return "review-gutter-suggestion";
    default:
      return "review-gutter-nit";
  }
}

// ── small util — rotating index for loading phase labels ──────────────

function useTimedRotation(
  count: number,
  intervalMs: number,
): [number, (n: number) => void] {
  const [idx, setIdx] = useState(0);
  useEffect(() => {
    if (count <= 1) return;
    const id = window.setInterval(() => {
      setIdx((prev) => (prev + 1) % count);
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [count, intervalMs]);
  return [idx, setIdx];
}
