/**
 * Thin analytics wrapper — no-ops when no provider is configured.
 *
 * If posthog/segment is wired later, replace `_emit` with a real impl. The
 * call sites stay identical.
 */

import { ANALYTICS_EVENTS, type MockAnalyticsEvent } from "./copy";

type EventProps = Record<string, string | number | boolean | null | undefined>;

declare global {
  interface Window {
    // posthog has loose typing — accept unknown to avoid pulling its types in.
    posthog?: {
      capture?: (event: string, props?: EventProps) => void;
    };
  }
}

function _emit(event: MockAnalyticsEvent, props: EventProps = {}): void {
  if (typeof window === "undefined") return;
  try {
    if (window.posthog?.capture) {
      window.posthog.capture(event, props);
      return;
    }
    // Dev-only console fallback so engineers see events firing.
    if (process.env.NODE_ENV !== "production") {
      // eslint-disable-next-line no-console
      console.debug("[mock-analytics]", event, props);
    }
  } catch {
    /* swallow */
  }
}

export const mockAnalytics = {
  sessionStarted: (props: { mode: string; voice_enabled: boolean; level: string }) =>
    _emit(ANALYTICS_EVENTS.SESSION_STARTED, props),
  sessionCompleted: (props: { session_id: string; total_cost_inr: number }) =>
    _emit(ANALYTICS_EVENTS.SESSION_COMPLETED, props),
  sessionAbandoned: (props: { session_id: string; questions_answered: number }) =>
    _emit(ANALYTICS_EVENTS.SESSION_ABANDONED, props),
  reportViewed: (props: { session_id: string; verdict: string }) =>
    _emit(ANALYTICS_EVENTS.REPORT_VIEWED, props),
  reportShared: (props: { session_id: string }) =>
    _emit(ANALYTICS_EVENTS.REPORT_SHARED, props),
  nextActionClicked: (props: { session_id: string; action_label: string }) =>
    _emit(ANALYTICS_EVENTS.NEXT_ACTION_CLICKED, props),
  voiceFallbackToText: (props: { reason: string }) =>
    _emit(ANALYTICS_EVENTS.VOICE_FALLBACK_TO_TEXT, props),
  confidenceBelowThreshold: (props: { sub_agent: string; confidence: number }) =>
    _emit(ANALYTICS_EVENTS.CONFIDENCE_BELOW_THRESHOLD, props),
};
