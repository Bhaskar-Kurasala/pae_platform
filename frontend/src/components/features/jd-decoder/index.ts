/**
 * Public surface for the JD Decoder feature.
 *
 * Components exported here are imported by:
 *   - readiness-screen.tsx (JdMatchView) for the standalone card
 *   - the diagnostic conversation (commit 9) for the inline embedding
 */

export { DecoderCard } from "./decoder-card";
export { AnalysisGrid } from "./analysis-grid";
export { MatchScoreGauge } from "./match-score-gauge";
export { jdDecoderAnalytics } from "./analytics";

/**
 * Feature-flag guard. As of the 2026-04-26 readiness workspace refactor,
 * default is ON. Set `NEXT_PUBLIC_FEATURE_JD_DECODER=0` to fall back to
 * the legacy placeholder view. Frontend gating is advisory only — the
 * backend route is the authoritative gate.
 */
export function isJdDecoderEnabled(): boolean {
  if (typeof process === "undefined") return true;
  return process.env.NEXT_PUBLIC_FEATURE_JD_DECODER !== "0";
}
