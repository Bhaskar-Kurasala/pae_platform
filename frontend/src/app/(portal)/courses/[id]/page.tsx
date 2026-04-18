"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, BookOpen, Clock } from "lucide-react";
import { useCourse, useCourseLessons } from "@/lib/hooks/use-courses";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { LessonItem } from "@/components/features/lesson-item";
import { ProgressBar } from "@/components/features/progress-bar";
import { Badge } from "@/components/ui/badge";
import type { ProgressResponse } from "@/lib/api-client";

function completedSet(progress: ProgressResponse | undefined, courseId: string): Set<string> {
  const course = progress?.courses.find((c) => c.course_id === courseId);
  return new Set(
    course?.lessons.filter((l) => l.status === "completed").map((l) => l.id) ?? [],
  );
}

export default function CourseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: course, isLoading: courseLoading } = useCourse(id);
  const { data: lessons = [], isLoading: lessonsLoading } = useCourseLessons(id);
  const { data: progress } = useMyProgress();

  const done = completedSet(progress, id);
  const completedCount = lessons.filter((l) => done.has(l.id)).length;
  const progressPct = lessons.length > 0 ? (completedCount / lessons.length) * 100 : 0;

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
            {course.price_cents === 0 && (
              <Badge className="bg-primary/10 text-primary hover:bg-primary/10">Free</Badge>
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

        {/* Progress */}
        {completedCount > 0 && (
          <div className="rounded-xl border bg-card p-4">
            <p className="text-sm font-medium mb-2">
              {completedCount} of {lessons.length} lessons completed
            </p>
            <ProgressBar value={progressPct} />
          </div>
        )}

        {/* Lesson list */}
        <div className="rounded-xl border bg-card overflow-hidden">
          <div className="px-5 py-3 border-b bg-muted/40">
            <h2 className="font-semibold text-sm">Course Content</h2>
          </div>
          {lessons.length === 0 ? (
            <p className="px-5 py-8 text-center text-muted-foreground text-sm">
              No lessons published yet.
            </p>
          ) : (
            <div className="divide-y">
              {lessons.map((lesson) => (
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
