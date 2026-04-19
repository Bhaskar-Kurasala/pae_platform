"use client";

import { useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { MotionFade } from "@/components/ui/motion-fade";
import { TodayConsistency } from "@/components/features/today-consistency";
import { TodayGoalBanner } from "@/components/features/today-goal-banner";
import { TodayIntention } from "@/components/features/today-intention";
import { TodayMicroWins } from "@/components/features/today-micro-wins";
import { TodayNextAction } from "@/components/features/today-next-action";
import { TodayReflection } from "@/components/features/today-reflection";
import { TodayReview } from "@/components/features/today-review";
import { TodaySignal } from "@/components/features/today-signal";
import { TeachBackWidget } from "@/components/features/teach-back-widget";
import { useMyGoal } from "@/lib/hooks/use-goal";
import { useAuthStore } from "@/stores/auth-store";
import { PageShell } from "@/components/layouts/page-shell";

type Variant = "morning" | "evening";

function greeting(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function currentVariant(hour: number): Variant {
  return hour >= 18 ? "evening" : "morning";
}

export default function TodayPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { data: goal, isLoading, isError } = useMyGoal();

  const hour = useMemo(() => new Date().getHours(), []);
  const variant = currentVariant(hour);

  useEffect(() => {
    if (!isLoading && !isError && goal === null) {
      router.replace("/onboarding");
    }
  }, [goal, isLoading, isError, router]);

  useEffect(() => {
    try {
      window.dispatchEvent(
        new CustomEvent("today.variant_shown", { detail: { variant } }),
      );
    } catch {
      /* ignore */
    }
  }, [variant]);

  if (isLoading || !goal) {
    return (
      <div
        className="flex min-h-[60vh] items-center justify-center"
        aria-busy="true"
        aria-live="polite"
      >
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const firstName = user?.full_name?.split(" ")[0] ?? "there";
  const today = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  const isMorning = variant === "morning";

  return (
    <PageShell variant="narrow" density="flush" className="px-6 py-10 md:py-14">
      <MotionFade>
        <header className="mb-8">
          <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
            Today · {today} · {isMorning ? "Morning view" : "Evening view"}
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">
            {greeting(hour)}, {firstName}.
          </h1>
        </header>
      </MotionFade>

      <div className="flex flex-col gap-5">
        <MotionFade delay={0.05}>
          <section
            id="today-goal-banner"
            aria-label="Your goal"
            data-slot="goal-banner"
          >
            <TodayGoalBanner goal={goal} />
          </section>
        </MotionFade>

        {isMorning && (
          <MotionFade delay={0.08}>
            <section
              id="today-intention"
              aria-label="Today's intention"
              data-slot="intention"
            >
              <TodayIntention />
            </section>
          </MotionFade>
        )}

        <MotionFade delay={0.1}>
          <section
            id="today-next-action"
            aria-label="Your next action"
            data-slot="next-action"
          >
            <TodayNextAction />
          </section>
        </MotionFade>

        <MotionFade delay={0.12}>
          <section
            id="today-consistency"
            aria-label="Consistency this week"
            data-slot="consistency"
          >
            <TodayConsistency />
          </section>
        </MotionFade>

        <MotionFade delay={0.15}>
          <section
            id="today-review"
            aria-label="Spaced review"
            data-slot="review"
          >
            <TodayReview />
          </section>
        </MotionFade>

        <MotionFade delay={0.18}>
          <section
            id="today-teach-back"
            aria-label="Teach it back"
            data-slot="teach-back"
          >
            <TeachBackWidget />
          </section>
        </MotionFade>

        <MotionFade delay={0.19}>
          <section
            id="today-micro-wins"
            aria-label="Recent wins"
            data-slot="micro-wins"
          >
            <TodayMicroWins />
          </section>
        </MotionFade>

        {!isMorning && (
          <MotionFade delay={0.2}>
            <section
              id="today-reflection"
              aria-label="Daily reflection"
              data-slot="reflection"
            >
              <TodayReflection />
            </section>
          </MotionFade>
        )}

        <MotionFade delay={0.25}>
          <section
            id="today-signal"
            aria-label="Signal from reality"
            data-slot="signal"
          >
            <TodaySignal />
          </section>
        </MotionFade>
      </div>
    </PageShell>
  );
}
