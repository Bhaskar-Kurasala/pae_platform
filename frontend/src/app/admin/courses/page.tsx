"use client";

/**
 * /admin/courses — catalog list.
 *
 * The first list page that's existed for course management — until
 * now `/admin/courses/[id]/edit` was reachable only via deep link
 * from the cockpit. Surfacing it as a navigable page closes a real
 * gap in the admin section.
 *
 * Renders a simple table: title, slug, difficulty, price, lessons,
 * publish state, last-updated. Click any row to land on the edit
 * route. Status pills mirror the cockpit aesthetic (mint for
 * published, muted for draft).
 */

import Link from "next/link";
import {
  ArrowUpRight,
  CheckCircle2,
  CircleDashed,
  GraduationCap,
} from "lucide-react";
import { useCourses } from "@/lib/hooks/use-courses";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

function formatPrice(priceCents: number): string {
  if (priceCents === 0) return "Free";
  return `$${(priceCents / 100).toFixed(0)}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function AdminCoursesPage() {
  const { data: courses = [], isLoading, isError, error } = useCourses();

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6 md:p-8">
      <header className="flex flex-col gap-2">
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <GraduationCap className="h-5 w-5 text-primary" aria-hidden="true" />
          Courses
        </h1>
        <p className="text-sm text-muted-foreground max-w-2xl">
          The full catalog. Click any course to edit lessons, exercises,
          pricing, and publish state.
        </p>
      </header>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-16 w-full animate-pulse rounded-xl bg-muted"
            />
          ))}
        </div>
      ) : isError ? (
        <Card>
          <CardContent className="py-6 text-sm text-destructive">
            Failed to load courses:{" "}
            {(error as Error)?.message ?? "unknown error"}
          </CardContent>
        </Card>
      ) : courses.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
            <GraduationCap
              className="h-8 w-8 text-muted-foreground"
              aria-hidden="true"
            />
            <div className="font-medium">No courses yet</div>
            <p className="max-w-md text-sm text-muted-foreground">
              The catalog is empty. Create your first course to start
              onboarding students.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm" aria-label="Courses">
            <thead>
              <tr className="border-b bg-muted/40 text-left">
                <th className="px-4 py-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Title
                </th>
                <th className="px-4 py-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Status
                </th>
                <th className="px-4 py-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Difficulty
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Price
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Hours
                </th>
                <th className="px-4 py-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Updated
                </th>
                <th className="w-12 px-4 py-3" aria-label="Edit" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {courses.map((course) => (
                <tr
                  key={course.id}
                  className="transition hover:bg-muted/20"
                >
                  <td className="px-4 py-3">
                    <Link
                      href={`/admin/courses/${course.id}/edit`}
                      className="block group"
                    >
                      <span className="font-medium text-foreground group-hover:text-primary transition">
                        {course.title}
                      </span>
                      <span className="block text-xs text-muted-foreground font-mono">
                        {course.slug}
                      </span>
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium uppercase tracking-wider",
                        course.is_published
                          ? "bg-primary/10 text-primary"
                          : "bg-muted text-muted-foreground",
                      )}
                    >
                      {course.is_published ? (
                        <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                      ) : (
                        <CircleDashed className="h-3 w-3" aria-hidden="true" />
                      )}
                      {course.is_published ? "Published" : "Draft"}
                    </span>
                  </td>
                  <td className="px-4 py-3 capitalize text-muted-foreground">
                    {course.difficulty}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">
                    {formatPrice(course.price_cents)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-muted-foreground">
                    {course.estimated_hours}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground font-mono tabular-nums text-xs">
                    {formatDate(course.updated_at)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      href={`/admin/courses/${course.id}/edit`}
                      aria-label={`Edit ${course.title}`}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
                    >
                      <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
