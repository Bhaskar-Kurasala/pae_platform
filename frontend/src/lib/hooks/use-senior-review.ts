"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  practiceApi,
  type PracticeReviewPayload,
  type PracticeReviewRecord,
  type RunOutputSnapshot,
  type SeniorReview,
} from "@/lib/api-client";

/**
 * Senior code review — now persisted via /api/v1/practice/review.
 *
 * The mutation takes the student's code plus (optionally) a snapshot of
 * the most recent sandbox run so the reviewer can cite stderr / exit
 * codes verbatim instead of reasoning about behavior in the abstract.
 * Returns a {@link PracticeReviewRecord} (review + id + created_at) so
 * the caller can stash review history without a second round-trip.
 */
export function useSeniorReview() {
  return useMutation<
    PracticeReviewRecord,
    Error,
    {
      code: string;
      problemId?: string;
      problemContext?: string;
      runOutput?: RunOutputSnapshot;
    }
  >({
    mutationFn: ({ code, problemId, problemContext, runOutput }) => {
      const payload: PracticeReviewPayload = { code };
      if (problemId) payload.problem_id = problemId;
      if (problemContext) payload.problem_context = problemContext;
      if (runOutput) payload.run_output = runOutput;
      return practiceApi.review(payload);
    },
    // The review panel renders its own typed error state via
    // classifyReviewError. Without this opt-out, the global
    // MutationCache.onError handler in providers.tsx also fires and
    // students see the same error twice — once in the panel, once as
    // a bottom-right sonner toast.
    meta: { skipErrorToast: true },
  });
}

/**
 * Recent reviews for the current student, optionally scoped to one
 * problem. Drives the "lit-on-resume" affordance — if the bot has prior
 * review history for the active exercise, it shows up already lit on
 * page load.
 */
export function usePracticeReviews(problemId?: string, limit = 20) {
  return useQuery<PracticeReviewRecord[]>({
    queryKey: ["practice-reviews", problemId ?? "all", limit],
    queryFn: () => practiceApi.listReviews(problemId, limit),
    staleTime: 30_000,
  });
}

/**
 * Extracts a structured review from either a freshly-returned record
 * (the mutation result) or a list-history record. Callers that only
 * care about the review body can use this to flatten both shapes.
 */
export function reviewFromRecord(
  record: PracticeReviewRecord | undefined,
): SeniorReview | undefined {
  return record?.review;
}
