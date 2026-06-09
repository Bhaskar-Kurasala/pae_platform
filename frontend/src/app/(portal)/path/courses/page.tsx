"use client";

/**
 * /path/courses — overview of every enrolled course.
 *
 * Restores the "show me everything I'm working on" surface that the
 * deleted /learn screen used to provide. Lives under My Path so the
 * merge stays intact. The active-course band on /path links here.
 *
 * Data source: useActiveCourse() (returns enrolled_courses derived
 * from student_asset_progress rows). Free catalog browse access does
 * NOT count as enrollment by design — only courses the student has
 * actually started.
 */

import Link from "next/link";
import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { useActiveCourse } from "@/lib/hooks/use-learn";

export default function MyCoursesPage() {
  useSetV8Topbar({
    eyebrow: "Course path",
    titleHtml: "My <i>courses</i>",
    chips: [],
    progress: 0,
  });

  const { data, isLoading, error } = useActiveCourse();
  const courses = data?.enrolled_courses ?? [];
  const isAdmin = data?.viewer_role === "admin";

  return (
    <section className="screen active" id="screen-my-courses">
      <div className="pad">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <Link
            href="/path"
            className="text-sm font-semibold"
            style={{ color: "var(--forest)", textDecoration: "none" }}
          >
            ← Back to your path
          </Link>
          <Link
            href="/catalog"
            className="btn"
            style={{ padding: "8px 14px", borderRadius: 8 }}
          >
            Browse catalog →
          </Link>
        </div>

        {isLoading ? (
          <SkeletonGrid />
        ) : error ? (
          <div role="alert" className="note" style={{ borderColor: "var(--rose)" }}>
            <div className="eyebrow">Couldn’t load your courses</div>
            <p>Try refreshing.</p>
          </div>
        ) : courses.length === 0 ? (
          <article className="note reveal">
            <div className="eyebrow">
              {isAdmin ? "Admin view" : "Nothing started yet"}
            </div>
            <h2 style={{ fontFamily: "var(--font-fraunces)", marginTop: 6 }}>
              {isAdmin
                ? "Open the catalog to inspect any course"
                : "Pick a course to begin"}
            </h2>
            <p style={{ marginTop: 8, opacity: 0.8 }}>
              {isAdmin
                ? "Admins start with full access to every published course; the catalog is your launchpad. To see a student's course list, use the admin console and click “View as student” on their profile."
                : "Open any course in the catalog and click “Open course” to start. Lessons will unlock one by one as you progress."}
            </p>
            <Link
              href="/catalog"
              className="btn primary"
              style={{ marginTop: 16, display: "inline-block" }}
            >
              Browse the catalog →
            </Link>
          </article>
        ) : (
          <>
            <header style={{ marginBottom: 18 }}>
              <div className="eyebrow">
                {courses.length} course{courses.length === 1 ? "" : "s"} in
                progress
              </div>
              <h2 style={{ fontFamily: "var(--font-fraunces)", margin: "4px 0" }}>
                Pick up where you left off
              </h2>
            </header>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                gap: 18,
              }}
            >
              {courses.map((c) => (
                <Link
                  key={c.course_id}
                  href={`/path/${c.course_id}`}
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
                    minHeight: 160,
                  }}
                >
                  <div className="eyebrow">
                    {c.completed_lessons} / {c.total_lessons} lessons
                  </div>
                  <h3
                    style={{
                      fontFamily: "var(--font-fraunces)",
                      fontSize: 19,
                      fontWeight: 600,
                      margin: 0,
                    }}
                  >
                    {c.course_title}
                  </h3>
                  <div
                    style={{
                      marginTop: "auto",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      fontSize: 13,
                    }}
                  >
                    <ProgressBar pct={c.progress_pct} />
                    <span style={{ color: "var(--forest)", fontWeight: 600 }}>
                      Continue →
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

function ProgressBar({ pct }: { pct: number }) {
  const percent = Math.round(pct * 100);
  return (
    <div
      style={{
        width: 100,
        height: 6,
        background: "var(--ink-7)",
        borderRadius: 999,
        overflow: "hidden",
      }}
    >
      <div
        aria-label={`${percent}% complete`}
        style={{
          width: `${percent}%`,
          height: "100%",
          background: "var(--forest)",
        }}
      />
    </div>
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
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          style={{
            height: 160,
            borderRadius: 14,
            background: "var(--ink-7)",
            opacity: 0.4,
          }}
        />
      ))}
    </div>
  );
}
