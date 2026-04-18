"use client";

import { use, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, CheckCircle2, Loader2 } from "lucide-react";
import { useLesson } from "@/lib/hooks/use-courses";
import { useMyProgress, useCompleteLesson } from "@/lib/hooks/use-progress";
import type { ProgressResponse } from "@/lib/api-client";

function isCompleted(lessonId: string, progress: ProgressResponse | undefined): boolean {
  return progress?.courses.some((c) =>
    c.lessons.some((l) => l.id === lessonId && l.status === "completed"),
  ) ?? false;
}

export default function LessonPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: lesson, isLoading } = useLesson(id);
  const { data: progress } = useMyProgress();
  const completeLesson = useCompleteLesson();
  const [completed, setCompleted] = useState(false);

  const alreadyDone = isCompleted(id, progress) || completed;

  async function handleComplete() {
    await completeLesson.mutateAsync(id);
    setCompleted(true);
  }

  if (isLoading) {
    return (
      <div className="p-8 max-w-3xl mx-auto space-y-4 animate-pulse">
        <div className="h-6 bg-muted rounded w-1/3" />
        <div className="aspect-video bg-muted rounded-xl" />
      </div>
    );
  }

  if (!lesson) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        Lesson not found.{" "}
        <Link href="/courses" className="text-primary hover:underline">
          Back to courses
        </Link>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-3xl mx-auto space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link href={`/courses/${lesson.course_id}`} className="hover:text-foreground inline-flex items-center gap-1">
          <ArrowLeft className="h-3 w-3" aria-hidden="true" /> Course
        </Link>
        <span>/</span>
        <span className="text-foreground font-medium truncate">{lesson.title}</span>
      </div>

      <h1 className="text-2xl font-bold">{lesson.title}</h1>

      {/* Video */}
      {lesson.youtube_video_id ? (
        <div className="aspect-video w-full rounded-xl overflow-hidden border shadow-sm">
          <iframe
            src={`https://www.youtube.com/embed/${lesson.youtube_video_id}`}
            title={lesson.title}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
            className="w-full h-full"
          />
        </div>
      ) : lesson.video_url ? (
        <div className="aspect-video w-full rounded-xl overflow-hidden border shadow-sm">
          <video src={lesson.video_url} controls className="w-full h-full object-cover" />
        </div>
      ) : (
        <div className="aspect-video w-full rounded-xl border bg-muted flex items-center justify-center text-muted-foreground text-sm">
          No video available
        </div>
      )}

      {/* Description */}
      {lesson.description && (
        <div>
          <h2 className="font-semibold mb-2">About this lesson</h2>
          <p className="text-muted-foreground text-sm leading-relaxed">{lesson.description}</p>
        </div>
      )}

      {/* Code viewer placeholder */}
      <div>
        <h2 className="font-semibold mb-2">Code</h2>
        <pre className="rounded-xl border bg-[#111827] text-green-400 p-5 text-sm overflow-x-auto font-mono">
          <code>{`# Lesson: ${lesson.title}
# Code examples will appear here as the lesson progresses.
# AI-powered code review is available via the AI Tutor.

print("Welcome to", "${lesson.title}")`}</code>
        </pre>
      </div>

      {/* Mark complete + navigation */}
      <div className="flex items-center justify-between pt-2">
        <Link
          href={`/courses/${lesson.course_id}`}
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back to course
        </Link>

        {alreadyDone ? (
          <div className="inline-flex items-center gap-2 text-sm font-medium text-primary">
            <CheckCircle2 className="h-5 w-5" aria-hidden="true" />
            Completed
          </div>
        ) : (
          <button
            onClick={handleComplete}
            disabled={completeLesson.isPending}
            className="inline-flex items-center gap-2 h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60 transition-colors"
          >
            {completeLesson.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            )}
            Mark as complete
          </button>
        )}
      </div>
    </div>
  );
}
