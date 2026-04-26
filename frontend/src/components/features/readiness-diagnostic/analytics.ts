/**
 * Readiness diagnostic analytics — no-ops when no provider is configured.
 *
 * Event names track the spec's success metrics:
 *   - diagnostic.session.started        (activation)
 *   - diagnostic.turn.sent               (engagement)
 *   - diagnostic.verdict.delivered       (trust)
 *   - diagnostic.next_action.clicked     (north-star: leads completion check)
 *   - diagnostic.session.abandoned       (funnel break)
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
      console.debug("[diagnostic]", event, props);
    }
  } catch {
    /* swallow */
  }
}

export const diagnosticAnalytics = {
  sessionStarted: (props: { session_id: string; has_prior_session: boolean }) =>
    _emit("diagnostic.session.started", props),
  turnSent: (props: { session_id: string; turn_number: number }) =>
    _emit("diagnostic.turn.sent", props),
  verdictDelivered: (props: {
    session_id: string;
    next_action_intent: string;
    sycophancy_flag_count: number;
  }) => _emit("diagnostic.verdict.delivered", props),
  nextActionClicked: (props: {
    session_id: string;
    action_label: string;
    intent: string;
  }) => _emit("diagnostic.next_action.clicked", props),
  sessionAbandoned: (props: { session_id: string; turn_count: number }) =>
    _emit("diagnostic.session.abandoned", props),
  invokedDecoder: (props: { session_id: string }) =>
    _emit("diagnostic.decoder.invoked", props),
};
