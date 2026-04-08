"use client";

import Link from "next/link";
import { ArrowRight, BookOpen, CheckCircle2, Clock } from "lucide-react";
import { useCourses } from "@/lib/hooks/use-courses";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { useAuthStore } from "@/stores/auth-store";
import { ProgressBar } from "@/components/features/progress-bar";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

function StatCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number | string;
  icon: React.ElementType;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 pt-6">
        <div className="rounded-lg bg-primary/10 p-3">
          <Icon className="h-5 w-5 text-primary" aria-hidden="true" />
        </div>
        <div>
          <p className="text-2xl font-bold">{value}</p>
          <p className="text-sm text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const { user } = useAuthStore();
  const { data: courses } = useCourses();
  const { data: progress } = useMyProgress();

  const completedLessons = progress?.filter((p) => p.status === "completed").length ?? 0;
  const enrolledCount = courses?.length ?? 0;

  return (
    <div className="p-6 md:p-8 max-w-5xl mx-auto space-y-8">
      {/* Greeting */}
      <div>
        <h1 className="text-2xl font-bold">
          Welcome back, {user?.full_name?.split(" ")[0] ?? "there"} 👋
        </h1>
        <p className="text-muted-foreground mt-1">Pick up where you left off.</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard label="Courses Enrolled" value={enrolledCount} icon={BookOpen} />
        <StatCard label="Lessons Completed" value={completedLessons} icon={CheckCircle2} />
        <StatCard
          label="Time Spent"
          value={`${Math.round((progress?.reduce((s, p) => s + p.watch_time_seconds, 0) ?? 0) / 60)}m`}
          icon={Clock}
        />
      </div>

      {/* Course progress */}
      {courses && courses.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-4">Your Courses</h2>
          <div className="space-y-3">
            {courses.slice(0, 5).map((course) => {
              const pct = 0; // Will compute once lesson→course mapping is added
              return (
                <Card key={course.id} className="hover:shadow-sm transition-shadow">
                  <CardHeader className="pb-2 pt-4 px-5">
                    <div className="flex items-center justify-between">
                      <h3 className="font-medium">{course.title}</h3>
                      <Link
                        href={`/courses/${course.id}`}
                        className="flex items-center gap-1 text-xs text-primary hover:underline"
                        aria-label={`Continue ${course.title}`}
                      >
                        Continue <ArrowRight className="h-3 w-3" aria-hidden="true" />
                      </Link>
                    </div>
                  </CardHeader>
                  <CardContent className="px-5 pb-4">
                    <ProgressBar value={pct} />
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      )}

      {/* Recent activity */}
      {progress && progress.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-4">Recent Activity</h2>
          <div className="space-y-2">
            {progress.slice(0, 5).map((p) => (
              <div
                key={p.id}
                className="flex items-center gap-3 rounded-lg border bg-card px-4 py-3"
              >
                <CheckCircle2 className="h-4 w-4 text-primary shrink-0" aria-hidden="true" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">Lesson completed</p>
                  <p className="text-xs text-muted-foreground">
                    {new Date(p.completed_at ?? p.created_at).toLocaleDateString()}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty CTA */}
      {(!courses || courses.length === 0) && (
        <div className="rounded-2xl border border-dashed bg-card p-12 text-center">
          <BookOpen className="h-10 w-10 text-muted-foreground mx-auto mb-4" aria-hidden="true" />
          <h2 className="text-lg font-semibold mb-2">No courses yet</h2>
          <p className="text-muted-foreground mb-6">Browse our catalogue and start learning today.</p>
          <Link
            href="/courses"
            className="inline-flex items-center gap-2 h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            Browse Courses <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>
      )}
    </div>
  );
}
