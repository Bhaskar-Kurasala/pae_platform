"use client";

import { COPY } from "../_quiz-config";
import { ProgressBar } from "./progress-bar";

export function LoadingScreen() {
  return (
    <section className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <p
        className="font-serif text-2xl sm:text-3xl text-[#f0ece1]"
        style={{ fontFamily: "var(--font-serif), 'Source Serif Pro', Georgia, serif" }}
        aria-live="polite"
      >
        {COPY.loading.line}
      </p>
      <div className="mx-auto mt-8 max-w-md w-full">
        <ProgressBar pct={100} pulse />
      </div>
    </section>
  );
}
