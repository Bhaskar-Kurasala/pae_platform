"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { v8Toast } from "@/components/v8/v8-toast";
import { useDueCards, useReviewCard } from "@/lib/hooks/use-srs";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { useMyGoal } from "@/lib/hooks/use-goal";
import { useConsistency } from "@/lib/hooks/use-today";
import { useAuthStore } from "@/stores/auth-store";

type StepState = "active" | "locked" | "done";

interface FallbackCard {
  id: string;
  prompt: string;
  answer: string;
  hint: string;
}

const FALLBACK_CARDS: ReadonlyArray<FallbackCard> = [
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

export function TodayScreen() {
  const { user } = useAuthStore();
  const { data: dueCards } = useDueCards(7);
  const { data: progress } = useMyProgress();
  const { data: goal } = useMyGoal();
  const { data: consistency } = useConsistency();
  const reviewCard = useReviewCard();

  const dueCount = dueCards?.length ?? 7;
  const streak = consistency?.days_this_week ?? 0;
  const overallProgress = Math.round(progress?.overall_progress ?? 34);
  const deadlineDays = goal?.deadline_months
    ? Math.max(1, Math.round(goal.deadline_months * 30))
    : 58;

  const { weekday, monthDay, sessionNumber } = useMemo(() => {
    const now = new Date();
    return {
      weekday: now.toLocaleDateString("en-US", { weekday: "long" }),
      monthDay: now.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      sessionNumber: 14,
    };
  }, []);

  useSetV8Topbar({
    eyebrow: `${weekday} · ${monthDay} · Session ${sessionNumber}`,
    titleHtml: "A modern learning flow that feels <i>alive</i>.",
    chips: [
      { label: `Day ${streak} streak`, variant: "forest" },
      { label: `${dueCount} review cards`, variant: "gold" },
      { label: "One clear next action", variant: "ink" },
    ],
    progress: overallProgress,
  });

  const cards: ReadonlyArray<FallbackCard> = useMemo(() => {
    if (!dueCards || dueCards.length === 0) return FALLBACK_CARDS;
    return dueCards.slice(0, 7).map((c, i) => ({
      id: c.id,
      prompt: c.prompt,
      answer: "Recall the concept and grade your honesty.",
      hint: FALLBACK_CARDS[i % FALLBACK_CARDS.length]?.hint ?? "Reveal when ready.",
    }));
  }, [dueCards]);

  const totalCards = Math.max(cards.length, 1);
  const [cardIndex, setCardIndex] = useState(3);
  const [revealed, setRevealed] = useState(false);
  const [steps, setSteps] = useState<{ warm: StepState; lesson: StepState; reflect: StepState }>({
    warm: "active",
    lesson: "locked",
    reflect: "locked",
  });

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
      setCardIndex((idx) => Math.min(idx + 1, totalCards));
    },
    [cards, cardIndex, reviewCard, totalCards],
  );

  const handleSimulateUnlock = useCallback(() => {
    setSteps((prev) => {
      if (prev.warm !== "done") {
        v8Toast("Warm-up complete. Lesson unlocked.");
        return { warm: "done", lesson: "active", reflect: "locked" };
      }
      if (prev.lesson !== "done") {
        v8Toast("Lesson complete. Reflection unlocked.");
        return { warm: "done", lesson: "done", reflect: "active" };
      }
      v8Toast("Session closed. See you tomorrow.");
      return { warm: "done", lesson: "done", reflect: "done" };
    });
  }, []);

  const handleSeeLessonPlan = useCallback(() => {
    document.getElementById("lessonPlan")?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const firstName = user?.full_name?.split(" ")[0] ?? "you";

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
                  You&apos;re 4 lessons closer to {goal?.success_statement ?? "your next role"} than you were a week ago.
                </p>
                <p>
                  This version adds modern motion where it helps students: entering focus,
                  understanding what changed, feeling unlock moments, and moving toward a role
                  with calm confidence.
                </p>
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    alignItems: "center",
                    flexWrap: "wrap",
                    margin: "18px 0 4px",
                  }}
                >
                  <span className="peer-chip">
                    <span className="peer-dot" />
                    <span>12 peers at your level today</span>
                    <span className="peer-faces">
                      <span className="peer-face">A</span>
                      <span className="peer-face">N</span>
                      <span className="peer-face">M</span>
                    </span>
                  </span>
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
                    <span>3 just promoted to Data Analyst</span>
                  </span>
                </div>
                <div className="hero-actions">
                  <Link href="/studio" className="btn primary">
                    Continue lesson
                  </Link>
                  <button className="btn secondary" onClick={handleSeeLessonPlan} type="button">
                    See lesson plan
                  </button>
                </div>
                <div className="moment-ribbon">
                  <span className="moment-dot" />
                  <span>
                    {firstName}&apos;s job readiness rose <b>+8</b> this week. One more lesson
                    likely lifts it above 65% — the threshold where recruiter replies jump in
                    cohort data.
                  </span>
                </div>
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
                  <div className="sub">
                    to Data Analyst if you keep a steady three sessions each week.
                  </div>
                </div>
                <div className="kpi reveal delay-2">
                  <div className="label">Today unlocks</div>
                  <div className="value">+17%</div>
                  <div className="sub">
                    toward finishing Level 1 and opening your capstone gate.
                  </div>
                </div>
                <div className="kpi reveal delay-3">
                  <div className="label">Current focus</div>
                  <div className="value">APIs</div>
                  <div className="sub">
                    async requests, retries, and handling failure without losing flow.
                  </div>
                </div>
                <div className="kpi reveal delay-4">
                  <div className="label">Proof created</div>
                  <div className="value">1 draft</div>
                  <div className="sub">
                    your CLI AI tool becomes evidence for promotion, not just practice.
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
                    Seven spaced-repetition cards from prior lessons. Fast enough to begin.
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
                    One practical outcome: write an async API client with retries and
                    environment-based auth.
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
                    <h5>{activeCard.prompt}</h5>
                    <p id="cardHintText">{activeCard.hint}</p>
                  </div>
                  <div className="card-face card-face-back">
                    <div className="card-back-recap">
                      <span className="recap-label">Question</span>
                      <span className="recap-text">{activeCard.prompt}</span>
                    </div>
                    <div className="card-face-eyebrow">Answer</div>
                    <p id="cardAnswerText">{activeCard.answer}</p>
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
                  ★ Your capstone — the proof of Python Developer
                </div>
                <div className="trailer-title">CLI AI tool · 5 days from now</div>
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
                    &ldquo;Building this changed how I read other people&apos;s code.&rdquo; — Nisha,
                    promoted Apr 18
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
                    <span className="count" data-to="84">
                      84
                    </span>
                  </div>
                  <div>
                    <strong>Current draft quality</strong>
                    <div className="small">
                      Good fundamentals. Two gaps separate this from a strong senior submission.
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
                days to Data Analyst if you keep this pace.
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
                    <p>Build an async API client with retry logic and env auth.</p>
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

            <section className="card rail-card reveal delay-2">
              <div className="section-title" style={{ marginBottom: 8 }}>
                <div>
                  <h4 style={{ fontSize: 20 }}>Cohort, live</h4>
                </div>
              </div>
              <div className="cohort-stream">
                <div className="cohort-item">
                  <span className="live-dot" />
                  <span>
                    <b>Priya</b> passed Python Developer to Data Analyst two minutes ago.
                  </span>
                </div>
                <div className="cohort-item">
                  <span className="live-dot" />
                  <span>
                    <b>Marcus</b> shipped a capstone revision with retry logic.
                  </span>
                </div>
                <div className="cohort-item">
                  <span className="live-dot" />
                  <span>
                    <b>Nisha</b> unlocked Lesson 3 and started Studio.
                  </span>
                </div>
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
          <button className="btn gold" onClick={handleSimulateUnlock} type="button">
            Simulate unlock
          </button>
        </div>
      </div>
    </section>
  );
}
