"use client";

import { useQuery } from "@tanstack/react-query";
import { exercisesApi, type PeerSubmissionItem } from "@/lib/api-client";

export function usePeerGallery(exerciseId: string | null, limit = 20) {
  return useQuery<PeerSubmissionItem[]>({
    queryKey: ["exercises", exerciseId, "peer-gallery", limit],
    queryFn: () => {
      if (!exerciseId) return Promise.resolve([] as PeerSubmissionItem[]);
      return exercisesApi.peerGallery(exerciseId, limit);
    },
    enabled: Boolean(exerciseId),
    staleTime: 60_000,
  });
}
