"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { v8Toast } from "@/components/v8/v8-toast";
import { trackTodaySummaryLoaded } from "@/lib/analytics-events";
import { useDueCards, useReviewCard } from "@/lib/hooks/use-srs";
import {
  useMarkSessionStep,
  useMyIntention,
  useSetIntention,
  useTodaySummary,
} from "@/lib/hooks/use-today";
import { useAuthStore } from "@/stores/auth-store";

type StepState = "active" | "locked" | "done";

interface DisplayCard {
  id: string;
  prompt: string;
  answer: string;
  hint: string;
}

const FALLBACK_CARDS: ReadonlyArray<DisplayCard> = [
  {
    id: "fallback-1",
    prompt:
      "What does asyncio.gather() do that sequential await calls cannot?",
    answer:
      "Runs coroutines concurrently. Sequential await calls block each other. gather() starts independent tasks together and waits for all of them.",
    hint: "Click reveal when you are ready. The response should explain concurrency and when it is safe to use it.",
  },
  {
    id: "fallback-2",
    prompt: "When should you prefer a context manager over try/finally?",
    answer:
      "When the cleanup is bound to the lifetime of a resource — the with block makes the contract explicit and survives early returns.",
    hint: "Think about resource lifetimes and readability of cleanup paths.",
  },
  {
    id: "fallback-3",
    prompt: "Why does retrying with exponential backoff beat fixed-interval retries?",
    answer:
      "Backoff spreads load away from rate-limit windows and gives transient failures real time to recover before the next attempt.",
    hint: "The answer is about rate limits and recovery windows, not about CPU.",
  },
];

const QUALITY: Record<"easy" | "hard" | "forgot", number> = {
  easy: 5,
  hard: 3,
  forgot: 1,
};

const DEFAULT_HINT = "Say the idea out loud first, then click reveal.";
const DEFAULT_ANSWER =
  "Restate the core idea in your own words and name one place you'd reach for it.";

function stripLeadingHandle(handle: string, label: string): string {
  // The cohort_events recorder may include the actor name at the start of
  // the label (so non-UI consumers get a self-contained sentence). The UI
  // already prepends <b>{handle}</b>, so trim a leading match to avoid
  // "Priya K. Priya K. promoted to …".
  const trimmed = label.trimStart();
  if (handle && trimmed.startsWith(handle)) {
    return trimmed.slice(handle.length).trimStart();
  }
  return trimmed;
}

function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  const diffSec = Math.max(1, Math.floor((Date.now() - t) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

export function TodayScreen() {
  const { user, isAuthenticated } = useAuthStore();
  const summaryQ = useTodaySummary();
  const summary = summaryQ.data;
  const { data: dueCards } = useDueCards(7);
  const reviewCard = useReviewCard();
  const intentionQ = useMyIntention();
  const setIntention = useSetIntention();
  const markStep = useMarkSessionStep();

  // PR3/C3.2 — fire `today.summary_loaded` once per visit when the
  // payload first arrives. We key on `summary?.session.id` so a
  // background refetch (same session) doesn't double-fire, but a
  // session rollover (new day) does. No-op when telemetry is off.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: re-fire only on session rollover, not on every step toggle.
  useEffect(() => {
    if (!summary) return;
    trackTodaySummaryLoaded({
      warmup_done: !!summary.session.warmup_done_at,
      lesson_done: !!summary.session.lesson_done_at,
      reflect_done: !!summary.session.reflect_done_at,
    });
  }, [summary?.session.id]);

  const dueCount = summary?.due_card_count ?? dueCards?.length ?? 0;
  const daysActive = summary?.consistency.days_active ?? 0;
  const windowDays = summary?.consistency.window_days ?? 7;
  const overallProgress = Math.round(summary?.progress.overall_percentage ?? 0);
  const deadlineDays = summary?.goal.days_remaining ?? 0;
  const sessionOrdinal = summary?.session.ordinal ?? 1;
  const targetRole =
    summary?.next_milestone.label || summary?.goal.target_role || "your next role";
  const lessonsCompleted = summary?.progress.lessons_completed_total ?? 0;
  const lessonsTotal = summary?.progress.lessons_total ?? 0;
  const lessonsLeft = Math.max(0, lessonsTotal - lessonsCompleted);
  const todayUnlock = Math.round(summary?.progress.today_unlock_percentage ?? 0);
  const focusName = summary?.current_focus.skill_name ?? "Today's focus";
  const focusBlurb =
    summary?.current_focus.skill_blurb ??
    "Pick today's lesson and the focus chip will update.";
  const capstone = summary?.capstone;
  const draftQuality = capstone?.draft_quality ?? null;
  const draftsCount = capstone?.drafts_count ?? 0;
  const capstoneTitle = capstone?.title ?? "Your capstone draft";
  const capstoneDays = capstone?.days_to_due ?? null;
  const readinessDelta = summary?.readiness.delta_week ?? 0;
  const readinessCurrent = summary?.readiness.current ?? 0;
  const peersAtLevel = summary?.peers_at_level ?? 0;
  const promotionsToday = summary?.promotions_today ?? 0;
  const microWins = summary?.micro_wins ?? [];
  const cohortEvents = summary?.cohort_events ?? [];
  const intentionText = summary?.intention.text ?? intentionQ.data?.text ?? "";

  const { weekday, monthDay } = useMemo(() => {
    const now = new Date();
    return {
      weekday: now.toLocaleDateString("en-US", { weekday: "long" }),
      monthDay: now.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    };
  }, []);

  useSetV8Topbar({
    eyebrow: `${weekday} · ${monthDay} · Session ${sessionOrdinal}`,
    titleHtml: "A modern learning flow that feels <i>alive</i>.",
    chips: [
      { label: `Active ${daysActive} of ${windowDays} days`, variant: "forest" },
      { label: `${dueCount} review cards`, variant: "gold" },
      { label: "One clear next action", variant: "ink" },
    ],
    progress: overallProgress,
  });

  const cards: ReadonlyArray<DisplayCard> = useMemo(() => {
    if (!isAuthenticated || !dueCards || dueCards.length === 0) {
      return FALLBACK_CARDS;
    }
    return dueCards.slice(0, 7).map((c) => ({
      id: c.id,
      prompt: c.prompt,
      answer: c.answer || DEFAULT_ANSWER,
      hint: c.hint || DEFAULT_HINT,
    }));
  }, [dueCards, isAuthenticated]);

  const totalCards = Math.max(cards.length, 1);
  const [cardIndex, setCardIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);

  // Local mirror of session step state — we hydrate from the summary so a
  // refresh after a partial session keeps us in the right column.
  const initialSteps = useMemo<{
    warm: StepState;
    lesson: StepState;
    reflect: StepState;
  }>(() => {
    const s = summary?.session;
    if (!s) return { warm: "active", lesson: "locked", reflect: "locked" };
    if (s.reflect_done_at) return { warm: "done", lesson: "done", reflect: "done" };
    if (s.lesson_done_at) return { warm: "done", lesson: "done", reflect: "active" };
    if (s.warmup_done_at) return { warm: "done", lesson: "active", reflect: "locked" };
    return { warm: "active", lesson: "locked", reflect: "locked" };
  }, [summary]);
  const [steps, setSteps] =
    useState<{ warm: StepState; lesson: StepState; reflect: StepState }>(initialSteps);
  useEffect(() => {
    setSteps(initialSteps);
  }, [initialSteps]);

  const activeCard = cards[Math.min(cardIndex, cards.length - 1)] ?? FALLBACK_CARDS[0];
  const cardsDone = Math.min(cardIndex, totalCards);

  const handleReveal = useCallback(() => setRevealed(true), []);

  const handleGrade = useCallback(
    (grade: "easy" | "hard" | "forgot") => {
      const card = cards[cardIndex];
      if (card && !card.id.startsWith("fallback-")) {
        reviewCard.mutate({ cardId: card.id, quality: QUALITY[grade] });
      }
      v8Toast(`Marked ${grade.charAt(0).toUpperCase()}${grade.slice(1)}`);
      setRevealed(false);
      setCardIndex((idx) => {
        const next = Math.min(idx + 1, totalCards);
        // Mark warm-up complete when we just reviewed the last card.
        if (next === totalCards && steps.warm !== "done") {
          markStep.mutate("warmup");
          v8Toast("Warm-up complete. Lesson unlocked.");
        }
        return next;
      });
    },
    [cards, cardIndex, reviewCard, totalCards, steps.warm, markStep],
  );

  const handleAdvanceStep = useCallback(() => {
    if (steps.warm !== "done") {
      markStep.mutate("warmup");
      v8Toast("Warm-up complete. Lesson unlocked.");
      setSteps({ warm: "done", lesson: "active", reflect: "locked" });
      return;
    }
    if (steps.lesson !== "done") {
      markStep.mutate("lesson");
      v8Toast("Lesson complete. Reflection unlocked.");
      setSteps({ warm: "done", lesson: "done", reflect: "active" });
      return;
    }
    if (steps.reflect !== "done") {
      markStep.mutate("reflect");
      v8Toast("Session closed. See you tomorrow.");
      setSteps({ warm: "done", lesson: "done", reflect: "done" });
    }
  }, [steps, markStep]);

  const handleSeeLessonPlan = useCallback(() => {
    document.getElementById("lessonPlan")?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const [intentionDraft, setIntentionDraft] = useState(intentionText);
  useEffect(() => setIntentionDraft(intentionText), [intentionText]);
  const handleSaveIntention = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = intentionDraft.trim();
      if (!trimmed) return;
      setIntention.mutate(trimmed, {
        onSuccess: () => v8Toast("Today's intention saved"),
      });
    },
    [intentionDraft, setIntention],
  );

  const firstName =
    summary?.user.first_name || user?.full_name?.split(" ")[0] || "you";

  return (
    <section className="screen active" id="screen-today">
      <div className="pad">
        <div className="grid today-grid">
          <div className="grid">
            <section className="card hero reveal">
              <div>
                <div className="eyebrow">Today, motion with purpose</div>
                <h3>
                  Warm up. Build. <i>Leave stronger</i> than you arrived.
                </h3>
                <p className="narrative-line" id="narrativeLine">
                  You&apos;re {lessonsCompleted} lessons closer to {targetRole} than when you started.
                </p>
                <p>
                  This version adds modern motion where it helps students: entering focus,
                  understanding what changed, feeling unlock moments, and moving toward a role
                  with calm confidence.
                </p>

                <form
                  onSubmit={handleSaveIntention}
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    margin: "16px 0 4px",
                    flexWrap: "wrap",
                  }}
                  aria-label="Today's intention"
                >
                  <label
                    htmlFor="todayIntention"
                    className="eyebrow"
                    style={{ fontSize: 11 }}
                  >
                    Today I want to
                  </label>
                  <input
                    id="todayIntention"
                    type="text"
                    value={intentionDraft}
                    onChange={(e) => setIntentionDraft(e.target.value)}
                    placeholder="ship one async client and grade it"
                    aria-label="What do you want to do today"
                    style={{
                      flex: "1 1 280px",
                      padding: "8px 10px",
                      border: "1px solid #e2e8f0",
                      borderRadius: 6,
                      fontSize: 13,
                    }}
                  />
                  <button className="btn ghost" type="submit" disabled={!intentionDraft.trim()}>
                    Save
                  </button>
                </form>

                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    alignItems: "center",
                    flexWrap: "wrap",
                    margin: "18px 0 4px",
                  }}
                >
                  {peersAtLevel > 0 && (
                    <span className="peer-chip">
                      <span className="peer-dot" />
                      <span>{peersAtLevel} peers at your level today</span>
                    </span>
                  )}
                  {promotionsToday > 0 && (
                    <span
                      className="peer-chip"
                      style={{
                        background:
                          "linear-gradient(95deg, rgba(184,134,45,0.10), rgba(184,134,45,0.04))",
                        borderColor: "rgba(184,134,45,0.25)",
                        color: "#8d621b",
                      }}
                    >
                      <span className="peer-dot" style={{ background: "#b8862d" }} />
                      <span>
                        {promotionsToday} just promoted to {targetRole}
                      </span>
                    </span>
                  )}
                </div>

                <div className="hero-actions">
                  <Link href="/studio" className="btn primary">
                    Continue lesson
                  </Link>
                  <button className="btn secondary" onClick={handleSeeLessonPlan} type="button">
                    See lesson plan
                  </button>
                </div>

                {readinessDelta !== 0 && (
                  <div className="moment-ribbon">
                    <span className="moment-dot" />
                    <span>
                      {firstName}&apos;s job readiness {readinessDelta > 0 ? "rose" : "moved"}{" "}
                      <b>
                        {readinessDelta > 0 ? "+" : ""}
                        {readinessDelta}
                      </b>{" "}
                      this week. Currently at {readinessCurrent}% on the north-star metric.
                    </span>
                  </div>
                )}
              </div>
              <div className="hero-aside">
                <div className="kpi reveal delay-1">
                  <div className="label">Next milestone</div>
                  <div className="value">
                    <span className="count" data-to={deadlineDays}>
                      {deadlineDays}
                    </span>{" "}
                    days
                  </div>
                  <div className="sub">to {targetRole} at this pace.</div>
                </div>
                <div className="kpi reveal delay-2">
                  <div className="label">Today unlocks</div>
                  <div className="value">+{todayUnlock}%</div>
                  <div className="sub">
                    progress in {summary?.progress.active_course_title ?? "your active course"}.
                  </div>
                </div>
                <div className="kpi reveal delay-3">
                  <div className="label">Current focus</div>
                  <div className="value">{focusName}</div>
                  <div className="sub">{focusBlurb}</div>
                </div>
                <div className="kpi reveal delay-4">
                  <div className="label">Proof created</div>
                  <div className="value">
                    {draftsCount} {draftsCount === 1 ? "draft" : "drafts"}
                  </div>
                  <div className="sub">
                    {capstoneTitle} becomes evidence for promotion, not just practice.
                  </div>
                </div>
              </div>
            </section>

            <section className="card pad reveal">
              <div className="section-title">
                <div>
                  <h4>Your session flow</h4>
                  <p>Each step should feel obvious, connected, and gently animated when it unlocks.</p>
                </div>
                <div className="small">Progress only moves when work is actually complete.</div>
              </div>
              <div className="step-row">
                <article className={`step-card ${steps.warm}`} id="stepWarm">
                  <div className="step-top">
                    <div className="step-num">1</div>
                    <div className="step-state">
                      {steps.warm === "active"
                        ? "Active now"
                        : steps.warm === "done"
                          ? "Complete"
                          : "Locked"}
                    </div>
                  </div>
                  <h5>Review what you nearly lost</h5>
                  <p>
                    {totalCards} spaced-repetition cards from prior lessons. Fast enough to begin.
                    Strong enough to re-open memory.
                  </p>
                  <div className="step-meta">
                    <span className="mini-chip">{totalCards} cards</span>
                    <span className="mini-chip">2 min</span>
                    <span className="mini-chip">Confidence first</span>
                  </div>
                </article>

                <article className={`step-card ${steps.lesson}`} id="stepLesson">
                  <div className="step-top">
                    <div className="step-num">2</div>
                    <div className="step-state">
                      {steps.lesson === "active"
                        ? "Active now"
                        : steps.lesson === "done"
                          ? "Complete"
                          : "Unlocks next"}
                    </div>
                  </div>
                  <h5>Build today&apos;s lesson</h5>
                  <p>
                    {summary?.progress.next_lesson_title
                      ? `Next up: ${summary.progress.next_lesson_title}.`
                      : "One practical outcome that compounds into your capstone."}
                  </p>
                  <div className="step-meta">
                    <span className="mini-chip">45 min</span>
                    <span className="mini-chip">Studio guided</span>
                    <span className="mini-chip">Core for capstone</span>
                  </div>
                </article>

                <article className={`step-card ${steps.reflect}`} id="stepReflect">
                  <div className="step-top">
                    <div className="step-num">3</div>
                    <div className="step-state">
                      {steps.reflect === "active"
                        ? "Active now"
                        : steps.reflect === "done"
                          ? "Complete"
                          : "Closes the loop"}
                    </div>
                  </div>
                  <h5>Capture what clicked</h5>
                  <p>
                    One sentence becomes tomorrow&apos;s first review card. Reflection is part of
                    learning, not a separate chore.
                  </p>
                  <div className="step-meta">
                    <span className="mini-chip">60 sec</span>
                    <span className="mini-chip">Feeds notebook</span>
                    <span className="mini-chip">Improves recall</span>
                  </div>
                </article>
              </div>
            </section>

            <div className="layout-2">
              <section className="card pad reveal">
                <div className="section-title">
                  <div>
                    <h4>Warm-up, refined</h4>
                    <p>Reveal should feel tactile and premium, not distracting.</p>
                  </div>
                  <div
                    className="card-progress"
                    id="cardCounter"
                    aria-label={`Card ${Math.min(cardsDone + 1, totalCards)} of ${totalCards}`}
                  >
                    <span className="cp-label">
                      {String(Math.min(cardsDone + 1, totalCards)).padStart(2, "0")}{" "}
                      <span>/ {String(totalCards).padStart(2, "0")}</span>
                    </span>
                    <span className="cp-track">
                      {Array.from({ length: totalCards }).map((_, i) => (
                        <span
                          key={i}
                          className={`cp-seg${i < cardsDone ? " done" : ""}`}
                        />
                      ))}
                    </span>
                  </div>
                </div>
                <div
                  className={`prompt-shell${revealed ? " revealed" : ""}`}
                  id="cardShell"
                >
                  <div className="card-face card-face-front">
                    {/* P-Today3 — wrap long legacy prompts cleanly. New
                        cards are <=140 chars so this is mostly defensive. */}
                    <h5
                      style={{
                        wordBreak: "break-word",
                        overflowWrap: "anywhere",
                        whiteSpace: "pre-wrap",
                      }}
                    >
                      {activeCard.prompt}
                    </h5>
                    <p id="cardHintText">{activeCard.hint}</p>
                  </div>
                  <div className="card-face card-face-back">
                    <div className="card-back-recap">
                      <span className="recap-label">Question</span>
                      <span
                        className="recap-text"
                        style={{
                          wordBreak: "break-word",
                          overflowWrap: "anywhere",
                        }}
                      >
                        {activeCard.prompt}
                      </span>
                    </div>
                    <div className="card-face-eyebrow">Answer</div>
                    <p
                      id="cardAnswerText"
                      style={{
                        wordBreak: "break-word",
                        overflowWrap: "anywhere",
                        whiteSpace: "pre-wrap",
                      }}
                    >
                      {activeCard.answer}
                    </p>
                  </div>
                </div>
                <div className="review-actions">
                  <button
                    className="btn ghost"
                    id="revealBtn"
                    onClick={handleReveal}
                    type="button"
                    disabled={revealed}
                  >
                    Reveal answer
                  </button>
                  <button
                    className="btn primary"
                    onClick={() => handleGrade("easy")}
                    type="button"
                  >
                    Easy
                  </button>
                  <button
                    className="btn ghost"
                    onClick={() => handleGrade("hard")}
                    type="button"
                  >
                    Hard
                  </button>
                  <button
                    className="btn ghost"
                    onClick={() => handleGrade("forgot")}
                    type="button"
                  >
                    Forgot
                  </button>
                </div>
              </section>

              <section className="capstone-trailer reveal">
                <div className="trailer-eyebrow">
                  ★ Your capstone — the proof of {targetRole}
                </div>
                <div className="trailer-title">
                  {capstoneTitle}
                  {capstoneDays !== null ? ` · ${capstoneDays} days from now` : ""}
                </div>
                <div className="trailer-frames">
                  <div className="trailer-frame">
                    <div className="step-num">01</div>
                    <div className="step-name">Brief</div>
                    <div className="step-desc">
                      Real-world spec drops in Studio. Open requirements, ask the mentor.
                    </div>
                  </div>
                  <div className="trailer-frame">
                    <div className="step-num">02</div>
                    <div className="step-name">Build</div>
                    <div className="step-desc">
                      Ship working code with tests + retry logic. Senior review at every commit.
                    </div>
                  </div>
                  <div className="trailer-frame">
                    <div className="step-num">03</div>
                    <div className="step-name">Defend</div>
                    <div className="step-desc">
                      15-min walkthrough with your reviewer. Then the promotion gate opens.
                    </div>
                  </div>
                </div>
                <div className="trailer-foot">
                  <div className="trailer-built-by">
                    {draftsCount > 0
                      ? `${draftsCount} draft${draftsCount > 1 ? "s" : ""} captured. Keep moving.`
                      : "Start your first draft and the trailer fills in."}
                  </div>
                  <button
                    className="btn primary"
                    style={{
                      background: "#b8862d",
                      color: "white",
                      padding: "8px 14px",
                      fontSize: 12,
                    }}
                    type="button"
                  >
                    Preview brief →
                  </button>
                </div>
              </section>

              <section className="card pad reveal" id="lessonPlan">
                <div className="section-title">
                  <div>
                    <h4>What the lesson gives you</h4>
                    <p>A student should feel the outcome before committing 45 minutes.</p>
                  </div>
                </div>
                <div className="score">
                  <div className="score-num">
                    <span className="count" data-to={draftQuality ?? 0}>
                      {draftQuality ?? "—"}
                    </span>
                  </div>
                  <div>
                    <strong>Current draft quality</strong>
                    <div className="small">
                      {draftQuality !== null
                        ? "Good fundamentals. Two gaps separate this from a strong senior submission."
                        : "Your first capstone submission seeds this score."}
                    </div>
                  </div>
                </div>
                <div className="list">
                  <div className="list-item">
                    <span className="bullet" />
                    <div>
                      <strong>You will write one real async request path</strong>
                      <span>
                        Not theory. One usable call structure with safe awaiting and clearer
                        organization.
                      </span>
                    </div>
                  </div>
                  <div className="list-item">
                    <span className="bullet warn" />
                    <div>
                      <strong>You will handle failure gracefully</strong>
                      <span>
                        Rate limits and transient errors are part of the skill, not edge cases
                        to ignore.
                      </span>
                    </div>
                  </div>
                  <div className="list-item">
                    <span className="bullet rose" />
                    <div>
                      <strong>You will leave with a stronger capstone draft</strong>
                      <span>
                        The work moves directly into your proof for promotion review.
                      </span>
                    </div>
                  </div>
                </div>
              </section>
            </div>
          </div>

          <aside className="rail">
            <section className="card rail-card reveal">
              <div className="eyebrow">Countdown</div>
              <div className="big-number">
                <span className="count" data-to={deadlineDays}>
                  {deadlineDays}
                </span>
              </div>
              <div className="small" style={{ marginTop: 8 }}>
                days to {targetRole} if you keep this pace.
              </div>
              <div className="small" style={{ marginTop: 4 }}>
                {lessonsLeft} lessons left across enrolled courses.
              </div>
            </section>

            <section className="card rail-card reveal delay-1">
              <div className="section-title" style={{ marginBottom: 8 }}>
                <div>
                  <h4 style={{ fontSize: 20 }}>What unlocks next</h4>
                </div>
              </div>
              <div className="timeline">
                <div className="t-row">
                  <div className={`t-mark ${steps.warm === "done" ? "done" : "now"}`}>
                    {steps.warm === "done" ? "✓" : "1"}
                  </div>
                  <div className="t-content">
                    <h6>Warm-up</h6>
                    <p>Recover memory and enter the lesson with momentum.</p>
                  </div>
                </div>
                <div className="t-row">
                  <div
                    className={`t-mark ${
                      steps.lesson === "done" ? "done" : steps.lesson === "active" ? "now" : ""
                    }`}
                  >
                    {steps.lesson === "done" ? "✓" : "2"}
                  </div>
                  <div className="t-content">
                    <h6>Lesson</h6>
                    <p>
                      {summary?.progress.next_lesson_title
                        ? summary.progress.next_lesson_title
                        : "Build the next practical outcome in Studio."}
                    </p>
                  </div>
                </div>
                <div className="t-row">
                  <div
                    className={`t-mark ${
                      steps.reflect === "done" ? "done" : steps.reflect === "active" ? "now" : ""
                    }`}
                  >
                    {steps.reflect === "done" ? "✓" : "3"}
                  </div>
                  <div className="t-content">
                    <h6>Reflection</h6>
                    <p>Lock one sentence into tomorrow&apos;s first card.</p>
                  </div>
                </div>
              </div>
            </section>

            {microWins.length > 0 && (
              <section className="card rail-card reveal delay-2">
                <div className="section-title" style={{ marginBottom: 8 }}>
                  <div>
                    <h4 style={{ fontSize: 20 }}>Yesterday&apos;s wins</h4>
                  </div>
                </div>
                <div className="cohort-stream">
                  {microWins.map((w) => (
                    <div className="cohort-item" key={`${w.kind}-${w.occurred_at}`}>
                      <span className="live-dot" />
                      <span>{w.label}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <section className="card rail-card reveal delay-2">
              <div className="section-title" style={{ marginBottom: 8 }}>
                <div>
                  <h4 style={{ fontSize: 20 }}>Cohort, live</h4>
                </div>
              </div>
              <div className="cohort-stream">
                {cohortEvents.length === 0 ? (
                  <div className="cohort-item">
                    <span className="live-dot" />
                    <span>Quiet right now. Be the first move today.</span>
                  </div>
                ) : (
                  cohortEvents.map((e, i) => (
                    <div className="cohort-item" key={`${e.actor_handle}-${i}`}>
                      <span className="live-dot" />
                      <span>
                        <b>{e.actor_handle}</b>{" "}
                        {stripLeadingHandle(e.actor_handle, e.label)}
                        <span className="small" style={{ marginLeft: 6, color: "#94a3b8" }}>
                          {" "}
                          · {relativeTime(e.occurred_at)}
                        </span>
                      </span>
                    </div>
                  ))
                )}
              </div>
            </section>
          </aside>
        </div>

        <div className="footer-cta reveal">
          <div>
            <div className="eyebrow" style={{ color: "#b8b0a3" }}>
              Best next action
            </div>
            <p>
              Finish the warm-up, unlock the lesson, and let the Studio review guide your next
              strongest draft.
            </p>
          </div>
          <button className="btn gold" onClick={handleAdvanceStep} type="button">
            {steps.warm !== "done"
              ? "Mark warm-up done"
              : steps.lesson !== "done"
                ? "Mark lesson done"
                : steps.reflect !== "done"
                  ? "Mark reflection done"
                  : "Session complete"}
          </button>
        </div>
      </div>
    </section>
  );
}
