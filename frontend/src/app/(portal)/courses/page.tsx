"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { BookOpen, Search } from "lucide-react";
import { useCourses } from "@/lib/hooks/use-courses";
import { CourseCard } from "@/components/features/course-card";

type DifficultyFilter = "all" | "beginner" | "intermediate" | "advanced";
type PriceFilter = "all" | "free" | "paid";
type SortMode = "default" | "title-asc" | "hours-asc" | "hours-desc" | "price-asc" | "price-desc";

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
  const [search, setSearch] = useState("");
  const [difficulty, setDifficulty] = useState<DifficultyFilter>("all");
  const [price, setPrice] = useState<PriceFilter>("all");
  const [sort, setSort] = useState<SortMode>("default");

  const filtered = useMemo(() => {
    if (!courses) return [];
    const needle = search.trim().toLowerCase();
    const result = courses.filter((c) => {
      if (needle) {
        const hay = `${c.title} ${c.description ?? ""}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      if (difficulty !== "all" && c.difficulty !== difficulty) return false;
      if (price === "free" && c.price_cents > 0) return false;
      if (price === "paid" && c.price_cents === 0) return false;
      return true;
    });
    const sorted = result.slice();
    switch (sort) {
      case "title-asc":
        sorted.sort((a, b) => a.title.localeCompare(b.title));
        break;
      case "hours-asc":
        sorted.sort((a, b) => a.estimated_hours - b.estimated_hours);
        break;
      case "hours-desc":
        sorted.sort((a, b) => b.estimated_hours - a.estimated_hours);
        break;
      case "price-asc":
        sorted.sort((a, b) => a.price_cents - b.price_cents);
        break;
      case "price-desc":
        sorted.sort((a, b) => b.price_cents - a.price_cents);
        break;
    }
    return sorted;
  }, [courses, search, difficulty, price, sort]);

  const hasActiveFilter =
    search.trim() !== "" || difficulty !== "all" || price !== "all" || sort !== "default";

  return (
    <div className="p-6 md:p-8 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Courses</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Production-grade GenAI engineering courses built by practitioners.
        </p>
      </div>

      {/* Filter bar */}
      <div className="mb-6 rounded-xl border bg-card p-4 grid gap-3 md:grid-cols-[1fr_auto_auto_auto]">
        <div className="relative">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search courses…"
            aria-label="Search courses"
            className="w-full h-10 pl-9 pr-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
        </div>
        <select
          value={difficulty}
          onChange={(e) => setDifficulty(e.target.value as DifficultyFilter)}
          aria-label="Filter by difficulty"
          className="h-10 rounded-lg border bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="all">All levels</option>
          <option value="beginner">Beginner</option>
          <option value="intermediate">Intermediate</option>
          <option value="advanced">Advanced</option>
        </select>
        <select
          value={price}
          onChange={(e) => setPrice(e.target.value as PriceFilter)}
          aria-label="Filter by price"
          className="h-10 rounded-lg border bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="all">All prices</option>
          <option value="free">Free</option>
          <option value="paid">Paid</option>
        </select>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortMode)}
          aria-label="Sort courses"
          className="h-10 rounded-lg border bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="default">Default order</option>
          <option value="title-asc">Title A–Z</option>
          <option value="hours-asc">Shortest first</option>
          <option value="hours-desc">Longest first</option>
          <option value="price-asc">Price: low to high</option>
          <option value="price-desc">Price: high to low</option>
        </select>
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

      {!isLoading && courses && courses.length > 0 && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center rounded-xl border bg-card">
          <BookOpen className="h-10 w-10 text-muted-foreground/30 mb-3" aria-hidden="true" />
          <h2 className="font-semibold mb-1">No courses match your filters</h2>
          <p className="text-muted-foreground text-sm mb-4">
            Try clearing the search or switching filters.
          </p>
          {hasActiveFilter && (
            <button
              onClick={() => {
                setSearch("");
                setDifficulty("all");
                setPrice("all");
                setSort("default");
              }}
              className="inline-flex items-center gap-2 h-9 rounded-lg border bg-background px-4 text-sm font-medium hover:bg-muted transition-colors"
            >
              Clear filters
            </button>
          )}
        </div>
      )}

      {filtered.length > 0 && (
        <>
          <p className="text-xs text-muted-foreground mb-3" aria-live="polite">
            Showing {filtered.length} of {courses?.length ?? 0} courses
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {filtered.map((course) => (
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
        </>
      )}
    </div>
  );
}
