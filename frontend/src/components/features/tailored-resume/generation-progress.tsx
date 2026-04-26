"use client";

import { useEffect, useState } from "react";
import { tailoredResumeCopy as copy } from "@/lib/copy/tailored-resume";

interface Props {
  active: boolean;
}

const STEP_DURATION_MS = 2200;

export function GenerationProgress({ active }: Props) {
  const [stepIndex, setStepIndex] = useState(0);

  useEffect(() => {
    if (!active) {
      setStepIndex(0);
      return;
    }
    const timer = window.setInterval(() => {
      setStepIndex((idx) =>
        idx < copy.generation.steps.length - 1 ? idx + 1 : idx,
      );
    }, STEP_DURATION_MS);
    return () => window.clearInterval(timer);
  }, [active]);

  if (!active) return null;

  return (
    <div className="rd-panel" role="status" aria-live="polite">
      <div className="t">{copy.generation.steps[stepIndex]}</div>
      <div className="c">
        {copy.generation.steps.map((label, i) => (
          <div
            key={label}
            className={`export-step${i <= stepIndex ? " done" : ""}`}
          >
            {label}
          </div>
        ))}
      </div>
    </div>
  );
}
