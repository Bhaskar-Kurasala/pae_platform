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
 * Feature-flag guard. Defaults to the env var; consumers may override
 * for storybook / preview tooling. Frontend gating is advisory only —
 * the backend route is the authoritative gate.
 */
export function isJdDecoderEnabled(): boolean {
  if (typeof process === "undefined") return false;
  return process.env.NEXT_PUBLIC_FEATURE_JD_DECODER === "1";
}
