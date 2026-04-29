"use client";

/**
 * P-Promo1 (2026-04-27) — Promotion screen rewired against
 * `/api/v1/promotion/summary` + `/api/v1/promotion/confirm`.
 *
 * Removes:
 *   - hardcoded `motivationToRole` mapping (now from `goal.target_role`)
 *   - hardcoded "Lessons 1 and 2 complete" copy (now derived from the
 *     real `progress.lessons_completed_total / lessons_total`)
 *   - hardcoded `overallProgress = 78` fallback
 *   - "Preview promotion moment" button that fired the takeover at any time
 *
 * The takeover now fires only when `gate_status === "ready_to_promote"`.
 * Clicking "Confirm promotion" POSTs `/promotion/confirm`, the backend
 * stamps `users.promoted_at`, and the cached summary flips to `promoted`.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { playUiSound } from "@/components/v8/v8-sound-toggle";
import {
  useConfirmPromotion,
  usePromotionSummary,
} from "@/lib/hooks/use-promotion-summary";
import type { PromotionRung } from "@/lib/api-client";
import { trackPromotionConfirmed } from "@/lib/analytics-events";

const CONFETTI_COLORS = ["#d6a54d", "#4e9470", "#9a4b3b", "#356d50", "#b8862d"] as const;
const CONFETTI_COUNT = 60;
const CONFETTI_LIFETIME_MS = 4500;

function formatPromotionDate(iso: string | null): string {
  const date = iso ? new Date(iso) : new Date();
  return date.toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

function rungClass(state: PromotionRung["state"]): string {
  const cls = ["rung"];
  if (state === "done") cls.push("done");
  if (state === "current") cls.push("current-pulse");
  return cls.join(" ");
}

function rungStateLabel(state: PromotionRung["state"]): string {
  if (state === "done") return "Done";
  if (state === "current") return "In progress";
  return "Locked";
}

export function PromotionScreen() {
  const router = useRouter();
  const { data: summary } = usePromotionSummary();
  const confirmPromotion = useConfirmPromotion();

  const overallProgress = summary?.overall_progress ?? 0;
  const role = summary?.role ?? { from_role: "Python Developer", to_role: "Data Analyst" };
  const rungs = summary?.rungs ?? [];
  const stats = summary?.stats;
  const userName = summary?.user_first_name ?? null;
  const promotionDate = useMemo(
    () => formatPromotionDate(summary?.promoted_at ?? null),
    [summary?.promoted_at],
  );

  useSetV8Topbar({
    eyebrow: "Promotion gate",
    titleHtml: "One title change. Earned through <i>evidence</i>.",
    chips: [],
    progress: overallProgress,
  });

  // Takeover state. Derived from the gate status — when the backend says
  // ready_to_promote we open the takeover; the user dismisses by either
  // confirming (which flips the gate to "promoted") or hitting Close (which
  // sets a manual override). For the already-promoted state we DON'T fire
  // automatically — the celebration already happened.
  const [manuallyClosed, setManuallyClosed] = useState(false);
  const [manuallyReopened, setManuallyReopened] = useState(false);
  const takeoverOpen =
    !manuallyClosed &&
    (manuallyReopened || summary?.gate_status === "ready_to_promote");

  const confettiHostRef = useRef<HTMLDivElement | null>(null);
  const cleanupTimersRef = useRef<number[]>([]);

  const closeTakeover = useCallback(() => {
    setManuallyReopened(false);
    setManuallyClosed(true);
  }, []);
  const openTakeover = useCallback(() => {
    setManuallyClosed(false);
    setManuallyReopened(true);
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

  const handleConfirm = useCallback(() => {
    closeTakeover();
    playUiSound("promote");
    confirmPromotion.mutate(undefined, {
      onSuccess: () => {
        // PR3/C3.2 — track on success only; a confirm that 500s
        // shouldn't show as a promotion in PostHog. The `level` is
        // the count of rungs climbed in this promotion event
        // (currently always 4, but tracked numerically so a future
        // partial-rung schema doesn't lose data).
        trackPromotionConfirmed({ level: rungs.length });
      },
      onSettled: () => {
        router.push("/today");
      },
    });
  }, [closeTakeover, confirmPromotion, router, rungs.length]);

  const handleViewInterviewPrep = useCallback(() => {
    router.push("/readiness");
  }, [router]);

  const gateStatus = summary?.gate_status ?? "not_ready";
  const alreadyPromoted = gateStatus === "promoted";

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
              {userName ? `${userName}, p` : "P"}romotion is ceremonial and
              earned. The gate opens when all four rungs flip to{" "}
              <i>done</i> — capstone, lessons, interviews, foundation.
            </p>

            <div className="rung-wrap">
              <div>
                <div className="rungs">
                  {rungs.length === 0 ? (
                    Array.from({ length: 4 }).map((_, idx) => (
                      <div className="rung" key={idx} style={{ opacity: 0.4 }}>
                        <div>
                          <strong>Loading…</strong>
                          <span>&nbsp;</span>
                        </div>
                        <div className="rung-state">·</div>
                      </div>
                    ))
                  ) : (
                    rungs.map((rung) => (
                      <div className={rungClass(rung.state)} key={rung.kind}>
                        <div>
                          <strong>{rung.title}</strong>
                          <span>{rung.detail}</span>
                        </div>
                        <div className="rung-state">
                          {rungStateLabel(rung.state)}
                        </div>
                      </div>
                    ))
                  )}
                </div>
                <div className="hero-actions" style={{ marginTop: 18 }}>
                  {alreadyPromoted ? (
                    <button
                      type="button"
                      className="btn gold"
                      disabled
                      aria-label="Promotion already confirmed"
                    >
                      Promoted on {promotionDate}
                    </button>
                  ) : gateStatus === "ready_to_promote" ? (
                    <button
                      type="button"
                      className="btn gold"
                      onClick={openTakeover}
                    >
                      Open promotion ceremony
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn gold"
                      disabled
                      aria-disabled="true"
                      title="Finish all four rungs to open the gate."
                    >
                      Gate locked — finish all rungs
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn secondary"
                    onClick={handleViewInterviewPrep}
                  >
                    View interview prep
                  </button>
                </div>
              </div>

              <div className="ladder-shell">
                <div className="ladder-rail left" />
                <div className="ladder-rail right" />
                {rungs.map((rung, idx) => (
                  <div
                    key={rung.kind}
                    className={`ladder-rung lr${idx + 1}${rung.state === "done" ? " done" : ""}`}
                  >
                    {rung.short_label}
                  </div>
                ))}
                <div className="ladder-floor" />
              </div>
            </div>
          </section>
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
          <div className="takeover-eyebrow">
            Promotion confirmed · {promotionDate}
          </div>
          <h1 className="takeover-title">
            You are, officially,
            <br />
            <i>{role.to_role}</i>.
          </h1>
          <div className="takeover-role-transition">
            <span className="from">{role.from_role}</span>
            <span className="arrow">→</span>
            <span className="to">{role.to_role}</span>
          </div>
          <p className="takeover-desc">
            You shipped the capstone. You passed senior review. You held
            your ground in the interview. Your role is now updated
            everywhere — resume, profile, sidebar.
          </p>
          {stats ? (
            <div className="takeover-stats">
              <span>
                <b>{stats.completed_lessons}</b> lessons
              </span>
              <span>
                <b>{stats.capstone_submissions}</b> capstone draft
                {stats.capstone_submissions === 1 ? "" : "s"}
              </span>
              <span>
                <b>{stats.completed_interviews}</b> interviews
              </span>
            </div>
          ) : null}
          <div className="takeover-actions">
            <button
              type="button"
              className="takeover-btn primary"
              onClick={handleConfirm}
              disabled={confirmPromotion.isPending}
            >
              {confirmPromotion.isPending
                ? "Confirming…"
                : `Begin ${role.to_role} →`}
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
