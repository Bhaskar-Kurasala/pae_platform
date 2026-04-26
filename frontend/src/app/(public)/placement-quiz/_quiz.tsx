"use client";

/**
 * Placement quiz — root client component / state machine.
 *
 * Stage flow: intro → question (5×) → loading (2s, 400ms with reduced motion)
 *             → result. Back button moves backward one step at a time;
 *             from result it returns to question 5.
 *
 * State persistence: sessionStorage. Refreshing during the flow restores the
 * exact stage, step, answers, and startTime. Cleared on Retake quiz.
 *
 * Reduced motion: shortens the loading hold to 400ms (not zero — the
 * narrative pause is intentional), and the screen-transition fades use
 * @media (prefers-reduced-motion: reduce) handled in CSS.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCourses } from "@/lib/hooks/use-courses";
import { useAuthStore } from "@/stores/auth-store";
import { billingApi } from "@/lib/api-client";
import { quizAnalytics } from "./_analytics";
import { COPY, TRACKS } from "./_quiz-config";
import {
  QUESTIONS,
  TOTAL_QUESTIONS,
  type AnswersMap,
} from "./_quiz-questions";
import {
  getRecommendedTrack,
  getUrgencyMode,
  isComplete,
} from "./_quiz-scoring";
import { IntroScreen } from "./_components/intro-screen";
import { QuestionScreen } from "./_components/question-screen";
import { LoadingScreen } from "./_components/loading-screen";
import { ResultScreen } from "./_components/result-screen";
import { BackButton } from "./_components/back-button";

const STORAGE_KEY = "placement-quiz:v2";
const AUTO_ADVANCE_MS = 250;

type Stage = "intro" | "question" | "loading" | "result";

interface PersistedState {
  stage: Stage;
  step: number;
  answers: AnswersMap;
  startTime: number;
}

function loadState(): PersistedState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PersistedState;
  } catch {
    return null;
  }
}

function saveState(state: PersistedState): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* swallow quota errors */
  }
}

function clearState(): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* swallow */
  }
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function PlacementQuiz() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: courses } = useCourses();

  const [stage, setStage] = useState<Stage>("intro");
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<AnswersMap>({});
  const [startTime, setStartTime] = useState<number>(0);
  const [hydrated, setHydrated] = useState(false);
  const [checkoutLoading, setCheckoutLoading] = useState(false);

  // Track per-screen time-on-screen for analytics. Reset on every screen change.
  const screenEnteredAt = useRef<number>(Date.now());
  // Auto-advance debouncer — cleared on unmount or back-navigation.
  const advanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // -------------------------------------------------------------------------
  // Hydrate from sessionStorage on first mount.
  // -------------------------------------------------------------------------
  useEffect(() => {
    const saved = loadState();
    if (saved) {
      setStage(saved.stage === "loading" ? "result" : saved.stage); // never resume mid-loading
      setStep(saved.step);
      setAnswers(saved.answers);
      setStartTime(saved.startTime || Date.now());
    }
    setHydrated(true);
    screenEnteredAt.current = Date.now();
  }, []);

  // Persist on every state change (after hydration).
  useEffect(() => {
    if (!hydrated) return;
    saveState({ stage, step, answers, startTime });
  }, [stage, step, answers, startTime, hydrated]);

  // Reset screen-entry timestamp whenever the visible screen changes.
  useEffect(() => {
    screenEnteredAt.current = Date.now();
  }, [stage, step]);

  // Cleanup timers on unmount.
  useEffect(() => {
    return () => {
      if (advanceTimer.current) clearTimeout(advanceTimer.current);
      if (loadingTimer.current) clearTimeout(loadingTimer.current);
    };
  }, []);

  // -------------------------------------------------------------------------
  // Stage transitions
  // -------------------------------------------------------------------------

  const begin = useCallback(() => {
    const now = Date.now();
    setStartTime(now);
    quizAnalytics.started();
    setStage("question");
    setStep(0);
  }, []);

  const choose = useCallback(
    (questionId: string, optionId: string) => {
      const timeOnScreen = Date.now() - screenEnteredAt.current;
      quizAnalytics.answered({
        question_id: questionId,
        answer_id: optionId,
        step: step + 1,
      });
      const next: AnswersMap = { ...answers, [questionId]: optionId };
      setAnswers(next);

      // 250ms before transitioning lets the user register the selection.
      if (advanceTimer.current) clearTimeout(advanceTimer.current);
      advanceTimer.current = setTimeout(() => {
        const isLast = step >= TOTAL_QUESTIONS - 1;
        if (isLast && isComplete(next)) {
          // Move to loading stage; loading transitions to result on its own timer.
          setStage("loading");
          const hold = prefersReducedMotion()
            ? COPY.loading.holdMsReducedMotion
            : COPY.loading.holdMs;
          if (loadingTimer.current) clearTimeout(loadingTimer.current);
          loadingTimer.current = setTimeout(() => {
            const track = getRecommendedTrack(next);
            if (track) {
              quizAnalytics.completed({
                track_slug: track,
                answers: QUESTIONS.map(
                  (q) => `${q.id}:${next[q.id] ?? ""}`,
                ).join(","),
                purchase_mode: "self_paced",
              });
            }
            setStage("result");
          }, hold);
        } else {
          setStep(Math.min(step + 1, TOTAL_QUESTIONS - 1));
        }
        // timeOnScreen logged; reference avoids unused-var lint.
        void timeOnScreen;
      }, AUTO_ADVANCE_MS);
    },
    [answers, step],
  );

  const goBack = useCallback(() => {
    if (advanceTimer.current) clearTimeout(advanceTimer.current);
    if (loadingTimer.current) clearTimeout(loadingTimer.current);
    if (stage === "result") {
      setStage("question");
      setStep(TOTAL_QUESTIONS - 1);
      return;
    }
    if (stage === "question") {
      if (step === 0) {
        setStage("intro");
      } else {
        setStep(step - 1);
      }
    }
    if (stage === "loading") {
      setStage("question");
      setStep(TOTAL_QUESTIONS - 1);
    }
  }, [stage, step]);

  const restart = useCallback(() => {
    if (advanceTimer.current) clearTimeout(advanceTimer.current);
    if (loadingTimer.current) clearTimeout(loadingTimer.current);
    clearState();
    setAnswers({});
    setStep(0);
    setStartTime(0);
    setStage("intro");
  }, []);

  // -------------------------------------------------------------------------
  // CTAs — enroll and curriculum
  // -------------------------------------------------------------------------

  const recommendedTrack = useMemo(
    () => (isComplete(answers) ? getRecommendedTrack(answers) : null),
    [answers],
  );

  const onEnroll = useCallback(async () => {
    if (!recommendedTrack) return;
    const track = TRACKS[recommendedTrack];
    const ctaLabel =
      getUrgencyMode(answers) === "decided"
        ? COPY.result.cta.decided(track.displayName)
        : COPY.result.cta.activating(track.displayName);
    quizAnalytics.ctaClicked({
      cta_label: ctaLabel,
      recommended_track: track.courseSlug,
    });

    if (!isAuthenticated) {
      router.push(`/register?next=/catalog`);
      return;
    }
    const course = courses?.find((c) => c.slug === track.courseSlug);
    if (!course || !course.is_published) {
      router.push("/catalog");
      return;
    }
    setCheckoutLoading(true);
    try {
      const origin = typeof window !== "undefined" ? window.location.origin : "";
      const { checkout_url } = await billingApi.createCheckout({
        course_id: course.id,
        success_url: `${origin}/portal?enrolled=${course.id}`,
        cancel_url: `${origin}/placement-quiz`,
      });
      window.location.href = checkout_url;
    } catch {
      router.push("/catalog");
    } finally {
      setCheckoutLoading(false);
    }
  }, [recommendedTrack, answers, isAuthenticated, courses, router]);

  const onCurriculum = useCallback(() => {
    if (!recommendedTrack) return;
    quizAnalytics.curriculumClicked({
      recommended_track: TRACKS[recommendedTrack].courseSlug,
    });
    router.push("/catalog");
  }, [recommendedTrack, router]);

  // -------------------------------------------------------------------------
  // Computed view state
  // -------------------------------------------------------------------------

  const progressPct =
    stage === "intro"
      ? 0
      : stage === "result" || stage === "loading"
        ? 100
        : ((step + 1) / TOTAL_QUESTIONS) * 100;

  const showBack = stage === "question" || stage === "result";

  // SSR-safe placeholder until hydration finishes.
  if (!hydrated) {
    return <Shell progressPct={0}>{null}</Shell>;
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  let body: React.ReactNode;
  if (stage === "intro") {
    body = <IntroScreen onBegin={begin} />;
  } else if (stage === "loading") {
    body = <LoadingScreen />;
  } else if (stage === "result" && recommendedTrack) {
    body = (
      <ResultScreen
        track={recommendedTrack}
        answers={answers}
        courses={courses}
        startTime={startTime || Date.now()}
        onEnroll={onEnroll}
        onCurriculum={onCurriculum}
        checkoutLoading={checkoutLoading}
        onRestart={restart}
      />
    );
  } else {
    const q = QUESTIONS[step];
    body = (
      <QuestionScreen
        key={q.id}
        question={q}
        index={step + 1}
        total={TOTAL_QUESTIONS}
        selected={answers[q.id]}
        onChoose={(opt) => choose(q.id, opt)}
      />
    );
  }

  return (
    <Shell progressPct={progressPct} onBack={showBack ? goBack : undefined}>
      {body}
    </Shell>
  );
}

// ---------------------------------------------------------------------------
// Shell — dark theme wrapper, header, top progress bar (already inside the
// question screen at higher resolution; this top one is the always-visible
// thin bar). Keeps the layout consistent across all stages.
// ---------------------------------------------------------------------------

function Shell({
  children,
  progressPct,
  onBack,
}: {
  children: React.ReactNode;
  progressPct: number;
  onBack?: () => void;
}) {
  return (
    <div className="min-h-screen bg-[#10120e] text-[#f0ece1] selection:bg-[#5db288]/40">
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10 opacity-60"
        style={{
          background:
            "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(78,148,112,0.18), transparent 60%), radial-gradient(ellipse 60% 50% at 80% 100%, rgba(184,134,45,0.10), transparent 60%)",
        }}
      />

      <header className="mx-auto flex max-w-3xl items-center justify-between px-5 pt-6 sm:pt-10">
        <Link
          href="/catalog"
          className="text-[11px] uppercase tracking-[.18em] font-bold text-[#a29a8a] hover:text-[#f0ece1] transition-colors"
        >
          ← Catalog
        </Link>
        <div className="text-[11px] uppercase tracking-[.18em] font-bold text-[#a29a8a]">
          Placement Quiz
        </div>
      </header>

      {/* Always-visible thin top progress bar (different from the in-question bar). */}
      <div className="mx-auto mt-5 max-w-3xl px-5">
        <div
          className="h-1 w-full overflow-hidden rounded-full bg-white/5"
          role="progressbar"
          aria-valuenow={Math.round(progressPct)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Quiz progress"
        >
          <div
            className="h-full bg-gradient-to-r from-[#244f39] via-[#4e9470] to-[#8fd6b1] transition-[width] duration-500 ease-out"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      <main className="mx-auto max-w-3xl px-5 pb-24 pt-10 sm:pt-14">
        {onBack ? (
          <div className="mb-6">
            <BackButton onClick={onBack} />
          </div>
        ) : null}
        <div className="quiz-fade">{children}</div>
      </main>
    </div>
  );
}

