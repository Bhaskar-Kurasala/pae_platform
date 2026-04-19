"use client";

import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  Bot,
  CalendarCheck,
  CheckCircle2,
  Clock,
  MessageSquare,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useCourses } from "@/lib/hooks/use-courses";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { useMySkillStates } from "@/lib/hooks/use-skills";
import { useAuthStore } from "@/stores/auth-store";
import { activeDaySet, computeStreak } from "@/lib/streak";
import { api, type CourseResponse } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { PageShell } from "@/components/layouts/page-shell";
import { PageHeader } from "@/components/layouts/page-header";

// ── Types ────────────────────────────────────────────────────────
interface AdminStats {
  total_students: number;
  total_agent_actions: number;
  mrr_usd: number;
  total_enrollments: number;
  total_submissions: number;
}

// ── Skeleton building block ──────────────────────────────────────
function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-xl bg-muted", className)}
      aria-hidden="true"
    />
  );
}

// ── KPI Card ─────────────────────────────────────────────────────
function KpiCard({
  label,
  value,
  sub,
  icon: Icon,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ElementType;
  accent: string;
}) {
  return (
    <div className="rounded-xl ring-1 ring-foreground/10 bg-card p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between">
        <div className={cn("rounded-lg p-2.5", accent)}>
          <Icon className="h-4 w-4" aria-hidden="true" />
        </div>
      </div>
      <div>
        <p className="text-2xl font-bold leading-none">{value}</p>
        <p className="text-sm text-muted-foreground mt-1">{label}</p>
        {sub && (
          <p className="text-xs text-primary mt-1 font-medium">{sub}</p>
        )}
      </div>
    </div>
  );
}

// ── Mini progress bar ────────────────────────────────────────────
function MiniProgress({ value }: { value: number }) {
  return (
    <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden" aria-hidden="true">
      <div
        className="h-full rounded-full bg-primary transition-all duration-500"
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );
}

// ── Course Card ──────────────────────────────────────────────────
function CourseCard({ course, progress }: { course: CourseResponse; progress: number }) {
  const difficultyColor: Record<string, string> = {
    beginner: "bg-muted text-muted-foreground",
    intermediate: "bg-muted text-foreground/80",
    advanced: "bg-primary/10 text-primary",
  };
  const badgeClass = difficultyColor[course.difficulty] ?? "bg-muted text-muted-foreground";

  return (
    <div className="rounded-xl ring-1 ring-foreground/10 bg-card p-5 flex flex-col gap-4 hover:ring-foreground/20 hover:shadow-[var(--elevation-2)] transition-[box-shadow,--tw-ring-color] duration-base ease-out-quad">
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold leading-snug line-clamp-2">{course.title}</h3>
        <span className={cn("shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize", badgeClass)}>
          {course.difficulty}
        </span>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{progress}% complete</span>
          <span>{course.estimated_hours}h total</span>
        </div>
        <MiniProgress value={progress} />
      </div>

      <Link
        href={`/courses/${course.id}`}
        aria-label={`Continue ${course.title}`}
        className="flex items-center gap-1.5 text-sm font-medium text-primary hover:text-primary/80 transition-colors"
      >
        Continue <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
      </Link>
    </div>
  );
}

// ── Agent Quick-Access ────────────────────────────────────────────
const QUICK_AGENTS = [
  { name: "socratic_tutor", label: "Socratic Tutor", color: "bg-primary/10 text-primary", hint: "Guided Q&A" },
  { name: "code_review", label: "Code Review", color: "bg-muted text-foreground", hint: "Production readiness" },
  { name: "adaptive_quiz", label: "Adaptive Quiz", color: "bg-muted text-foreground", hint: "Test your knowledge" },
  { name: "mock_interview", label: "Mock Interview", color: "bg-muted text-foreground", hint: "FAANG prep" },
  { name: "progress_report", label: "Progress Report", color: "bg-muted text-foreground", hint: "Weekly summary" },
];

function AgentShortcuts() {
  return (
    <div className="rounded-xl ring-1 ring-foreground/10 bg-card overflow-hidden">
      <div className="px-5 py-4 border-b">
        <h2 className="font-semibold text-sm">Quick Agents</h2>
      </div>
      <div className="divide-y">
        {QUICK_AGENTS.map((agent) => (
          <Link
            key={agent.name}
            href={`/chat?agent=${agent.name}`}
            aria-label={`Open ${agent.label} agent`}
            className="flex items-center gap-3 px-5 py-3 hover:bg-muted/50 transition-colors"
          >
            <div className={cn("rounded-lg p-2 shrink-0", agent.color)}>
              <Bot className="h-3.5 w-3.5" aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium leading-none">{agent.label}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{agent.hint}</p>
            </div>
            <ArrowRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" aria-hidden="true" />
          </Link>
        ))}
      </div>
    </div>
  );
}

// ── Timeline Activity Item ────────────────────────────────────────
function ActivityItem({
  icon: Icon,
  label,
  sub,
  accent,
}: {
  icon: React.ElementType;
  label: string;
  sub: string;
  accent: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className={cn("mt-0.5 rounded-full p-1.5 shrink-0", accent)}>
        <Icon className="h-3 w-3" aria-hidden="true" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{label}</p>
        <p className="text-xs text-muted-foreground">{sub}</p>
      </div>
    </div>
  );
}

// ── Greeting helpers ─────────────────────────────────────────────
function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

// ── Page Component ───────────────────────────────────────────────
export default function DashboardPage() {
  const { user } = useAuthStore();

  const { data: courses, isLoading: coursesLoading } = useCourses();
  const { data: progressData, isLoading: progressLoading } = useMyProgress();
  const { data: skillStates } = useMySkillStates();
  const { data: stats } = useQuery<AdminStats>({
    queryKey: ["admin", "stats"],
    queryFn: () => api.get<AdminStats>("/api/v1/admin/stats"),
    staleTime: 30_000,
    retry: false,
    enabled: user?.role === "admin",
  });

  const isLoading = coursesLoading || progressLoading;

  // Derived stats from nested progress shape
  const allLessons = progressData?.courses.flatMap((c) => c.lessons) ?? [];
  const completedLessons = allLessons.filter((l) => l.status === "completed").length;
  const courseCount = progressData?.courses.length ?? 0;
  const overallProgress = Math.round(progressData?.overall_progress ?? 0);

  const skillsTouched = (skillStates ?? []).filter((s) => s.last_touched_at !== null).length;
  const streakDays = computeStreak(
    activeDaySet((skillStates ?? []).map((s) => s.last_touched_at)),
  );

  // Recent completed courses (as activity proxy)
  const recentActivity = (progressData?.courses ?? [])
    .filter((c) => c.completed_lessons > 0)
    .slice(0, 5);

  const today = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  return (
    <PageShell variant="wide" className="space-y-8">
      <PageHeader
        title={`${greeting()}, ${user?.full_name?.split(" ")[0] ?? "there"}`}
        description={today}
      />

      {/* KPI row */}
      {isLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard
            label="Lessons Completed"
            value={completedLessons}
            sub={completedLessons > 0 ? `+${Math.min(completedLessons, 3)} this week` : undefined}
            icon={CheckCircle2}
            accent="bg-primary/10 text-primary"
          />
          <KpiCard
            label="Skills Touched"
            value={skillsTouched}
            sub={skillsTouched > 0 ? "Growth in motion" : "Explore the skill map"}
            icon={Sparkles}
            accent="bg-muted text-foreground"
          />
          <KpiCard
            label="Consistency"
            value={`${streakDays}d`}
            sub={streakDays > 0 ? "Days active in a row" : "Any activity today starts the count"}
            icon={CalendarCheck}
            accent="bg-muted text-foreground"
          />
          <KpiCard
            label="Course Progress"
            value={`${overallProgress}%`}
            sub={`${courseCount} course${courseCount !== 1 ? "s" : ""} enrolled`}
            icon={TrendingUp}
            accent="bg-muted text-foreground"
          />
        </div>
      )}

      {/* Content grid: courses + sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-8">
        <div className="space-y-8">
          {/* Active courses */}
          <section aria-labelledby="courses-heading">
            <div className="flex items-center justify-between mb-4">
              <h2 id="courses-heading" className="font-semibold text-base">
                Active Courses
              </h2>
              <Link
                href="/courses"
                aria-label="Browse all courses"
                className="text-sm text-primary hover:text-primary/80 flex items-center gap-1 transition-colors"
              >
                Browse all <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            </div>

            {isLoading ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Skeleton className="h-40" />
                <Skeleton className="h-40" />
              </div>
            ) : courses && courses.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {courses.slice(0, 4).map((course) => (
                  <CourseCard key={course.id} course={course} progress={overallProgress} />
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed bg-card p-10 text-center">
                <BookOpen
                  className="h-9 w-9 text-muted-foreground mx-auto mb-3"
                  aria-hidden="true"
                />
                <h3 className="font-semibold mb-1">No courses yet</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  Browse our catalogue and start learning today.
                </p>
                <Link
                  href="/courses"
                  className="inline-flex items-center gap-2 h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                >
                  Browse Courses <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Link>
              </div>
            )}
          </section>

          {/* Recent activity */}
          <section aria-labelledby="activity-heading">
            <h2 id="activity-heading" className="font-semibold text-base mb-4">
              Recent Activity
            </h2>
            {isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-12" />
                ))}
              </div>
            ) : recentActivity.length > 0 ? (
              <div className="rounded-xl ring-1 ring-foreground/10 bg-card divide-y overflow-hidden">
                {recentActivity.map((c) => (
                  <div key={c.course_id} className="px-5 py-3.5">
                    <ActivityItem
                      icon={CheckCircle2}
                      label={c.course_title}
                      sub={`${c.completed_lessons} of ${c.total_lessons} lessons completed`}
                      accent="bg-primary/10 text-primary"
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed bg-card p-8 text-center text-sm text-muted-foreground">
                <Clock className="h-8 w-8 mx-auto mb-2 opacity-30" aria-hidden="true" />
                <p>Complete your first lesson to see activity here.</p>
              </div>
            )}
          </section>

          {/* Quick actions */}
          <section aria-labelledby="actions-heading">
            <h2 id="actions-heading" className="font-semibold text-base mb-4">
              Quick Actions
            </h2>
            <div className="flex flex-wrap gap-3">
              {courses && courses.length > 0 && (
                <Link
                  href={`/courses/${courses[0].id}`}
                  aria-label="Continue learning your most recent course"
                  className="flex items-center gap-2 h-10 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
                >
                  <BookOpen className="h-4 w-4" aria-hidden="true" />
                  Continue Learning
                </Link>
              )}
              <Link
                href="/chat"
                aria-label="Open AI agent chat"
                className="flex items-center gap-2 h-10 rounded-lg border border-border px-5 text-sm font-medium hover:bg-muted transition-colors"
              >
                <MessageSquare className="h-4 w-4" aria-hidden="true" />
                Ask an Agent
              </Link>
              <Link
                href="/chat?agent=adaptive_quiz"
                aria-label="Start a practice quiz"
                className="flex items-center gap-2 h-10 rounded-lg border border-border px-5 text-sm font-medium hover:bg-muted transition-colors"
              >
                <Zap className="h-4 w-4" aria-hidden="true" />
                Practice Quiz
              </Link>
            </div>
          </section>
        </div>

        {/* Right sidebar: agent shortcuts */}
        <aside className="hidden lg:block" aria-label="Agent shortcuts">
          <AgentShortcuts />
        </aside>
      </div>
    </PageShell>
  );
}
