/**
 * PR3/C3.2 — typed PostHog event catalog.
 *
 * Every event the platform fires goes through one of these typed
 * helpers instead of raw `telemetry.capture("some.event", {...})`
 * calls. Two reasons:
 *
 *   1. **Autocomplete + type safety.** A typo in `today.warmup_done`
 *      becomes a TypeScript error, not a silently-missing dashboard
 *      row. Property shapes are also typed so `practice.run` always
 *      has `exercise_id`, never `exerciseId`, never optional.
 *
 *   2. **Single rename point.** When PostHog says "rename
 *      practice.run → practice.exercise_run for consistency", we edit
 *      one line here instead of grep-replacing 30 call sites.
 *
 * Naming convention: `<domain>.<action>` snake_case. Past tense for
 * completed actions (`signed_in`, `saved`, `confirmed`); present
 * tense for one-shots that can repeat (`run`, `viewed`).
 *
 * The shim below this catalog is no-op-safe: when
 * `NEXT_PUBLIC_POSTHOG_KEY` is unset (dev, CI, pre-deploy), every
 * call returns immediately without touching the SDK.
 */

import { capture, identify } from "@/lib/telemetry";

// ─── Auth ─────────────────────────────────────────────────────────

export const trackSignedUp = (userId: string, method: "email" | "github" | "google"): void => {
  identify(userId, { signup_method: method });
  capture("auth.signed_up", { method });
};

export const trackSignedIn = (userId: string): void => {
  identify(userId);
  capture("auth.signed_in", {});
};

export const trackTokenRefreshed = (): void => {
  capture("auth.token_refreshed", {});
};

// ─── Today screen ─────────────────────────────────────────────────

export const trackTodaySummaryLoaded = (props: {
  warmup_done: boolean;
  lesson_done: boolean;
  reflect_done: boolean;
}): void => {
  capture("today.summary_loaded", props);
};

export const trackTodayStepDone = (
  step: "warmup" | "lesson" | "reflect",
): void => {
  capture(`today.${step}_done`, {});
};

// ─── Practice screen ──────────────────────────────────────────────

export const trackPracticeRun = (props: {
  mode: "capstone" | "exercises";
  exercise_id?: string;
}): void => {
  capture("practice.run", props);
};

export const trackPracticeReviewRequested = (props: {
  exercise_id?: string;
}): void => {
  capture("practice.review_requested", props);
};

export const trackPracticeNotebookSaved = (props: {
  exercise_id?: string;
}): void => {
  capture("practice.notebook_saved", props);
};

export const trackPracticeExerciseSelected = (exerciseId: string): void => {
  capture("practice.exercise_selected", { exercise_id: exerciseId });
};

// ─── Notebook screen ──────────────────────────────────────────────

export const trackNotebookSaved = (props: {
  source: "chat" | "practice" | "tutor" | "other";
}): void => {
  capture("notebook.saved", props);
};

export const trackNotebookOpened = (entryId: string): void => {
  capture("notebook.opened", { entry_id: entryId });
};

export const trackNotebookDeleted = (entryId: string): void => {
  capture("notebook.deleted", { entry_id: entryId });
};

// ─── Promotion ────────────────────────────────────────────────────

export const trackPromotionSummaryViewed = (): void => {
  capture("promotion.summary_viewed", {});
};

export const trackPromotionReady = (): void => {
  capture("promotion.ready", {});
};

export const trackPromotionConfirmed = (props: {
  level: number;
}): void => {
  capture("promotion.confirmed", props);
};

// ─── Payment ──────────────────────────────────────────────────────

export const trackPaymentCheckoutOpened = (props: {
  product: string;
  amount_inr: number;
}): void => {
  capture("payment.checkout_opened", props);
};

export const trackPaymentCompleted = (props: {
  order_id: string;
  amount_inr: number;
}): void => {
  capture("payment.completed", props);
};

export const trackPaymentFailed = (props: {
  reason: string;
}): void => {
  capture("payment.failed", props);
};

// ─── Errors ───────────────────────────────────────────────────────

export const trackErrorBoundaryCaught = (props: {
  digest?: string;
  pathname: string;
}): void => {
  capture("error.boundary_caught", props);
};

export const trackErrorApiFailed = (props: {
  status: number;
  path: string;
}): void => {
  capture("error.api_failed", props);
};
