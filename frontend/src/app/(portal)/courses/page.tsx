"use client";

import Link from "next/link";
import { BookOpen } from "lucide-react";
import { useCourses } from "@/lib/hooks/use-courses";
import { CourseCard } from "@/components/features/course-card";

function CourseSkeleton() {
  return (
    <div className="rounded-xl border bg-card p-5 animate-pulse space-y-3">
      <div className="h-4 bg-muted rounded w-3/4" />
      <div className="h-3 bg-muted rounded w-1/3" />
      <div className="h-3 bg-muted rounded w-full" />
      <div className="h-3 bg-muted rounded w-2/3" />
    </div>
  );
}

export default function PortalCoursesPage() {
  const { data: courses, isLoading, isError } = useCourses();

  return (
    <div className="p-6 md:p-8 max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Courses</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Production-grade GenAI engineering courses built by practitioners.
        </p>
      </div>

      {isError && (
        <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive mb-6">
          Failed to load courses. Please try refreshing.
        </div>
      )}

      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {Array.from({ length: 6 }).map((_, i) => (
            <CourseSkeleton key={i} />
          ))}
        </div>
      )}

      {!isLoading && courses && courses.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <BookOpen className="h-12 w-12 text-muted-foreground/30 mb-4" aria-hidden="true" />
          <h2 className="font-semibold text-lg mb-1">No courses published yet</h2>
          <p className="text-muted-foreground text-sm mb-6">
            Check back soon — new courses are on the way.
          </p>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            Back to dashboard
          </Link>
        </div>
      )}

      {courses && courses.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {courses.map((course) => (
            <CourseCard
              key={course.id}
              id={course.id}
              title={course.title}
              description={course.description}
              difficulty={course.difficulty}
              estimatedHours={course.estimated_hours}
              priceCents={course.price_cents}
            />
          ))}
        </div>
      )}
    </div>
  );
}
