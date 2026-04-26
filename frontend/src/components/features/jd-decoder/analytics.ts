/**
 * JD Decoder analytics — no-ops when no provider is configured.
 * Mirrors the mock-interview analytics shape for consistency.
 */

type EventProps = Record<string, string | number | boolean | null | undefined>;

declare global {
  interface Window {
    posthog?: {
      capture?: (event: string, props?: EventProps) => void;
    };
  }
}

function _emit(event: string, props: EventProps = {}): void {
  if (typeof window === "undefined") return;
  try {
    if (window.posthog?.capture) {
      window.posthog.capture(event, props);
      return;
    }
    if (process.env.NODE_ENV !== "production") {
      console.debug("[jd-decoder]", event, props);
    }
  } catch {
    /* swallow */
  }
}

export const jdDecoderAnalytics = {
  decoded: (props: {
    jd_analysis_id: string;
    cached: boolean;
    score: number | null;
  }) => _emit("jd.decoded", props),
  matchScoreCalculated: (props: {
    jd_analysis_id: string;
    score: number | null;
  }) => _emit("jd.match_score.calculated", props),
  nextActionClicked: (props: {
    jd_analysis_id: string;
    action_label: string;
    intent: string;
  }) => _emit("jd.next_action.clicked", props),
};
