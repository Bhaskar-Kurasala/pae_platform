"use client";

import { PlacementQuiz } from "@/app/(public)/placement-quiz/_quiz";

/**
 * Portal-hosted placement quiz at /quiz.
 * Uses the standard .screen.active scroll container (same as every other portal
 * page) so the result card scrolls correctly inside V8Shell.
 * The inner dark card gives the quiz its own premium dark surface while the
 * portal shell stays in its light/dark theme.
 */
export default function PortalPlacementQuizPage() {
  return (
    <section className="screen active" id="screen-quiz">
      <div className="pad">
        {/* Premium dark card — full available width, no max-w cap so result fills space */}
        <div
          className="relative rounded-3xl overflow-hidden"
          style={{
            background: "linear-gradient(145deg, #141712 0%, #10120e 60%, #0d1510 100%)",
            boxShadow:
              "0 0 0 1px rgba(93,178,136,0.12), 0 24px 64px rgba(0,0,0,0.40), 0 8px 24px rgba(0,0,0,0.24)",
          }}
        >
          {/* Ambient glow overlay */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(ellipse 80% 40% at 50% 0%, rgba(29,158,117,0.14), transparent 60%), radial-gradient(ellipse 50% 40% at 90% 100%, rgba(184,134,45,0.08), transparent 60%)",
            }}
          />
          {/* Top accent line */}
          <div
            className="absolute top-0 left-0 right-0 h-[2px] z-10"
            style={{
              background:
                "linear-gradient(90deg, transparent 0%, #5db288 30%, #8fd6b1 50%, #5db288 70%, transparent 100%)",
            }}
          />
          <div className="relative z-10 px-8 py-8 sm:px-14 sm:py-10">
            <PlacementQuiz portalMode />
          </div>
        </div>
      </div>
    </section>
  );
}
