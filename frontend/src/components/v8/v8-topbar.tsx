"use client";

import { useEffect, useState } from "react";
import { useV8Topbar } from "./v8-topbar-context";

function clampPct(n: number): number {
  if (Number.isNaN(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

/**
 * Sticky v8 topbar with eyebrow, serif title, optional chips, and an
 * under-bar shimmer progress fill that animates whenever progress changes.
 */
export function V8Topbar() {
  const { state } = useV8Topbar();
  const [renderedProgress, setRenderedProgress] = useState(0);

  useEffect(() => {
    // Defer one frame so the bar grows from 0 → target on entry, mirroring
    // the v8 source's initial fill animation.
    const id = requestAnimationFrame(() => setRenderedProgress(clampPct(state.progress)));
    return () => cancelAnimationFrame(id);
  }, [state.progress]);

  return (
    <>
      <div className="session-progress" aria-hidden>
        <div className="fill" style={{ width: `${renderedProgress}%` }} />
      </div>
      <header className="topbar">
        <div>
          <div className="eyebrow">{state.eyebrow}</div>
          <h2 dangerouslySetInnerHTML={{ __html: state.titleHtml }} />
        </div>
        <div className="topbar-right">
          {state.chips.map((chip, i) => (
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
