"use client";

/**
 * LearnScreen — course picker for the lesson player.
 *
 * Lists every course the student is entitled to. Clicking into a course
 * navigates to /learn/[courseId] (the timeline + player).
 *
 * Mirrors the v8 pattern used by catalog-screen: a `.screen.active`
 * section wrapping a `.pad` content rail. Without those classes the
 * portal layout's CSS keeps screens collapsed (display: none).
 */

import { useMemo } from "react";
import Link from "next/link";
import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { useCatalog } from "@/lib/hooks/use-catalog";

export function LearnScreen() {
  useSetV8Topbar({
    eyebrow: "Course path",
    titleHtml: "Pick up where you <i>left off</i>",
    chips: [{ label: "Self-paced", variant: "forest" }],
    progress: 0,
  });

  const { data: catalog, isLoading, error } = useCatalog();

  const unlockedCourses = useMemo(() => {
    if (!catalog) return [];
    return catalog.courses.filter((c) => c.is_unlocked);
  }, [catalog]);

  return (
    <section className="screen active" id="screen-learn">
      <div className="pad">
        {isLoading ? (
          <SkeletonGrid />
        ) : error ? (
          <div role="alert" className="note" style={{ borderColor: "var(--rose)" }}>
            <div className="eyebrow">Something went wrong</div>
            <p>We couldn’t load your courses. Try refreshing.</p>
          </div>
        ) : unlockedCourses.length === 0 ? (
          <article className="note reveal">
            <div className="eyebrow">No courses yet</div>
            <h2 style={{ fontFamily: "var(--font-fraunces)", marginTop: 6 }}>
              Unlock a track to begin
            </h2>
            <p style={{ marginTop: 8, opacity: 0.8 }}>
              Visit the Catalog to pick a course. Each course unlocks lessons
              one by one — read, run a notebook, watch the explainer, mark it
              complete, and the next lesson opens.
            </p>
            <Link
              href="/catalog"
              className="btn primary"
              style={{ marginTop: 16, display: "inline-block" }}
            >
              Browse catalog →
            </Link>
          </article>
        ) : (
          <>
            <header style={{ marginBottom: 18 }}>
              <div className="eyebrow">Your courses</div>
              <h2
                style={{
                  fontFamily: "var(--font-fraunces)",
                  margin: "4px 0",
                }}
              >
                {unlockedCourses.length} course
                {unlockedCourses.length === 1 ? "" : "s"} unlocked
              </h2>
            </header>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                gap: 18,
              }}
            >
              {unlockedCourses.map((course) => (
                <Link
                  key={course.id}
                  href={`/learn/${course.id}`}
                  className="card"
                  style={{
                    padding: 18,
                    borderRadius: 14,
                    border: "1px solid var(--line)",
                    background: "var(--surface)",
                    textDecoration: "none",
                    color: "inherit",
                    display: "flex",
                    flexDirection: "column",
                    gap: 10,
                    minHeight: 180,
                    transition:
                      "transform 120ms ease, border-color 120ms ease",
                  }}
                >
                  <div className="eyebrow">{course.difficulty}</div>
                  <h3
                    style={{
                      fontFamily: "var(--font-fraunces)",
                      fontSize: 20,
                      fontWeight: 600,
                      margin: 0,
                    }}
                  >
                    {course.title}
                  </h3>
                  {course.description && (
                    <p style={{ opacity: 0.75, fontSize: 14, margin: 0 }}>
                      {course.description.length > 130
                        ? `${course.description.slice(0, 129).trimEnd()}…`
                        : course.description}
                    </p>
                  )}
                  <div
                    style={{
                      marginTop: "auto",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      color: "var(--forest)",
                      fontWeight: 600,
                      fontSize: 13,
                    }}
                  >
                    <span>Continue learning →</span>
                    <span style={{ opacity: 0.6, fontWeight: 400 }}>
                      {(course.bullets ?? []).length} modules
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function SkeletonGrid() {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
        gap: 18,
      }}
    >
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          style={{
            height: 180,
            borderRadius: 14,
            background: "var(--ink-7)",
            opacity: 0.45,
          }}
        />
      ))}
    </div>
  );
}
