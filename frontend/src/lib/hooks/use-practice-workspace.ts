"use client";

import { useMemo } from "react";

import {
  exercisesApi,
  pathApi,
  type ExerciseResponse,
  type PathLab,
  type PathLevel,
  type PathSummaryResponse,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import { useQuery } from "@tanstack/react-query";

/**
 * Aggregates the data the unified Practice screen needs in parallel:
 *   - the active capstone (derived from /path/summary's current level + lab list)
 *   - the full exercise catalog (so the Exercises mode rail has every task)
 *
 * Both queries are gated on `isAuthenticated` so anon users see neither.
 * The hook is intentionally read-only — selection state and code state live
 * in the screen, not here.
 */

export interface PracticeCapstone {
  /** Title of the capstone (lab marked `is_capstone` if present, else first lab). */
  title: string;
  /** One-sentence summary derived from the active level's blurb. */
  blurb: string;
  /** All labs that compose the bundle — file tree gets rendered from this. */
  labs: PathLab[];
  /** Convenience: the exercise the editor seeds itself with. */
  primaryLabId: string | null;
}

function pickCapstone(level: PathLevel | undefined): PracticeCapstone | null {
  if (!level) return null;
  // Pull every lab from every lesson on the active level — the v10 mock
  // shows a multi-file capstone bundle. Until the backend models multi-file
  // capstones, we treat the labs of the first lesson as the bundle.
  const lessons = level.lessons ?? [];
  const labs: PathLab[] = lessons.flatMap((l) => l.labs ?? []);
  if (labs.length === 0) return null;
  return {
    title: level.title,
    blurb: level.blurb,
    labs,
    primaryLabId: labs[0]?.id ?? null,
  };
}

export function usePracticeWorkspace() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);

  const exercisesQuery = useQuery<ExerciseResponse[]>({
    queryKey: ["practice", "exercises"],
    queryFn: () => exercisesApi.list(),
    enabled: isAuthed,
    staleTime: 60_000,
  });

  const pathQuery = useQuery<PathSummaryResponse>({
    queryKey: ["path", "summary"],
    queryFn: () => pathApi.summary(),
    enabled: isAuthed,
    staleTime: 60_000,
  });

  const capstone = useMemo<PracticeCapstone | null>(
    () => pickCapstone(pathQuery.data?.levels.find((l) => l.state === "current")),
    [pathQuery.data],
  );

  return {
    isAuthed,
    isLoading: exercisesQuery.isLoading || pathQuery.isLoading,
    error: exercisesQuery.error ?? pathQuery.error,
    exercises: exercisesQuery.data ?? [],
    capstone,
    activeCourseTitle: pathQuery.data?.active_course_title ?? null,
  };
}
