type EventProps = Record<string, string | number | boolean | null | undefined>;

declare global {
  interface Window {
    posthog?: {
      capture?: (event: string, props?: EventProps) => void;
    };
  }
}

function emit(event: string, props: EventProps = {}): void {
  if (typeof window === "undefined") return;
  try {
    if (window.posthog?.capture) {
      window.posthog.capture(event, props);
      return;
    }
    if (process.env.NODE_ENV !== "production") {
      console.debug("[placement-quiz]", event, props);
    }
  } catch {
    /* swallow */
  }
}

export const quizAnalytics = {
  started: () => emit("quiz_started"),
  answered: (props: { question_id: string; answer_id: string; step: number }) =>
    emit("quiz_question_answered", props),
  completed: (props: {
    track_slug: string;
    /** Comma-joined "questionId:answerId" pairs — flat string for analytics back-ends. */
    answers: string;
    purchase_mode: "self_paced" | "cohort";
  }) => emit("quiz_completed", props),
  ctaClicked: (props: { cta_label: string; recommended_track: string }) =>
    emit("quiz_cta_clicked", props),
  curriculumClicked: (props: { recommended_track: string }) =>
    emit("quiz_curriculum_clicked", props),
};
