"use client";

import { useMemo } from "react";
import { useCatalog } from "@/lib/hooks/use-catalog";

interface EntitlementsResult {
  entitledCourseIds: Set<string>;
  isLoading: boolean;
}

/**
 * Derives the set of course UUIDs the current user has unlocked from the
 * catalog response. Single source of truth for "is this course paid for?"
 * across the app — keep all gating logic reading from this hook so that
 * optimistic cache updates in `useConfirmOrder` flow through everywhere.
 */
export function useEntitlements(): EntitlementsResult {
  const { data, isLoading } = useCatalog();
  const entitledCourseIds = useMemo(() => {
    if (!data) return new Set<string>();
    return new Set(
      data.courses.filter((c) => c.is_unlocked).map((c) => c.id),
    );
  }, [data]);
  return { entitledCourseIds, isLoading };
}

/**
 * Returns:
 *   - `undefined` while the catalog is loading or when `courseId` is missing
 *   - `true`  if the user has an entitlement for that course
 *   - `false` otherwise
 */
export function useIsCourseUnlocked(
  courseId: string | null | undefined,
): boolean | undefined {
  const { data, isLoading } = useCatalog();
  if (isLoading) return undefined;
  if (!courseId || !data) return undefined;
  const course = data.courses.find((c) => c.id === courseId);
  if (!course) return false;
  return course.is_unlocked;
}
