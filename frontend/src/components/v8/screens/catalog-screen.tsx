"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { v8Toast } from "@/components/v8/v8-toast";
import { useCourses } from "@/lib/hooks/use-courses";
import { useAuthStore } from "@/stores/auth-store";
import { billingApi, type CourseResponse } from "@/lib/api-client";

type FilterKey = "all" | "free" | "beginner" | "intermediate" | "advanced" | "genai";

interface OutcomeRow {
  on: boolean;
  text: React.ReactNode;
}

interface MetaCell {
  text: React.ReactNode;
}

interface SalaryTooltip {
  eyebrow: string;
  stats: ReadonlyArray<{ v: string; l: string }>;
  foot: string;
}

interface PriceShape {
  free?: boolean;
  cur?: string;
  amt?: string;
  was?: string;
}

interface CtaShape {
  label: string;
  variant?: "default" | "gold" | "enrolled";
  /** When set, opens enroll overlay using these details. */
  enroll?: { trackName: string; price: string; isBundle?: boolean };
  /** When set, course is real backend-wired and CTA triggers checkout. */
  courseSlug?: string;
  /** Disabled CTA (no real backend course). */
  comingSoon?: boolean;
}

interface CardShape {
  key: string;
  cats: ReadonlyArray<FilterKey>;
  accent: string;
  accent2: string;
  ribbon?: { text: string; dark?: boolean };
  level: string;
  levelColor?: string;
  title: string;
  roleSub: string;
  outcomes: ReadonlyArray<OutcomeRow>;
  meta: ReadonlyArray<MetaCell>;
  price: PriceShape;
  cta: CtaShape;
  featured?: boolean;
  locked?: boolean;
  tooltip?: SalaryTooltip;
}

const CHIP_LABELS: ReadonlyArray<{ key: FilterKey; label: string }> = [
  { key: "all", label: "All tracks" },
  { key: "free", label: "Free" },
  { key: "beginner", label: "Beginner" },
  { key: "intermediate", label: "Intermediate" },
  { key: "advanced", label: "Advanced" },
  { key: "genai", label: "GenAI" },
];

const CARDS: ReadonlyArray<CardShape> = [
  {
    key: "python",
    cats: ["free", "beginner"],
    accent: "var(--forest)",
    accent2: "var(--forest-3)",
    level: "Level 1 · Free foundation",
    title: "Python Developer",
    roleSub:
      "Clean functions, async I/O, error handling. The base every role ahead depends on.",
    outcomes: [
      {
        on: true,
        text: (
          <>
            <b>6 lessons</b> · fundamentals, OOP, APIs, testing, debugging, collab
          </>
        ),
      },
      {
        on: true,
        text: (
          <>
            <b>18 labs</b> with automated test suites
          </>
        ),
      },
      { on: true, text: <>1 CLI-tool capstone reviewed by your mentor</> },
      { on: false, text: <>Spaced-repetition notebook across all lessons</> },
    ],
    meta: [
      { text: <><b>45h</b> est.</> },
      { text: <><b>6</b> weeks</> },
      { text: <><b>92%</b> completion</> },
    ],
    price: { free: true },
    cta: { label: "✓ Enrolled", variant: "enrolled", courseSlug: "python-developer" },
  },
  {
    key: "data-analyst",
    cats: ["beginner", "intermediate"],
    accent: "var(--gold)",
    accent2: "var(--gold-2)",
    ribbon: { text: "Most popular" },
    level: "Level 2 · Your next step",
    levelColor: "#8d621b",
    title: "Data Analyst",
    roleSub:
      "SQL joins that feel natural, pandas that scales, and dashboards a stakeholder reads without a walkthrough.",
    outcomes: [
      {
        on: true,
        text: (
          <>
            <b>8 lessons</b> · SQL, pandas at scale, viz, stakeholder comms
          </>
        ),
      },
      {
        on: true,
        text: (
          <>
            <b>22 labs</b> · real retail + marketing datasets
          </>
        ),
      },
      { on: true, text: <>Dashboard capstone graded by a working analyst</> },
      { on: true, text: <>2 mock interviews + resume review with mentor</> },
    ],
    meta: [
      { text: <><b>60h</b> est.</> },
      { text: <><b>8</b> weeks</> },
      { text: <><b>76%</b> placed in 90 days</> },
    ],
    price: { cur: "$", amt: "89", was: "$129" },
    cta: {
      label: "Unlock track",
      variant: "gold",
      enroll: { trackName: "Data Analyst", price: "$89" },
      courseSlug: "data-analyst",
    },
    featured: true,
    locked: true,
    tooltip: {
      eyebrow: "Why unlock Data Analyst",
      stats: [
        { v: "$78k", l: "Median entry salary (US)" },
        { v: "12,400", l: "Open roles right now" },
      ],
      foot: "76% of CareerForge students land a role within 90 days of promotion",
    },
  },
  {
    key: "data-scientist",
    cats: ["intermediate"],
    accent: "#3a6ea3",
    accent2: "#5888b5",
    level: "Level 3 · Intermediate",
    levelColor: "#3a6ea3",
    title: "Data Scientist",
    roleSub:
      "Statistics you trust, experiments you run, and models that actually ship — not just notebooks.",
    outcomes: [
      {
        on: true,
        text: (
          <>
            <b>10 lessons</b> · stats, experimentation, ML foundations, deployment
          </>
        ),
      },
      {
        on: true,
        text: (
          <>
            <b>28 labs</b> · A/B tests, feature engineering, model ops
          </>
        ),
      },
      { on: true, text: <>Kaggle-grade capstone with peer + mentor review</> },
      { on: false, text: <>Requires Data Analyst or equivalent foundation</> },
    ],
    meta: [
      { text: <><b>90h</b> est.</> },
      { text: <><b>12</b> weeks</> },
      { text: <><b>64%</b> interview-ready in 120 days</> },
    ],
    price: { cur: "$", amt: "149" },
    cta: {
      label: "Unlock track",
      enroll: { trackName: "Data Scientist", price: "$149" },
      courseSlug: "data-scientist",
    },
    locked: true,
    tooltip: {
      eyebrow: "Why unlock Data Scientist",
      stats: [
        { v: "$112k", l: "Median salary (US)" },
        { v: "8,200", l: "Open roles right now" },
      ],
      foot: "Build models that ship. The role for people who like science and shipping.",
    },
  },
  {
    key: "ml-engineer",
    cats: ["advanced"],
    accent: "#6d4a8f",
    accent2: "#8f70ae",
    level: "Level 4 · Advanced",
    levelColor: "#6d4a8f",
    title: "ML Engineer",
    roleSub:
      "Production ML — training pipelines that don't break on Monday, features that are versioned, models that are monitored.",
    outcomes: [
      {
        on: true,
        text: (
          <>
            <b>12 lessons</b> · pipelines, feature stores, serving, monitoring
          </>
        ),
      },
      {
        on: true,
        text: (
          <>
            <b>34 labs</b> · Docker, GPUs, batch + online inference
          </>
        ),
      },
      { on: true, text: <>End-to-end production ML system as capstone</> },
      { on: false, text: <>Requires Data Scientist or equivalent</> },
    ],
    meta: [
      { text: <><b>120h</b> est.</> },
      { text: <><b>16</b> weeks</> },
      { text: <><b>$145k</b> median post-placement</> },
    ],
    price: { cur: "$", amt: "199" },
    cta: {
      label: "Unlock track",
      enroll: { trackName: "ML Engineer", price: "$199" },
      courseSlug: "ml-engineer",
    },
    locked: true,
    tooltip: {
      eyebrow: "Why unlock ML Engineer",
      stats: [
        { v: "$145k", l: "Median salary (US)" },
        { v: "5,800", l: "Open roles right now" },
      ],
      foot: "Where the actual ML lives. Production at scale, not toy notebooks.",
    },
  },
  {
    key: "genai-engineer",
    cats: ["advanced", "genai"],
    accent: "#9a4b3b",
    accent2: "#be6a56",
    level: "Level 5 · GenAI specialization",
    levelColor: "#9a4b3b",
    title: "GenAI Engineer",
    roleSub:
      "Agentic systems, production RAG, evals that catch real regressions, and LLMOps. Build what ships in 2026.",
    outcomes: [
      {
        on: true,
        text: (
          <>
            <b>14 lessons</b> · RAG, agents, evals, LLMOps, safety
          </>
        ),
      },
      {
        on: true,
        text: (
          <>
            <b>38 labs</b> · tool use, long-context, reasoning chains
          </>
        ),
      },
      { on: true, text: <>Agentic capstone + 1:1 mentor from a GenAI company</> },
      { on: false, text: <>Requires ML Engineer or equivalent production experience</> },
    ],
    meta: [
      { text: <><b>140h</b> est.</> },
      { text: <><b>18</b> weeks</> },
      { text: <><b>$180k+</b> median post-placement</> },
    ],
    price: { cur: "$", amt: "249" },
    cta: {
      label: "Unlock track",
      enroll: { trackName: "GenAI Engineer", price: "$249" },
      courseSlug: "genai-engineer",
    },
    locked: true,
    tooltip: {
      eyebrow: "Why unlock GenAI Engineer",
      stats: [
        { v: "$180k+", l: "Median salary (US)" },
        { v: "3,400", l: "Open roles · 4× yoy" },
      ],
      foot:
        "The fastest-growing role in tech. Most companies have 0–2 people who can do this.",
    },
  },
  {
    key: "bundle",
    cats: ["genai"],
    accent: "var(--gold)",
    accent2: "var(--gold-2)",
    ribbon: { text: "Bundle · save $178", dark: true },
    level: "Full career arc",
    levelColor: "#8d621b",
    title: "Data Analyst → GenAI Engineer",
    roleSub:
      "All four paid tracks, in the sequence the platform recommends. Unlock the next the moment you close the current.",
    outcomes: [
      { on: true, text: <>Analyst + Scientist + ML Engineer + GenAI Engineer</> },
      {
        on: true,
        text: (
          <>
            <b>122 labs</b> + 4 capstones + 8 mentor reviews
          </>
        ),
      },
      { on: true, text: <>Placement services + resume reviews at every level</> },
      { on: true, text: <>Priority mentor matching across all four tracks</> },
    ],
    meta: [
      { text: <><b>410h</b> est.</> },
      { text: <><b>18 months</b> est.</> },
      { text: <>Save <b>$178</b> vs. separate</> },
    ],
    price: { cur: "$", amt: "508", was: "$686" },
    cta: {
      label: "Unlock bundle",
      variant: "gold",
      enroll: { trackName: "Full arc bundle", price: "$508", isBundle: true },
      comingSoon: true,
    },
  },
];

interface EnrollState {
  trackName: string;
  price: string;
  isBundle: boolean;
  courseId: string | null;
  comingSoon: boolean;
}

function findCourseId(
  slug: string | undefined,
  courses: ReadonlyArray<CourseResponse> | undefined,
): string | null {
  if (!slug || !courses) return null;
  return courses.find((c) => c.slug === slug)?.id ?? null;
}

export function CatalogScreen() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: courses } = useCourses();

  useSetV8Topbar({
    eyebrow: "Catalog · 5 career tracks",
    titleHtml: "Every role is a track. Unlock the <i>next one</i> when ready.",
    chips: [],
    progress: 50,
  });

  const [filter, setFilter] = useState<FilterKey>("all");
  const [enroll, setEnroll] = useState<EnrollState | null>(null);
  const [checkoutLoading, setCheckoutLoading] = useState(false);

  const visibleCards = useMemo(
    () => CARDS.filter((c) => filter === "all" || c.cats.includes(filter)),
    [filter],
  );

  const closeEnroll = useCallback(() => setEnroll(null), []);

  useEffect(() => {
    if (!enroll) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeEnroll();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enroll, closeEnroll]);

  const openEnroll = useCallback(
    (card: CardShape) => {
      if (!card.cta.enroll) return;
      const courseId = findCourseId(card.cta.courseSlug, courses);
      setEnroll({
        trackName: card.cta.enroll.trackName,
        price: card.cta.enroll.price,
        isBundle: !!card.cta.enroll.isBundle,
        courseId,
        comingSoon: !!card.cta.comingSoon || !courseId,
      });
    },
    [courses],
  );

  const confirmEnroll = useCallback(async () => {
    if (!enroll) return;
    if (!isAuthenticated) {
      v8Toast("Sign in to unlock this track.");
      router.push("/login");
      return;
    }
    if (enroll.comingSoon || !enroll.courseId) {
      v8Toast("Coming soon.");
      closeEnroll();
      return;
    }
    setCheckoutLoading(true);
    try {
      const origin = typeof window !== "undefined" ? window.location.origin : "";
      const { checkout_url } = await billingApi.createCheckout({
        course_id: enroll.courseId,
        success_url: `${origin}/portal?enrolled=${enroll.courseId}`,
        cancel_url: `${origin}/catalog`,
      });
      window.location.href = checkout_url;
    } catch {
      v8Toast("Checkout failed. Try again in a moment.");
    } finally {
      setCheckoutLoading(false);
    }
  }, [enroll, isAuthenticated, router, closeEnroll]);

  const ctaWord = enroll?.isBundle ? "bundle" : "track";
  const titleSuffix = enroll?.isBundle ? "" : " track";

  return (
    <section className="screen active" id="screen-catalog">
      <div className="pad">
        <section className="card catalog-hero reveal">
          <div className="eyebrow">Catalog</div>
          <h3>
            Every role is a track. Unlock the <i>next one</i> when you&apos;re ready.
          </h3>
          <p>
            Free foundation builds your base. Paid tracks add a capstone, graded labs,
            mentor reviews, and placement-ready proof. Buy one track, or bundle a career arc.
          </p>
          <div className="stats">
            <div className="stat">
              <div className="v">5</div>
              <div className="l">career tracks</div>
            </div>
            <div className="stat">
              <div className="v">148</div>
              <div className="l">lessons + labs</div>
            </div>
            <div className="stat">
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

        <div className="course-grid" id="courseGrid">
          {visibleCards.map((card) => {
            const articleClasses = ["course-card"];
            if (card.featured) articleClasses.push("featured");
            if (card.locked) articleClasses.push("locked-card-v8");
            const ctaClasses = ["course-cta"];
            if (card.cta.variant === "gold") ctaClasses.push("gold");
            if (card.cta.variant === "enrolled") ctaClasses.push("enrolled");
            const handleCta =
              card.cta.variant === "enrolled"
                ? undefined
                : card.cta.enroll
                  ? () => openEnroll(card)
                  : undefined;
            return (
              <article
                key={card.key}
                className={articleClasses.join(" ")}
                data-cat={card.cats.join(" ")}
                style={
                  {
                    "--accent": card.accent,
                    "--accent-2": card.accent2,
                  } as React.CSSProperties
                }
              >
                {card.ribbon ? (
                  <div
                    className="ribbon"
                    style={
                      card.ribbon.dark
                        ? { background: "#10120e", color: "#fff" }
                        : undefined
                    }
                  >
                    {card.ribbon.text}
                  </div>
                ) : null}
                <div
                  className="level"
                  style={card.levelColor ? { color: card.levelColor } : undefined}
                >
                  {card.level}
                </div>
                <h4>{card.title}</h4>
                <div className="role-sub">{card.roleSub}</div>
                <div className="course-outcomes">
                  {card.outcomes.map((o, i) => (
                    <div key={i} className="course-outcome">
                      <span className={`dot${o.on ? " on" : ""}`}>{o.on ? "✓" : "·"}</span>
                      <span>{o.text}</span>
                    </div>
                  ))}
                </div>
                <div className="course-meta-row">
                  {card.meta.map((m, i) => (
                    <span key={i}>{m.text}</span>
                  ))}
                </div>
                <div className="course-foot">
                  <div className="course-price">
                    {card.price.free ? (
                      <span className="free">Free</span>
                    ) : (
                      <>
                        <span className="cur">{card.price.cur}</span>
                        <span className="amt">{card.price.amt}</span>
                        {card.price.was ? (
                          <span className="was">{card.price.was}</span>
                        ) : null}
                      </>
                    )}
                  </div>
                  <button
                    type="button"
                    className={ctaClasses.join(" ")}
                    onClick={handleCta}
                    disabled={card.cta.variant === "enrolled"}
                  >
                    {card.cta.label}
                  </button>
                </div>
                {card.tooltip ? (
                  <div className="salary-tooltip">
                    <div className="tooltip-eyebrow">{card.tooltip.eyebrow}</div>
                    <div className="tooltip-stats">
                      {card.tooltip.stats.map((s, i) => (
                        <div key={i}>
                          <div className="tooltip-stat-v">{s.v}</div>
                          <div className="tooltip-stat-l">{s.l}</div>
                        </div>
                      ))}
                    </div>
                    <div className="tooltip-foot">{card.tooltip.foot}</div>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>

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
            <Link href="/path" className="btn primary" style={{ padding: "12px 20px" }}>
              Start placement quiz
            </Link>
          </div>
        </div>
      </div>

      <div
        className={`enroll-overlay${enroll ? " on" : ""}`}
        onClick={(e) => {
          if (e.target === e.currentTarget) closeEnroll();
        }}
      >
        <div className="enroll-card" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="enroll-close"
            onClick={closeEnroll}
            aria-label="Close"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 14 14"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <path d="M2 2l10 10M12 2L2 12" />
            </svg>
          </button>
          <div className="enroll-seal">
            <svg
              width="30"
              height="30"
              viewBox="0 0 42 42"
              fill="none"
              stroke="currentColor"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="10,22 18,30 32,14" />
            </svg>
          </div>
          <h4>{enroll ? `Unlock ${enroll.trackName}${titleSuffix}` : "Unlock track"}</h4>
          <p>
            {enroll?.isBundle
              ? "You're one click from opening all four paid tracks, 122 labs, 4 capstones, and mentor reviews at every level. Money-back within 30 days."
              : "You're one click from opening this track's lessons, labs, and mentor-graded capstone. Money-back within 30 days if the track isn't right."}
          </p>
          <div className="foot">
            <button
              type="button"
              className="btn primary enroll-cta"
              onClick={confirmEnroll}
              disabled={checkoutLoading}
            >
              <span className="enroll-cta-label">
                {enroll?.comingSoon
                  ? "Coming soon"
                  : checkoutLoading
                    ? "Opening checkout…"
                    : `Unlock my ${ctaWord} · ${enroll?.price ?? ""}`}
              </span>
            </button>
          </div>
          <div className="enroll-reassure">
            <svg
              width="11"
              height="11"
              viewBox="0 0 14 14"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M7 1l5 2v4c0 3.5-2.5 5.5-5 6-2.5-.5-5-2.5-5-6V3l5-2z" />
            </svg>
            <span>30-day money-back guarantee · Secure checkout</span>
          </div>
        </div>
      </div>
    </section>
  );
}
