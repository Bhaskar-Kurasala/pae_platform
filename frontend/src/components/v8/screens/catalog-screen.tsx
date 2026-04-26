"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { v8Toast } from "@/components/v8/v8-toast";
import { useCatalog } from "@/lib/hooks/use-catalog";
import { RazorpayCheckoutButton } from "@/components/features/razorpay-checkout/checkout-button";
import { FreeEnrollButton } from "@/components/features/razorpay-checkout/free-enroll-button";
import type {
  CatalogBullet,
  CatalogBundleResponse,
  CatalogCourseResponse,
} from "@/lib/api-client";

type FilterKey = "all" | "free" | "beginner" | "intermediate" | "advanced" | "genai";

interface SalaryTooltip {
  eyebrow: string;
  stats: ReadonlyArray<{ v: string; l: string }>;
  foot: string;
}

const CHIP_LABELS: ReadonlyArray<{ key: FilterKey; label: string }> = [
  { key: "all", label: "All tracks" },
  { key: "free", label: "Free" },
  { key: "beginner", label: "Beginner" },
  { key: "intermediate", label: "Intermediate" },
  { key: "advanced", label: "Advanced" },
  { key: "genai", label: "GenAI" },
];

// Rotating accent palette used when metadata.accent_color is missing.
const ACCENT_PALETTE: ReadonlyArray<string> = [
  "var(--forest)",
  "var(--gold)",
  "var(--purple)",
  "#3a6ea3",
  "#22a17e",
];

const PLACEHOLDER_BULLETS: ReadonlyArray<CatalogBullet> = [
  { text: "Course content coming soon", included: false },
];

function formatPrice(cents: number, currency: string): string {
  if (cents <= 0) return "Free";
  if (currency === "INR") {
    return `₹${Math.round(cents / 100)}`;
  }
  const amount = (cents / 100).toFixed(2);
  if (currency === "USD") return `$${amount}`;
  return `${currency} ${amount}`;
}

function capitalize(value: string | null | undefined, fallback: string): string {
  if (!value) return fallback;
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
}

function levelLabel(difficulty: string | null | undefined, index: number): string {
  const tier = capitalize(difficulty, "Beginner");
  return `Level ${index + 1} · ${tier}`;
}

function truncate(text: string | null, max = 140): string {
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1).trimEnd()}…`;
}

function bulletsFor(course: CatalogCourseResponse): ReadonlyArray<CatalogBullet> {
  return course.bullets.length > 0 ? course.bullets : PLACEHOLDER_BULLETS;
}

function metaCellsFor(metadata: Record<string, unknown>): ReadonlyArray<string> {
  const cells: string[] = [];
  const push = (raw: unknown, suffix: string) => {
    if (typeof raw === "number" && Number.isFinite(raw) && raw > 0) {
      cells.push(`${raw}${suffix}`);
    }
  };
  push(metadata.est_hours, "h est.");
  push(metadata.est_weeks, " weeks");
  push(metadata.completion_pct, "% completion");
  push(metadata.placement_pct, "% placed in 90 days");
  push(metadata.lesson_count, " lessons");
  push(metadata.lab_count, " labs");
  return cells;
}

function readString(metadata: Record<string, unknown>, key: string): string | null {
  const v = metadata[key];
  return typeof v === "string" && v.length > 0 ? v : null;
}

function readSalaryTooltip(metadata: Record<string, unknown>): SalaryTooltip | null {
  const raw = metadata.salary_tooltip;
  if (!raw || typeof raw !== "object") return null;
  const t = raw as Record<string, unknown>;
  const eyebrow = typeof t.eyebrow === "string" ? t.eyebrow : null;
  const foot = typeof t.foot === "string" ? t.foot : null;
  const statsRaw = Array.isArray(t.stats) ? t.stats : null;
  if (!eyebrow || !foot || !statsRaw) return null;
  const stats: Array<{ v: string; l: string }> = [];
  for (const item of statsRaw) {
    if (item && typeof item === "object") {
      const o = item as Record<string, unknown>;
      if (typeof o.v === "string" && typeof o.l === "string") {
        stats.push({ v: o.v, l: o.l });
      }
    }
  }
  if (stats.length === 0) return null;
  return { eyebrow, stats, foot };
}

function genaiMatch(course: CatalogCourseResponse): boolean {
  const tags = course.metadata.tags;
  if (Array.isArray(tags) && tags.includes("genai")) return true;
  const slug = course.slug.toLowerCase();
  return slug.includes("genai") || slug.includes("/ai") || slug.includes("-ai") || slug.includes("ml") || slug.startsWith("ai");
}

function difficultyMatches(course: CatalogCourseResponse, key: FilterKey): boolean {
  return (course.difficulty ?? "").toLowerCase() === key;
}

function applyFilter(
  courses: ReadonlyArray<CatalogCourseResponse>,
  filter: FilterKey,
): ReadonlyArray<CatalogCourseResponse> {
  if (filter === "all") return courses;
  if (filter === "free") return courses.filter((c) => c.price_cents === 0);
  if (filter === "genai") return courses.filter(genaiMatch);
  return courses.filter((c) => difficultyMatches(c, filter));
}

interface HeroStats {
  trackCount: string;
  lessonsAndLabs: string;
}

function deriveHeroStats(
  tracks: ReadonlyArray<CatalogCourseResponse>,
  isLoading: boolean,
): HeroStats {
  if (isLoading && tracks.length === 0) {
    return { trackCount: "—", lessonsAndLabs: "—" };
  }
  const total = tracks.reduce((acc, c) => {
    const lessons = typeof c.metadata.lesson_count === "number" ? c.metadata.lesson_count : 0;
    const labs = typeof c.metadata.lab_count === "number" ? c.metadata.lab_count : 0;
    return acc + lessons + labs;
  }, 0);
  return {
    trackCount: tracks.length > 0 ? String(tracks.length) : "—",
    lessonsAndLabs: total > 0 ? String(total) : "—",
  };
}

interface BundleIncluded {
  titles: ReadonlyArray<string>;
  more: number;
}

function bundleIncluded(
  bundle: CatalogBundleResponse,
  courses: ReadonlyArray<CatalogCourseResponse>,
): BundleIncluded {
  const byId = new Map(courses.map((c) => [c.id, c.title]));
  const titles: string[] = [];
  for (const id of bundle.course_ids) {
    const t = byId.get(id);
    if (t) titles.push(t);
  }
  if (titles.length === 0) {
    return { titles: [`${bundle.course_ids.length} course(s)`], more: 0 };
  }
  const visible = titles.slice(0, 3);
  return { titles: visible, more: Math.max(0, titles.length - visible.length) };
}

export function CatalogScreen() {
  const { data, isLoading, error } = useCatalog();
  const tracks = useMemo(() => data?.courses ?? [], [data]);
  const bundles = useMemo(() => data?.bundles ?? [], [data]);

  const heroStats = useMemo(
    () => deriveHeroStats(tracks, isLoading),
    [tracks, isLoading],
  );

  useSetV8Topbar({
    eyebrow:
      tracks.length > 0
        ? `Catalog · ${tracks.length} career track${tracks.length === 1 ? "" : "s"}`
        : "Catalog",
    titleHtml: "Every role is a track. Unlock the <i>next one</i> when ready.",
    chips: [],
    progress: 50,
  });

  const [filter, setFilter] = useState<FilterKey>("all");

  const visibleTracks = useMemo(() => applyFilter(tracks, filter), [tracks, filter]);

  return (
    <section className="screen active" id="screen-catalog">
      <div className="pad">
        <section className="card catalog-hero reveal">
          <div className="eyebrow">
            Catalog
            <Link
              href="/receipts"
              className="catalog-receipts-link"
              style={{ marginLeft: 12, fontSize: 12, color: "var(--ink-2)" }}
            >
              Receipts →
            </Link>
          </div>
          <h3>
            Every role is a track. Unlock the <i>next one</i> when you&apos;re ready.
          </h3>
          <p>
            Free foundation builds your base. Paid tracks add a capstone, graded labs,
            mentor reviews, and placement-ready proof. Buy one track, or bundle a career arc.
          </p>
          <div className="stats">
            <div className="stat">
              <div className="v">{heroStats.trackCount}</div>
              <div className="l">career tracks</div>
            </div>
            <div className="stat">
              <div className="v">{heroStats.lessonsAndLabs}</div>
              <div className="l">lessons + labs</div>
            </div>
            <div className="stat">
              {/* LATER: live aggregate — no count endpoint yet. */}
              <div className="v">2,400+</div>
              <div className="l">students promoted</div>
            </div>
            <div className="stat">
              <div className="v">30 days</div>
              <div className="l">money-back guarantee</div>
            </div>
          </div>
        </section>

        <div className="catalog-filter">
          {CHIP_LABELS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className={`cf-chip${filter === key ? " on" : ""}`}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>

        {error ? (
          <div className="card" role="alert" style={{ borderColor: "var(--rose)" }}>
            <h5>Couldn&apos;t load the catalog.</h5>
            <p>Try refreshing the page in a moment.</p>
          </div>
        ) : null}

        {isLoading && tracks.length === 0 ? (
          <CatalogSkeletonGrid />
        ) : tracks.length === 0 ? (
          <div className="card empty-state" role="status">
            <h5>No tracks published yet</h5>
            <p>Check back soon — we&apos;re finalizing the next track release.</p>
          </div>
        ) : (
          <div className="course-grid" id="courseGrid">
            {visibleTracks.map((course, idx) => (
              <CourseCard key={course.id} course={course} index={idx} />
            ))}
            {bundles.map((bundle) => (
              <BundleCard key={bundle.id} bundle={bundle} courses={tracks} />
            ))}
          </div>
        )}

        <div className="catalog-strip reveal">
          <div>
            <h5>Not sure which track fits?</h5>
            <p>
              Take the 4-minute placement quiz. We&apos;ll look at your current role,
              lessons completed, and goal, then recommend the right next step and the
              fastest path there.
            </p>
          </div>
          <div
            style={{
              display: "flex",
              gap: 14,
              alignItems: "center",
              justifyContent: "flex-end",
            }}
          >
            <div className="bundle-price">
              <span className="amt">4 min</span>
            </div>
            <Link
              href="/placement-quiz"
              className="btn primary"
              style={{ padding: "12px 20px" }}
            >
              Start placement quiz
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

interface CourseCardProps {
  course: CatalogCourseResponse;
  index: number;
}

function CourseCard({ course, index }: CourseCardProps) {
  const ribbonText = readString(course.metadata, "ribbon_text");
  const accent = readString(course.metadata, "accent_color") ?? ACCENT_PALETTE[index % ACCENT_PALETTE.length];
  const accent2 = readString(course.metadata, "accent_color_2") ?? accent;
  const tooltip = readSalaryTooltip(course.metadata);
  const bullets = bulletsFor(course);
  const meta = metaCellsFor(course.metadata);
  const description = truncate(course.description, 140);
  const articleClasses = ["course-card"];
  if (ribbonText) articleClasses.push("featured");
  if (!course.is_unlocked && course.price_cents > 0) {
    articleClasses.push("locked-card-v8");
  }

  const onUnlocked = () => {
    v8Toast(`✓ ${course.title} unlocked`);
  };

  let cta: React.ReactNode;
  if (course.is_unlocked) {
    cta = (
      <button type="button" className="course-cta enrolled" disabled>
        ✓ Enrolled
      </button>
    );
  } else if (course.price_cents === 0) {
    cta = (
      <FreeEnrollButton
        courseId={course.id}
        label="Enroll free"
        className="course-cta"
        onEnrolled={onUnlocked}
      />
    );
  } else {
    cta = (
      <RazorpayCheckoutButton
        targetType="course"
        targetId={course.id}
        label="Unlock track"
        variant="gold"
        className="course-cta gold"
        onUnlocked={onUnlocked}
      />
    );
  }

  return (
    <article
      className={articleClasses.join(" ")}
      data-cat={course.difficulty ?? "all"}
      style={
        {
          "--accent": accent,
          "--accent-2": accent2,
        } as React.CSSProperties
      }
    >
      {ribbonText ? <div className="ribbon">{ribbonText}</div> : null}
      <div className="level">{levelLabel(course.difficulty, index)}</div>
      <h4>{course.title}</h4>
      <div className="role-sub">{description}</div>
      <div className="course-outcomes">
        {bullets.map((b, i) => (
          <div key={i} className="course-outcome">
            <span className={`dot${b.included ? " on" : ""}`}>
              {b.included ? "✓" : "·"}
            </span>
            <span>{b.text}</span>
          </div>
        ))}
      </div>
      <div className="course-meta-row">
        {meta.length > 0 ? (
          meta.map((cell, i) => <span key={i}>{cell}</span>)
        ) : (
          <span>New track</span>
        )}
      </div>
      <div className="course-foot">
        <div className="course-price">
          {course.price_cents === 0 ? (
            <span className="free">Free</span>
          ) : course.currency === "INR" ? (
            <>
              <span className="cur">₹</span>
              <span className="amt">{Math.round(course.price_cents / 100)}</span>
            </>
          ) : (
            <>
              <span className="cur">{course.currency === "USD" ? "$" : `${course.currency} `}</span>
              <span className="amt">{(course.price_cents / 100).toFixed(2)}</span>
            </>
          )}
        </div>
        {cta}
      </div>
      {tooltip ? (
        <div className="salary-tooltip">
          <div className="tooltip-eyebrow">{tooltip.eyebrow}</div>
          <div className="tooltip-stats">
            {tooltip.stats.map((s, i) => (
              <div key={i}>
                <div className="tooltip-stat-v">{s.v}</div>
                <div className="tooltip-stat-l">{s.l}</div>
              </div>
            ))}
          </div>
          <div className="tooltip-foot">{tooltip.foot}</div>
        </div>
      ) : null}
    </article>
  );
}

interface BundleCardProps {
  bundle: CatalogBundleResponse;
  courses: ReadonlyArray<CatalogCourseResponse>;
}

function BundleCard({ bundle, courses }: BundleCardProps) {
  const included = bundleIncluded(bundle, courses);
  const accent = readString(bundle.metadata, "accent_color") ?? "var(--gold)";
  const accent2 = readString(bundle.metadata, "accent_color_2") ?? "var(--gold-2)";
  const ribbonText = readString(bundle.metadata, "ribbon_text");
  const description = truncate(bundle.description, 180);

  const onUnlocked = () => {
    v8Toast(`✓ ${bundle.title} unlocked`);
  };

  return (
    <article
      className="course-card featured"
      data-cat="bundle"
      style={
        {
          "--accent": accent,
          "--accent-2": accent2,
        } as React.CSSProperties
      }
    >
      {ribbonText ? (
        <div className="ribbon" style={{ background: "#10120e", color: "#fff" }}>
          {ribbonText}
        </div>
      ) : null}
      <div className="level">Full career arc</div>
      <h4>{bundle.title}</h4>
      <div className="role-sub">{description}</div>
      <div className="course-outcomes">
        <div className="course-outcome">
          <span className="dot on">✓</span>
          <span>
            {bundle.course_ids.length} course{bundle.course_ids.length === 1 ? "" : "s"} included
          </span>
        </div>
        <div className="course-outcome">
          <span className="dot on">✓</span>
          <span>
            {included.titles.join(" · ")}
            {included.more > 0 ? ` + ${included.more} more` : ""}
          </span>
        </div>
      </div>
      <div className="course-meta-row">
        <span>Bundle · save vs. separate</span>
      </div>
      <div className="course-foot">
        <div className="course-price">
          {bundle.currency === "INR" ? (
            <>
              <span className="cur">₹</span>
              <span className="amt">{Math.round(bundle.price_cents / 100)}</span>
            </>
          ) : (
            <>
              <span className="cur">{bundle.currency === "USD" ? "$" : `${bundle.currency} `}</span>
              <span className="amt">{(bundle.price_cents / 100).toFixed(2)}</span>
            </>
          )}
        </div>
        <RazorpayCheckoutButton
          targetType="bundle"
          targetId={bundle.id}
          label="Unlock bundle"
          variant="primary"
          className="course-cta gold"
          onUnlocked={onUnlocked}
        />
      </div>
    </article>
  );
}

function CatalogSkeletonGrid() {
  const slots = Array.from({ length: 5 }, (_, i) => i);
  return (
    <div className="course-grid" id="courseGrid" data-state="loading">
      {slots.map((i) => (
        <article
          key={i}
          className="course-card"
          aria-hidden
          style={{ minHeight: 360 }}
          data-testid="catalog-skeleton-card"
        >
          <div
            className="level"
            style={{
              background: "var(--ink-7, #eee)",
              height: 12,
              width: 120,
              borderRadius: 4,
            }}
          />
          <h4 style={{ height: 22, background: "var(--ink-7, #eee)", borderRadius: 4, marginTop: 12 }} />
          <div
            className="role-sub"
            style={{
              height: 40,
              background: "var(--ink-7, #f4f4f4)",
              borderRadius: 4,
              marginTop: 8,
            }}
          />
          <div style={{ marginTop: 14, color: "var(--ink-3)", fontSize: 12 }}>Loading…</div>
        </article>
      ))}
    </div>
  );
}

// Internal — keep formatPrice exported via re-export for any sibling tests.
export { formatPrice };
