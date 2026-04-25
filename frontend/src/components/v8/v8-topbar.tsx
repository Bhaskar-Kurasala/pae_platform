"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import { useV8Topbar, type V8TopbarState } from "./v8-topbar-context";

function clampPct(n: number): number {
  if (Number.isNaN(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

interface RouteFallback {
  test: RegExp;
  state: V8TopbarState;
}

/**
 * Default eyebrow/title for routes that don't set their own topbar via
 * `useSetV8Topbar`. Lets the existing exercises/receipts/chat/etc. pages
 * sit cleanly inside the v8 shell without per-page wiring.
 */
const ROUTE_FALLBACKS: ReadonlyArray<RouteFallback> = [
  {
    test: /^\/exercises(\/|$)/,
    state: {
      eyebrow: "Practice · Exercises",
      titleHtml: "Hands-on builds with <i>AI-powered</i> code review.",
      chips: [],
      progress: 55,
    },
  },
  {
    test: /^\/receipts(\/|$)/,
    state: {
      eyebrow: "Receipts",
      titleHtml: "Proof of where your <i>week</i> went.",
      chips: [],
      progress: 70,
    },
  },
  {
    test: /^\/chat(\/|$)/,
    state: {
      eyebrow: "AI Tutor",
      titleHtml: "Ask the model that <i>thinks like a senior</i>.",
      chips: [],
      progress: 60,
    },
  },
  {
    test: /^\/onboarding(\/|$)/,
    state: {
      eyebrow: "Onboarding · Goal contract",
      titleHtml: "Tell us where you're <i>headed</i>.",
      chips: [],
      progress: 8,
    },
  },
  {
    test: /^\/lessons(\/|$)/,
    state: {
      eyebrow: "Lesson",
      titleHtml: "Learn the <i>concept</i>, then prove it.",
      chips: [],
      progress: 45,
    },
  },
  {
    test: /^\/interview(\/|$)/,
    state: {
      eyebrow: "Interview practice",
      titleHtml: "Pressure-test what you <i>actually</i> know.",
      chips: [],
      progress: 65,
    },
  },
  {
    test: /^\/progress(\/|$)/,
    state: {
      eyebrow: "Progress",
      titleHtml: "Trace the line between <i>effort and outcome</i>.",
      chips: [],
      progress: 72,
    },
  },
  {
    test: /^\/career(\/|$)/,
    state: {
      eyebrow: "Career workspace",
      titleHtml: "Turn proof into <i>interviews</i>.",
      chips: [],
      progress: 80,
    },
  },
  {
    test: /^\/courses(\/|$)/,
    state: {
      eyebrow: "Courses",
      titleHtml: "Open the lesson that <i>moves</i> you next.",
      chips: [],
      progress: 50,
    },
  },
];

/**
 * Sticky v8 topbar with eyebrow, serif title, optional chips, and an
 * under-bar shimmer progress fill that animates whenever progress changes.
 *
 * Pages that don't call `useSetV8Topbar` get a sensible fallback derived
 * from the pathname.
 */
export function V8Topbar() {
  const { state } = useV8Topbar();
  const pathname = usePathname();
  const [renderedProgress, setRenderedProgress] = useState(0);

  const effective = useMemo<V8TopbarState>(() => {
    if (state.eyebrow || state.titleHtml) return state;
    const match = ROUTE_FALLBACKS.find((r) => r.test.test(pathname));
    return match ? match.state : state;
  }, [state, pathname]);

  useEffect(() => {
    // Defer one frame so the bar grows from 0 → target on entry, mirroring
    // the v8 source's initial fill animation.
    const id = requestAnimationFrame(() => setRenderedProgress(clampPct(effective.progress)));
    return () => cancelAnimationFrame(id);
  }, [effective.progress]);

  return (
    <>
      <div className="session-progress" aria-hidden>
        <div className="fill" style={{ width: `${renderedProgress}%` }} />
      </div>
      <header className="topbar">
        <div>
          <div className="eyebrow">{effective.eyebrow}</div>
          <h2 dangerouslySetInnerHTML={{ __html: effective.titleHtml }} />
        </div>
        <div className="topbar-right">
          {effective.chips.map((chip, i) => (
            <span
              key={`${chip.label}-${i}`}
              className={`chip${chip.variant && chip.variant !== "neutral" ? ` ${chip.variant}` : ""}`}
            >
              {chip.label}
            </span>
          ))}
        </div>
      </header>
    </>
  );
}
