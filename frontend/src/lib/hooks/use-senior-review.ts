"use client";

import { useMutation } from "@tanstack/react-query";
import { seniorReviewApi, type SeniorReview } from "@/lib/api-client";

export function useSeniorReview() {
  return useMutation<
    SeniorReview,
    Error,
    { code: string; problemContext?: string }
  >({
    mutationFn: ({ code, problemContext }) =>
      seniorReviewApi.request(code, problemContext),
  });
}
