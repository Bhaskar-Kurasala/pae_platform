"use client";

/**
 * Result screen — the Hormozi knockout.
 * Stacking order locked per spec: A → B → C → D → E → F → G → H → I.
 *
 * Block H (cohort/seats urgency) is rendered ONLY when COHORT.enabled === true
 * in _quiz-config.ts. Currently disabled until the backend exposes a real
 * cohort_starts_at field.
 *
 * All 9 blocks are kept in one file — they're a single visual unit, all read
 * from the same answers + scoring outputs, and splitting them would mean
 * threading 5+ props through 9 thin components for no review-surface gain.
 */

import type { CourseResponse } from "@/lib/api-client";
import {
  COHORT,
  COPY,
  TRACKS,
  renderEchoBody,
  type TrackMeta,
  type VerifiedStat,
} from "../_quiz-config";
import { TOTAL_QUESTIONS, type AnswersMap, type TrackKey } from "../_quiz-questions";
import {
  getCommitmentIntensity,
  getConfidencePercent,
  getEchoPieces,
  getUrgencyMode,
} from "../_quiz-scoring";
import { PlaceholderBadge } from "./placeholder-badge";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatUsd(cents: number): string {
  if (cents <= 0) return "Free";
  const dollars = cents / 100;
  return `$${Number.isInteger(dollars) ? dollars.toFixed(0) : dollars.toFixed(2)}`;
}

function formatHm(d: Date): string {
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  return `${h}:${m}`;
}

function VerifiedNumber<T extends string | number>({
  stat,
  format,
}: {
  stat: VerifiedStat<T>;
  format?: (v: T) => string;
}) {
  const display = format ? format(stat.value) : String(stat.value);
  return (
    <>
      <b className="text-[#f0ece1]">{display}</b>
      <PlaceholderBadge verified={stat.verified} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Result screen
// ---------------------------------------------------------------------------

interface ResultScreenProps {
  track: TrackKey;
  answers: AnswersMap;
  courses: ReadonlyArray<CourseResponse> | undefined;
  startTime: number;
  onEnroll: () => void;
  onCurriculum: () => void;
  checkoutLoading: boolean;
  onRestart: () => void;
}

export function ResultScreen({
  track,
  answers,
  courses,
  startTime,
  onEnroll,
  onCurriculum,
  checkoutLoading,
  onRestart,
}: ResultScreenProps) {
  const meta: TrackMeta = TRACKS[track];
  const echo = getEchoPieces(answers);
  const echoLines = renderEchoBody({
    q1Paraphrase: echo.q1Paraphrase,
    q2Verbatim: echo.q2Verbatim,
    q3Paraphrase: echo.q3Paraphrase,
    q4Verbatim: echo.q4Verbatim,
    q5Paraphrase: echo.q5Paraphrase,
  });

  const confidence = getConfidencePercent(answers);
  const urgencyMode = getUrgencyMode(answers);
  const intensity = getCommitmentIntensity(answers);

  const liveCourse = courses?.find((c) => c.slug === meta.courseSlug);
  const livePriceCents = liveCourse?.price_cents ?? 0;
  const livePriceLabel = formatUsd(livePriceCents);
  const anchorTotal = meta.anchor.reduce((sum, a) => sum + a.price, 0);

  const ctaLabel =
    urgencyMode === "decided"
      ? COPY.result.cta.decided(meta.displayName)
      : COPY.result.cta.activating(meta.displayName);

  // Timestamp clamp: if elapsed > 15 min, drop the time mechanic and lean on
  // the closing line alone. See Hormozi-feedback decision in conversation.
  const startDate = new Date(startTime);
  const endDate = new Date();
  const elapsedMs = endDate.getTime() - startDate.getTime();
  const elapsedClamped = elapsedMs > 15 * 60 * 1000;

  return (
    <section>
      {/* ============================================================
          BLOCK A — Verdict headline
          ============================================================ */}
      <p className="text-[11px] uppercase tracking-[.22em] font-bold text-[#8fd6b1]">
        Your match
      </p>
      <h2
        className="mt-3 font-serif text-4xl sm:text-5xl font-medium leading-[1.05] tracking-[-0.02em]"
        style={{ fontFamily: "var(--font-serif), 'Source Serif Pro', Georgia, serif" }}
      >
        ✨ {COPY.result.verdictPrefix}{" "}
        <span className="text-[#8fd6b1]">{meta.displayName}</span>
      </h2>
      <p className="mt-2 text-sm text-[#a29a8a]">
        Confidence: <span className="text-[#f0ece1] font-semibold">{confidence}%</span>{" "}
        {COPY.result.confidenceLabel}
      </p>
      <p className="mt-3 text-base sm:text-lg text-[#a29a8a]">{meta.tagline}</p>

      {/* ============================================================
          BLOCK B — Echo card
          ============================================================ */}
      <div
        className="mt-9 rounded-2xl border border-white/8 bg-white/[0.04] p-5 sm:p-6"
        style={{ borderLeftWidth: "4px", borderLeftColor: "#5db288" }}
      >
        <p className="text-[10px] uppercase tracking-[.2em] font-bold text-[#a29a8a]">
          {COPY.result.echoHeader}
        </p>
        <div className="mt-3 space-y-2 text-[15px] leading-relaxed text-[#d6d2c6]">
          {echoLines.map((line, i) => (
            <p key={i}>{line}</p>
          ))}
        </div>
        <p className="mt-5 text-lg sm:text-xl font-semibold text-[#f0ece1]">
          {COPY.result.echoFinalLine}
        </p>
      </div>

      {/* ============================================================
          BLOCK C — Four pillars (2x2 grid)
          ============================================================ */}
      <h3 className="mt-12 font-serif text-2xl sm:text-3xl font-medium tracking-[-0.015em] text-[#f0ece1]"
        style={{ fontFamily: "var(--font-serif), 'Source Serif Pro', Georgia, serif" }}
      >
        {COPY.result.pillarsHeader}
      </h3>
      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        {/* Pillar 1 — Your Dream */}
        <Pillar title={COPY.result.pillarTitles.dream}>
          <p>
            {capitalize(echo.q3Paraphrase.replace(/^to /, ""))}.
          </p>
          <p className="mt-2 text-[#a29a8a]">
            The last <VerifiedNumber stat={meta.cohortSize} /> students who started
            exactly where you are —{" "}
            <VerifiedNumber stat={meta.successRate} format={(v) => `${v}%`} /> are
            there now. Average outcome:{" "}
            <VerifiedNumber stat={meta.averageOutcome} />.
          </p>
        </Pillar>
        {/* Pillar 2 — Why this time is different (quote Q4 + system fix) */}
        <Pillar title={COPY.result.pillarTitles.different}>
          <p>You said: {echo.q4Verbatim}</p>
          <p className="mt-2 text-[#a29a8a]">
            That&apos;s not a feeling. That&apos;s a system failure. This track is built
            backwards from exactly that — {echo.q4SystemFix}
          </p>
        </Pillar>
        {/* Pillar 3 — Speed */}
        <Pillar title={COPY.result.pillarTitles.speed}>
          <p className="text-[#d6d2c6]">
            {COPY.result.speedTemplate(meta.timeline.shipDay, meta.timeline.resumeDay)}
          </p>
        </Pillar>
        {/* Pillar 4 — Effort relief beat */}
        <Pillar title={COPY.result.pillarTitles.effort}>
          <p className="text-[#d6d2c6]">{meta.effortLine}</p>
        </Pillar>
      </div>

      {/* ============================================================
          BLOCK D — What's included
          ============================================================ */}
      <h3 className="mt-12 text-[11px] uppercase tracking-[.2em] font-bold text-[#a29a8a]">
        {COPY.result.includedHeader}
      </h3>
      <ul className="mt-4 grid gap-2.5 sm:grid-cols-2">
        {meta.included.map((line) => (
          <li
            key={line}
            className="flex gap-2.5 rounded-xl bg-white/[0.03] px-4 py-3 text-sm text-[#d6d2c6]"
          >
            <span aria-hidden className="text-[#8fd6b1] shrink-0">✓</span>
            <span>{line}</span>
          </li>
        ))}
      </ul>

      {/* ============================================================
          BLOCK E — Price anchor
          ============================================================ */}
      {livePriceCents > 0 ? (
        <div className="mt-10 rounded-2xl border border-[#5db288]/25 bg-gradient-to-br from-[#244f39]/30 to-[#10120e]/0 p-6 shadow-[0_18px_44px_rgba(0,0,0,.35)]">
          <p className="text-[11px] uppercase tracking-[.2em] font-bold text-[#a29a8a]">
            {COPY.result.priceCard.anchorHeader}
          </p>
          <ul className="mt-3 space-y-1.5 text-sm text-[#d6d2c6]/80">
            {meta.anchor.map((a) => (
              <li key={a.label} className="flex justify-between line-through decoration-[#a29a8a]/40">
                <span>{a.label}</span>
                <span className="font-mono">${a.price.toLocaleString()}</span>
              </li>
            ))}
            <li className="flex justify-between border-t border-white/10 pt-2 mt-2 font-semibold text-[#a29a8a]">
              <span>{COPY.result.priceCard.comparableValueLabel}</span>
              <span className="font-mono">${anchorTotal.toLocaleString()}</span>
            </li>
          </ul>
          <div className="mt-6 flex items-baseline gap-3">
            <span className="text-xs uppercase tracking-[.18em] text-[#a29a8a]">
              {COPY.result.priceCard.yourPriceLabel}
            </span>
            <span
              className="font-serif text-5xl sm:text-6xl font-medium tracking-[-0.02em] text-[#8fd6b1]"
              style={{ fontFamily: "var(--font-serif), 'Source Serif Pro', Georgia, serif" }}
            >
              {livePriceLabel}
            </span>
            <span className="text-sm text-[#a29a8a]">
              {COPY.result.priceCard.oneTime}
            </span>
          </div>
          <p className="mt-2 text-sm text-[#a29a8a]">{meta.perDayLine}</p>
        </div>
      ) : null}

      {/* ============================================================
          BLOCK F — Guarantee
          ============================================================ */}
      <div className="mt-10 rounded-2xl border border-[#8fd6b1]/20 bg-gradient-to-br from-[#5db288]/8 via-[#10120e]/0 to-[#10120e]/0 p-6 sm:p-7">
        <h3
          className="font-serif text-xl sm:text-2xl font-medium text-[#f0ece1] tracking-[-0.015em]"
          style={{ fontFamily: "var(--font-serif), 'Source Serif Pro', Georgia, serif" }}
        >
          {COPY.result.guarantee.header}
        </h3>
        <p className="mt-4 text-[15px] leading-relaxed text-[#d6d2c6]">
          {COPY.result.guarantee.body(meta.dreamForGuarantee)}
        </p>
        <p className="mt-2 text-[15px] leading-relaxed text-[#d6d2c6]">
          {COPY.result.guarantee.bodyClose}
        </p>
        <p className="mt-3 text-[15px] leading-relaxed font-semibold italic text-[#8fd6b1]">
          {COPY.result.guarantee.emphasis}
        </p>
      </div>

      {/* ============================================================
          BLOCK G — Primary CTA + secondary
          ============================================================ */}
      <div className="mt-8 flex flex-col items-center gap-4">
        <button
          type="button"
          onClick={onEnroll}
          disabled={checkoutLoading}
          className="group inline-flex w-full max-w-[480px] items-center justify-center gap-2 rounded-full bg-[#5db288] px-8 py-5 text-base font-semibold text-[#10120e] shadow-[0_14px_28px_rgba(53,109,80,.32)] transition-all duration-200 hover:-translate-y-[1.5px] hover:bg-[#73c79c] hover:shadow-[0_18px_34px_rgba(53,109,80,.42)] active:translate-y-0 disabled:cursor-wait disabled:opacity-70 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fd6b1] focus-visible:ring-offset-4 focus-visible:ring-offset-[#10120e]"
        >
          {checkoutLoading ? "Opening checkout…" : ctaLabel}
          <span aria-hidden className="transition-transform group-hover:translate-x-1">→</span>
        </button>
        <button
          type="button"
          onClick={onCurriculum}
          className="text-sm text-[#a29a8a] underline-offset-4 hover:text-[#f0ece1] hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[#5db288] rounded"
        >
          {COPY.result.cta.secondary}
        </button>
      </div>

      {/* ============================================================
          BLOCK H — Cohort urgency (only when COHORT.enabled)
          ============================================================ */}
      {COHORT.enabled && COHORT.startsAt && COHORT.seatsLeft != null ? (
        <p className="mt-6 text-center text-sm text-[#d6d2c6]">
          Cohort starts <b className="text-[#f0ece1]">{COHORT.startsAt}</b>.{" "}
          <b className="text-[#f0ece1]">{COHORT.seatsLeft} seats left.</b>
        </p>
      ) : null}

      {/* ============================================================
          BLOCK I — Timestamp close
          ============================================================ */}
      <div className="mt-12 border-t border-white/8 pt-8 text-center">
        {!elapsedClamped ? (
          <p className="text-xs italic text-[#7d776a]">
            {COPY.result.timestamp.withTime(formatHm(startDate), formatHm(endDate))}
          </p>
        ) : (
          <p className="text-xs italic text-[#7d776a]">
            {COPY.result.timestamp.clamped}
          </p>
        )}
        <p
          className={`mx-auto mt-2 max-w-md text-sm italic text-[#a29a8a] ${
            intensity >= 3 ? "font-semibold text-[#d6d2c6]" : ""
          }`}
        >
          {COPY.result.timestamp.closingLine}
        </p>

        <button
          type="button"
          onClick={onRestart}
          className="mt-6 text-xs text-[#7d776a] hover:text-[#a29a8a] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#5db288] rounded"
        >
          Retake quiz
        </button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Pillar — small bordered card with checkmark + heading + body slot.
// ---------------------------------------------------------------------------

function Pillar({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-5">
      <div className="flex items-center gap-2">
        <span aria-hidden className="text-[#8fd6b1]">✓</span>
        <span className="text-[10px] uppercase tracking-[.2em] font-bold text-[#a29a8a]">
          {title}
        </span>
      </div>
      <div className="mt-3 text-[14.5px] leading-relaxed text-[#f0ece1]">
        {children}
      </div>
    </div>
  );
}

function capitalize(s: string): string {
  if (!s) return s;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Make TOTAL_QUESTIONS available if a future block needs it (currently unused
// here but keeps result-screen self-contained for testing).
export { TOTAL_QUESTIONS };
