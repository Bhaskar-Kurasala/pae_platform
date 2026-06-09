"use client";

import { useQuery } from "@tanstack/react-query";
import { catalogApi, type CatalogResponse } from "@/lib/api-client";

/**
 * Catalog of courses + bundles. NOT auth-gated — anonymous users can browse;
 * `is_unlocked` is `false` for them.
 */
export function useCatalog() {
  return useQuery<CatalogResponse>({
    queryKey: ["catalog"],
    queryFn: () => catalogApi.get(),
    staleTime: 60_000,
  });
}
