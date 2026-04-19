"use client";

import { use, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, BookOpen, Clock, Loader2 } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCourse, useCourseLessons } from "@/lib/hooks/use-courses";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { LessonItem } from "@/components/features/lesson-item";
import { ProgressBar } from "@/components/features/progress-bar";
import { Badge } from "@/components/ui/badge";
import {
  ApiError,
  coursesApi,
  type EnrollmentResponse,
  type ProgressResponse,
} from "@/lib/api-client";

function completedSet(progress: ProgressResponse | undefined, courseId: string): Set<string> {
  const course = progress?.courses.find((c) => c.course_id === courseId);
  return new Set(
    course?.lessons.filter((l) => l.status === "completed").map((l) => l.id) ?? [],
  );
}

function formatPrice(cents: number): string {
  return `$${(cents / 100).toFixed(cents % 100 === 0 ? 0 : 2)}`;
}

export default function CourseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const queryClient = useQueryClient();
  const { data: course, isLoading: courseLoading } = useCourse(id);
  const { data: lessons = [], isLoading: lessonsLoading } = useCourseLessons(id);
  const { data: progress } = useMyProgress();
  const { data: enrollment, refetch: refetchEnrollment } = useQuery<EnrollmentResponse | null>({
    queryKey: ["courses", id, "my-enrollment"],
    queryFn: () => coursesApi.myEnrollment(id),
    enabled: !!id,
  });

  const [enrolling, setEnrolling] = useState(false);
  const [enrollError, setEnrollError] = useState("");

  const done = completedSet(progress, id);
  const completedCount = lessons.filter((l) => done.has(l.id)).length;
  const progressPct = lessons.length > 0 ? (completedCount / lessons.length) * 100 : 0;
  const orderedLessons = lessons.slice().sort((a, b) => a.order - b.order);
  const firstIncomplete = orderedLessons.find((l) => !done.has(l.id));
  const continueLesson = firstIncomplete ?? orderedLessons[0];
  const isPaid = (course?.price_cents ?? 0) > 0;
  const isEnrolled = !!enrollment;
  const locked = isPaid && !isEnrolled;

  async function handleEnroll() {
    setEnrolling(true);
    setEnrollError("");
    try {
      await coursesApi.enroll(id);
      await refetchEnrollment();
      await queryClient.invalidateQueries({ queryKey: ["progress", "mine"] });
    } catch (err) {
      if (err instanceof ApiError) {
        setEnrollError(err.message);
      } else {
        setEnrollError("Could not enroll. Please try again.");
      }
    } finally {
      setEnrolling(false);
    }
  }

  if (courseLoading || lessonsLoading) {
    return (
      <div className="p-8 max-w-3xl mx-auto space-y-4 animate-pulse">
        <div className="h-6 bg-muted rounded w-1/2" />
        <div className="h-4 bg-muted rounded w-full" />
        <div className="h-4 bg-muted rounded w-3/4" />
      </div>
    );
  }

  if (!course) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        Course not found.{" "}
        <Link href="/courses" className="text-primary hover:underline">
          Back to courses
        </Link>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-3xl mx-auto">
      <Link
        href="/courses"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-6"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back to courses
      </Link>

      <div className="space-y-6">
        {/* Header */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Badge variant="secondary">{course.difficulty}</Badge>
            {course.price_cents === 0 ? (
              <Badge className="bg-primary/10 text-primary hover:bg-primary/10">Free</Badge>
            ) : (
              <Badge className="bg-secondary/20 text-secondary">
                {formatPrice(course.price_cents)}
              </Badge>
            )}
            {isEnrolled && (
              <Badge className="bg-primary text-primary-foreground">Enrolled</Badge>
            )}
          </div>
          <h1 className="text-3xl font-bold">{course.title}</h1>
          {course.description && (
            <p className="text-muted-foreground mt-3">{course.description}</p>
          )}
          <div className="flex items-center gap-4 mt-4 text-sm text-muted-foreground">
            <span className="flex items-center gap-1">
              <BookOpen className="h-4 w-4" aria-hidden="true" />
              {lessons.length} lessons
            </span>
            <span className="flex items-center gap-1">
              <Clock className="h-4 w-4" aria-hidden="true" />
              {course.estimated_hours}h estimated
            </span>
          </div>
        </div>

        {/* CTA: Enroll (not yet enrolled) OR Continue learning (enrolled) */}
        {!isEnrolled ? (
          <div className="rounded-xl border bg-card p-5 space-y-3">
            <div>
              <p className="font-semibold">
                {isPaid
                  ? `Enroll for ${formatPrice(course.price_cents)} to unlock all lessons`
                  : "Start this course"}
              </p>
              <p className="text-sm text-muted-foreground">
                {isPaid
                  ? "One-time purchase — lifetime access."
                  : "Free — you can start right away."}
              </p>
            </div>
            {enrollError && (
              <p className="text-sm text-destructive" role="alert">
                {enrollError}
              </p>
            )}
            <button
              onClick={handleEnroll}
              disabled={enrolling}
              className="inline-flex items-center gap-2 h-10 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60 transition-colors"
              aria-label={isPaid ? `Enroll for ${formatPrice(course.price_cents)}` : "Start free course"}
            >
              {enrolling ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              )}
              {enrolling
                ? "Enrolling…"
                : isPaid
                  ? `Enroll for ${formatPrice(course.price_cents)}`
                  : "Start course"}
            </button>
          </div>
        ) : continueLesson ? (
          <div className="rounded-xl border bg-card p-5 space-y-3">
            <div>
              <p className="text-sm font-medium">
                {completedCount > 0
                  ? `${completedCount} of ${lessons.length} lessons completed`
                  : "Ready to begin"}
              </p>
              {completedCount > 0 && <ProgressBar value={progressPct} />}
            </div>
            <Link
              href={`/lessons/${continueLesson.id}`}
              className="inline-flex items-center gap-2 h-10 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
              {completedCount > 0 ? "Continue" : "Start"} with{" "}
              <span className="truncate max-w-[16rem]">{continueLesson.title}</span>
            </Link>
          </div>
        ) : null}

        {/* Lesson list */}
        <div className="rounded-xl border bg-card overflow-hidden">
          <div className="px-5 py-3 border-b bg-muted/40">
            <h2 className="font-semibold text-sm">Course Content</h2>
          </div>
          {lessons.length === 0 ? (
            <p className="px-5 py-8 text-center text-muted-foreground text-sm">
              No lessons published yet.
            </p>
          ) : locked ? (
            <p className="px-5 py-8 text-center text-sm text-muted-foreground">
              Enroll above to unlock {lessons.length} lessons.
            </p>
          ) : (
            <div className="divide-y">
              {orderedLessons.map((lesson) => (
                <LessonItem
                  key={lesson.id}
                  id={lesson.id}
                  title={lesson.title}
                  durationSeconds={lesson.duration_seconds}
                  order={lesson.order}
                  isCompleted={done.has(lesson.id)}
                  isFreePreview={lesson.is_free_preview}
                  isPortal
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
