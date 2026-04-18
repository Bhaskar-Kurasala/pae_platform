"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { MotionFade } from "@/components/ui/motion-fade";
import { TodayGoalBanner } from "@/components/features/today-goal-banner";
import { TodayIntention } from "@/components/features/today-intention";
import { TodayNextAction } from "@/components/features/today-next-action";
import { TodayReflection } from "@/components/features/today-reflection";
import { TodayReview } from "@/components/features/today-review";
import { TodaySignal } from "@/components/features/today-signal";
import { TeachBackWidget } from "@/components/features/teach-back-widget";
import { useMyGoal } from "@/lib/hooks/use-goal";
import { useAuthStore } from "@/stores/auth-store";

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export default function TodayPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { data: goal, isLoading, isError } = useMyGoal();

  useEffect(() => {
    if (!isLoading && !isError && goal === null) {
      router.replace("/onboarding");
    }
  }, [goal, isLoading, isError, router]);

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

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-10 md:py-14">
      <MotionFade>
        <header className="mb-8">
          <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
            Today · {today}
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">
            {greeting()}, {firstName}.
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
        <MotionFade delay={0.08}>
          <section
            id="today-intention"
            aria-label="Today's intention"
            data-slot="intention"
          >
            <TodayIntention />
          </section>
        </MotionFade>
        <MotionFade delay={0.1}>
          <section
            id="today-next-action"
            aria-label="Your next action"
            data-slot="next-action"
          >
            <TodayNextAction />
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
        <MotionFade delay={0.2}>
          <section
            id="today-reflection"
            aria-label="Daily reflection"
            data-slot="reflection"
          >
            <TodayReflection />
          </section>
        </MotionFade>
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
    </div>
  );
}
