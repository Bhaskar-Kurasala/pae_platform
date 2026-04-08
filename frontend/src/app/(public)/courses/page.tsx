"use client";

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

export default function PublicCoursesPage() {
  const { data: courses, isLoading, isError } = useCourses();

  return (
    <div className="max-w-6xl mx-auto px-4 py-12">
      <div className="mb-10">
        <h1 className="text-3xl font-bold">Courses</h1>
        <p className="text-muted-foreground mt-2">
          Production-grade GenAI engineering courses built by practitioners.
        </p>
      </div>

      {isError && (
        <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive">
          Failed to load courses. Make sure the API server is running.
        </div>
      )}

      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {Array.from({ length: 6 }).map((_, i) => (
            <CourseSkeleton key={i} />
          ))}
        </div>
      )}

      {courses && courses.length === 0 && (
        <div className="text-center py-20 text-muted-foreground">
          No courses published yet. Check back soon!
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
