"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { playUiSound } from "@/components/v8/v8-sound-toggle";
import { useMyGoal } from "@/lib/hooks/use-goal";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { useDueCards } from "@/lib/hooks/use-srs";
import { useInterviewSessions } from "@/lib/hooks/use-interview";
import { useAuthStore } from "@/stores/auth-store";

type RungState = "done" | "current" | "locked";

interface RungSpec {
  title: string;
  detail: string;
  state: RungState;
}

const CONFETTI_COLORS = ["#d6a54d", "#4e9470", "#9a4b3b", "#356d50", "#b8862d"] as const;
const CONFETTI_COUNT = 60;
const CONFETTI_LIFETIME_MS = 4500;

function motivationToRole(motivation: string | undefined): { from: string; to: string } {
  switch (motivation) {
    case "career_switch":
      return { from: "Python Developer", to: "Data Analyst" };
    case "skill_up":
      return { from: "Engineer", to: "Senior Engineer" };
    case "interview":
      return { from: "Candidate", to: "Hired Engineer" };
    case "curiosity":
      return { from: "Learner", to: "Practitioner" };
    default:
      return { from: "Python Developer", to: "Data Analyst" };
  }
}

export function PromotionScreen() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const { data: goal } = useMyGoal();
  const { data: progress } = useMyProgress();
  const { data: dueCards } = useDueCards(1);
  const { data: interviewSessions } = useInterviewSessions();

  const completedLessons = useMemo(
    () => progress?.courses.reduce((acc, c) => acc + c.completed_lessons, 0) ?? 0,
    [progress],
  );
  const totalLessons = useMemo(
    () => progress?.courses.reduce((acc, c) => acc + c.total_lessons, 0) ?? 0,
    [progress],
  );
  const remainingLessons = Math.max(0, totalLessons - completedLessons);
  const completedInterviews = useMemo(
    () => interviewSessions?.filter((s) => s.status === "completed").length ?? 0,
    [interviewSessions],
  );

  const overallProgress = progress?.overall_progress ?? 78;
  const role = motivationToRole(goal?.motivation);
  const promotionDate = useMemo(
    () =>
      new Date().toLocaleDateString("en-US", {
        month: "long",
        day: "numeric",
        year: "numeric",
      }),
    [],
  );

  const rungs: RungSpec[] = useMemo(
    () => [
      {
        title: "Lessons 1 and 2 complete",
        detail: "Your foundation is already in place.",
        state: completedLessons >= 2 ? "done" : "current",
      },
      {
        title:
          remainingLessons > 0
            ? `Finish ${remainingLessons} remaining lesson${remainingLessons === 1 ? "" : "s"}`
            : "All lessons complete",
        detail: "APIs, testing, and collaboration close Level 1.",
        state: remainingLessons > 0 ? "current" : "done",
      },
      {
        title: "Submit capstone",
        detail: "One real artifact proves the role, not just attendance.",
        state: "locked",
      },
      {
        title: "Complete 2 practice interviews",
        detail: "Pressure-test your thinking before the actual gate.",
        state:
          completedInterviews >= 2
            ? "done"
            : completedInterviews > 0
              ? "current"
              : "locked",
      },
    ],
    [completedLessons, remainingLessons, completedInterviews],
  );

  useSetV8Topbar({
    eyebrow: "Promotion gate",
    titleHtml: "One title change. Earned through <i>evidence</i>.",
    chips: [],
    progress: Math.round(overallProgress),
  });

  const [takeoverOpen, setTakeoverOpen] = useState(false);
  const confettiHostRef = useRef<HTMLDivElement | null>(null);
  const cleanupTimersRef = useRef<number[]>([]);

  const closeTakeover = useCallback(() => {
    setTakeoverOpen(false);
  }, []);

  const spawnConfetti = useCallback(() => {
    const host = confettiHostRef.current;
    if (!host) return;
    for (let i = 0; i < CONFETTI_COUNT; i++) {
      const node = document.createElement("div");
      node.className = "confetti";
      node.style.left = `${Math.random() * 100}%`;
      node.style.background =
        CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)];
      node.style.animationDelay = `${Math.random() * 0.4}s`;
      node.style.animationDuration = `${2.5 + Math.random() * 1.5}s`;
      node.style.transform = `rotate(${Math.random() * 360}deg)`;
      host.appendChild(node);
      const timer = window.setTimeout(() => {
        node.remove();
      }, CONFETTI_LIFETIME_MS);
      cleanupTimersRef.current.push(timer);
    }
  }, []);

  const openTakeover = useCallback(() => {
    setTakeoverOpen(true);
  }, []);

  useEffect(() => {
    if (!takeoverOpen) return;
    const host = confettiHostRef.current;
    spawnConfetti();
    const t1 = window.setTimeout(() => playUiSound("promote"), 200);
    const t2 = window.setTimeout(() => playUiSound("complete"), 500);
    const t3 = window.setTimeout(() => playUiSound("promote"), 800);
    const timers = cleanupTimersRef.current;
    timers.push(t1, t2, t3);

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeTakeover();
    };
    window.addEventListener("keydown", onKey);

    return () => {
      window.removeEventListener("keydown", onKey);
      timers.forEach((t) => window.clearTimeout(t));
      cleanupTimersRef.current = [];
      if (host) {
        while (host.firstChild) host.removeChild(host.firstChild);
      }
    };
  }, [takeoverOpen, spawnConfetti, closeTakeover]);

  const beginNewRole = useCallback(() => {
    closeTakeover();
    playUiSound("promote");
    router.push("/today");
  }, [closeTakeover, router]);

  const dueCount = dueCards?.length ?? 0;
  const userName = user?.full_name?.split(" ")[0];

  return (
    <>
      <section className="screen active">
        <div className="pad">
          <section className="card promo-hero reveal">
            <div className="eyebrow" style={{ color: "#bfae88" }}>
              Promotion gate
            </div>
            <h3>
              Climb four <i>rungs</i>. Earn one new title.
            </h3>
            <p>
              {userName ? `${userName}, p` : "P"}romotion should feel ceremonial and earned.
              v5 keeps the gravitas, but the motion is cleaner and the gate is easier to
              understand at a glance.
            </p>

            <div className="rung-wrap">
              <div>
                <div className="rungs">
                  {rungs.map((rung, idx) => {
                    const cls = ["rung"];
                    if (rung.state === "done") cls.push("done");
                    if (rung.state === "current") cls.push("current-pulse");
                    const stateLabel =
                      rung.state === "done"
                        ? "Done"
                        : rung.state === "current"
                          ? "In progress"
                          : "Locked";
                    return (
                      <div className={cls.join(" ")} key={idx}>
                        <div>
                          <strong>{rung.title}</strong>
                          <span>{rung.detail}</span>
                        </div>
                        <div className="rung-state">{stateLabel}</div>
                      </div>
                    );
                  })}
                </div>
                <div className="hero-actions" style={{ marginTop: 18 }}>
                  <button type="button" className="btn gold" onClick={openTakeover}>
                    Preview promotion moment
                  </button>
                  <button
                    type="button"
                    className="btn secondary"
                    onClick={() => router.push("/readiness")}
                  >
                    View interview prep
                  </button>
                </div>
              </div>

              <div className="ladder-shell">
                <div className="ladder-rail left" />
                <div className="ladder-rail right" />
                <div
                  className={`ladder-rung lr1${rungs[0].state === "done" ? " done" : ""}`}
                >
                  Lessons 1 and 2 complete
                </div>
                <div
                  className={`ladder-rung lr2${rungs[1].state === "done" ? " done" : ""}`}
                >
                  {remainingLessons > 0
                    ? `${remainingLessons} remaining lesson${remainingLessons === 1 ? "" : "s"}`
                    : "All lessons done"}
                </div>
                <div
                  className={`ladder-rung lr3${rungs[2].state === "done" ? " done" : ""}`}
                >
                  Capstone submitted
                </div>
                <div
                  className={`ladder-rung lr4${rungs[3].state === "done" ? " done" : ""}`}
                >
                  2 practice interviews
                </div>
                <div className="ladder-floor" />
              </div>
            </div>
          </section>

          <div className="win-panel" id="winPanel" style={{ display: "none" }}>
            <div className="card win-card">
              <div className="win-top">
                <div className="win-seal">
                  <svg
                    width="42"
                    height="42"
                    viewBox="0 0 42 42"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={3}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polyline points="10,22 18,30 32,14" />
                  </svg>
                </div>
                <div className="eyebrow" style={{ color: "#e0c98c" }}>
                  Promotion confirmed · {promotionDate}
                </div>
                <h3>
                  You are, officially, <i>{role.to}</i>.
                </h3>
                <p>
                  You shipped the capstone. You passed review. You held your ground in the
                  interview. The product should make this feel like a real transition in
                  identity.
                </p>
              </div>
              <div className="win-body">
                <div className="win-stats">
                  <div className="ws">
                    <strong>{completedLessons}</strong>
                    <span>Lessons</span>
                  </div>
                  <div className="ws">
                    <strong>{dueCount}</strong>
                    <span>Cards due</span>
                  </div>
                  <div className="ws">
                    <strong>Level 2</strong>
                    <span>Unlocked</span>
                  </div>
                </div>
                <div className="win-actions">
                  <button type="button" className="btn primary" onClick={beginNewRole}>
                    Begin {role.to}
                  </button>
                  <button type="button" className="btn ghost">
                    Download certificate
                  </button>
                  <button type="button" className="btn ghost">
                    Share
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <div
        className={`promo-takeover${takeoverOpen ? " show" : ""}`}
        id="promoTakeover"
        role="dialog"
        aria-modal="true"
        aria-hidden={!takeoverOpen}
      >
        <div ref={confettiHostRef} aria-hidden />
        <div className="takeover-content">
          <div className="takeover-seal">
            <svg
              width="44"
              height="44"
              viewBox="0 0 44 44"
              fill="none"
              stroke="currentColor"
              strokeWidth={3}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="11,23 19,31 33,15" />
            </svg>
          </div>
          <div className="takeover-eyebrow">Promotion confirmed · {promotionDate}</div>
          <h1 className="takeover-title">
            You are, officially,
            <br />
            <i>{role.to}</i>.
          </h1>
          <div className="takeover-role-transition">
            <span className="from">{role.from}</span>
            <span className="arrow">→</span>
            <span className="to">{role.to}</span>
          </div>
          <p className="takeover-desc">
            You shipped the capstone. You passed senior review. You held your ground in
            the interview. Your role is now updated everywhere — resume, profile, sidebar.
          </p>
          <div className="takeover-actions">
            <button
              type="button"
              className="takeover-btn primary"
              onClick={beginNewRole}
            >
              Begin {role.to} →
            </button>
            <button type="button" className="takeover-btn ghost" onClick={closeTakeover}>
              Close
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
