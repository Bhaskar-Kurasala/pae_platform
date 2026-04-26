"use client";

import { useEffect, useRef } from "react";
import type { QuizQuestion } from "../_quiz-questions";
import { ProgressBar } from "./progress-bar";

interface QuestionScreenProps {
  question: QuizQuestion;
  /** 1-based for display; pct = (index / total) * 100. */
  index: number;
  total: number;
  /** Currently-selected option id, if any (back-navigation case). */
  selected: string | undefined;
  /** Fires after the user picks. Parent handles the 250ms auto-advance delay. */
  onChoose: (optionId: string) => void;
}

export function QuestionScreen({
  question,
  index,
  total,
  selected,
  onChoose,
}: QuestionScreenProps) {
  const headlineRef = useRef<HTMLHeadingElement>(null);

  // Focus the headline on screen change so screen readers announce the new
  // question, and arrow-key handling has a stable focus root.
  useEffect(() => {
    headlineRef.current?.focus();
  }, [question.id]);

  const handleKey = (e: React.KeyboardEvent<HTMLLIElement>, idx: number) => {
    const opts = question.options;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      e.preventDefault();
      const nextIdx = (idx + 1) % opts.length;
      const nextEl = document.getElementById(`opt-${question.id}-${opts[nextIdx].id}`);
      nextEl?.focus();
    } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      e.preventDefault();
      const prevIdx = (idx - 1 + opts.length) % opts.length;
      const prevEl = document.getElementById(`opt-${question.id}-${opts[prevIdx].id}`);
      prevEl?.focus();
    }
  };

  // Q2 carries a heavier card background — see _quiz-questions.ts visualWeight.
  const heavy = question.visualWeight === "heavy";

  return (
    <section aria-live="polite">
      <p className="text-[11px] uppercase tracking-[.22em] font-bold text-[#8fd6b1]">
        Question {index} of {total} · {question.theme}
      </p>

      <div className="mt-3">
        <ProgressBar pct={(index / total) * 100} />
      </div>

      <h2
        ref={headlineRef}
        tabIndex={-1}
        className="mt-7 font-serif text-3xl sm:text-4xl font-medium leading-tight tracking-[-0.015em] focus:outline-none max-w-[600px]"
        style={{ fontFamily: "var(--font-serif), 'Source Serif Pro', Georgia, serif" }}
      >
        {question.headline}
      </h2>
      {question.subline ? (
        <p className="mt-4 text-sm sm:text-base text-[#a29a8a] italic max-w-[600px]">
          {question.subline}
        </p>
      ) : null}

      <ul className="mt-8 grid gap-3" role="radiogroup" aria-label={question.headline}>
        {question.options.map((opt, idx) => {
          const active = selected === opt.id;
          return (
            <li
              key={opt.id}
              onKeyDown={(e) => handleKey(e, idx)}
              className="list-none"
            >
              <button
                id={`opt-${question.id}-${opt.id}`}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => onChoose(opt.id)}
                className={`group relative block w-full overflow-hidden rounded-2xl border px-5 py-5 text-left text-[15px] sm:text-base min-h-[64px] transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fd6b1] focus-visible:ring-offset-2 focus-visible:ring-offset-[#10120e] active:scale-[0.985] ${
                  active
                    ? "border-[#5db288] bg-[#5db288]/10 text-[#f0ece1]"
                    : heavy
                      ? "border-white/12 bg-white/[0.06] text-[#d6d2c6] hover:border-[#5db288]/60 hover:bg-white/[0.09]"
                      : "border-white/8 bg-white/[0.03] text-[#d6d2c6] hover:border-[#5db288]/60 hover:bg-white/[0.06]"
                }`}
              >
                {/* Mint-green left accent bar when selected. */}
                <span
                  aria-hidden
                  className={`absolute left-0 top-0 h-full w-1 transition-opacity ${
                    active ? "bg-[#5db288] opacity-100" : "opacity-0"
                  }`}
                />
                <span className="flex items-center gap-3">
                  <span className="flex-1">{opt.label}</span>
                  {/* Right-side checkmark when selected. */}
                  <span
                    aria-hidden
                    className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-[12px] font-semibold transition-all ${
                      active
                        ? "bg-[#5db288] text-[#10120e]"
                        : "bg-transparent text-transparent"
                    }`}
                  >
                    ✓
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
