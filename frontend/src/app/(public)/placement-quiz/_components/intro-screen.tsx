"use client";

import { COPY } from "../_quiz-config";
import { ProgressBar } from "./progress-bar";

interface IntroScreenProps {
  onBegin: () => void;
}

export function IntroScreen({ onBegin }: IntroScreenProps) {
  return (
    <section className="text-center">
      <p className="text-[11px] uppercase tracking-[.22em] font-bold text-[#8fd6b1]">
        4 minutes · 5 questions
      </p>
      <h1
        className="mt-4 font-serif text-4xl sm:text-6xl font-medium leading-[1.05] tracking-[-0.02em]"
        style={{ fontFamily: "var(--font-serif), 'Source Serif Pro', Georgia, serif" }}
      >
        {COPY.intro.headline}
      </h1>
      <p className="mx-auto mt-6 max-w-xl text-base sm:text-lg leading-relaxed text-[#a29a8a]">
        {COPY.intro.subline}
      </p>

      <div className="mx-auto mt-8 max-w-md">
        <ProgressBar pct={0} />
      </div>

      <button
        type="button"
        onClick={onBegin}
        className="group mt-10 inline-flex items-center gap-2 rounded-full bg-[#5db288] px-7 py-4 text-sm font-semibold text-[#10120e] shadow-[0_14px_28px_rgba(53,109,80,.32)] transition-all duration-200 hover:-translate-y-[1.5px] hover:bg-[#73c79c] hover:shadow-[0_18px_34px_rgba(53,109,80,.42)] active:translate-y-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fd6b1] focus-visible:ring-offset-4 focus-visible:ring-offset-[#10120e]"
      >
        {COPY.intro.cta}
        <span aria-hidden className="transition-transform group-hover:translate-x-1">
          →
        </span>
      </button>

      <p className="mt-5 text-xs text-[#7d776a]">{COPY.intro.footer}</p>
    </section>
  );
}
