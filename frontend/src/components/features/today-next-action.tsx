"use client";

import Link from "next/link";
import { ArrowRight, Compass, PlayCircle, Sparkles } from "lucide-react";
import { useCourses } from "@/lib/hooks/use-courses";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { cn } from "@/lib/utils";

type Action = {
  kind: "resume-lesson" | "start-course" | "browse";
  title: string;
  subtitle: string;
  href: string;
  cta: string;
  icon: React.ElementType;
};

function resolveAction(
  progress: ReturnType<typeof useMyProgress>["data"],
  courses: ReturnType<typeof useCourses>["data"],
): Action {
  // 1. Active enrollment with an in-progress course → resume next lesson
  const inProgress = progress?.courses.find(
    (c) => c.completed_lessons > 0 && c.next_lesson_id,
  );
  if (inProgress?.next_lesson_id) {
    return {
      kind: "resume-lesson",
      title: inProgress.next_lesson_title ?? "Continue where you left off",
      subtitle: `${inProgress.course_title} · ${inProgress.completed_lessons}/${inProgress.total_lessons} lessons done`,
      href: `/lessons/${inProgress.next_lesson_id}`,
      cta: "Resume",
      icon: PlayCircle,
    };
  }

  // 2. Enrolled but not started yet → first lesson of first enrolled course
  const notStarted = progress?.courses.find(
    (c) => c.completed_lessons === 0 && c.next_lesson_id,
  );
  if (notStarted?.next_lesson_id) {
    return {
      kind: "start-course",
      title: notStarted.next_lesson_title ?? "Your first lesson",
      subtitle: `${notStarted.course_title} · start here`,
      href: `/lessons/${notStarted.next_lesson_id}`,
      cta: "Start now",
      icon: Sparkles,
    };
  }

  // 3. No enrollments → direct them to a course
  const firstCourse = courses?.[0];
  if (firstCourse) {
    return {
      kind: "browse",
      title: firstCourse.title,
      subtitle: "Pick your first course — most students start here.",
      href: `/courses/${firstCourse.id}`,
      cta: "Explore",
      icon: Compass,
    };
  }

  // 4. Ultimate fallback
  return {
    kind: "browse",
    title: "Browse the catalogue",
    subtitle: "We're still stocking courses. Check back soon.",
    href: "/courses",
    cta: "Browse",
    icon: Compass,
  };
}

export function TodayNextAction() {
  const { data: progress, isLoading: progressLoading } = useMyProgress();
  const { data: courses, isLoading: coursesLoading } = useCourses();

  if (progressLoading || coursesLoading) {
    return (
      <div
        className="rounded-2xl border border-foreground/10 bg-card p-5 md:p-6"
        aria-busy="true"
      >
        <div className="h-3 w-20 rounded bg-foreground/[0.06] animate-pulse" />
        <div className="mt-3 h-5 w-2/3 rounded bg-foreground/[0.06] animate-pulse" />
        <div className="mt-2 h-4 w-1/2 rounded bg-foreground/[0.06] animate-pulse" />
        <div className="mt-5 h-9 w-28 rounded-lg bg-foreground/[0.06] animate-pulse" />
      </div>
    );
  }

  const action = resolveAction(progress, courses);
  const Icon = action.icon;

  return (
    <article
      aria-labelledby="next-action-heading"
      className="group relative overflow-hidden rounded-2xl border border-primary/20 bg-gradient-to-br from-card to-primary/[0.03] p-5 md:p-6 shadow-sm transition-all hover:border-foreground/20"
    >
      {/* Accent glow */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-16 -top-16 h-40 w-40 rounded-full bg-primary/20 blur-3xl opacity-0 group-hover:opacity-60 transition-opacity duration-500"
      />

      <div className="relative flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <div className="mt-0.5 rounded-xl bg-primary/15 p-3 text-primary shrink-0">
            <Icon className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
              Up next
            </p>
            <h2
              id="next-action-heading"
              className="mt-1.5 text-lg font-semibold leading-snug line-clamp-2"
            >
              {action.title}
            </h2>
            <p className="mt-1.5 text-sm text-muted-foreground line-clamp-2">
              {action.subtitle}
            </p>
            {action.kind === "resume-lesson" && (
              <p className="mt-2 text-xs text-muted-foreground/70">
                Pick up where you left off
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="relative mt-5">
        <Link
          href={action.href}
          aria-label={action.cta}
          className="inline-flex items-center gap-2 h-10 rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90 active:translate-y-px focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {action.cta}
          <ArrowRight
            className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5"
            aria-hidden="true"
          />
        </Link>
      </div>
    </article>
  );
}
