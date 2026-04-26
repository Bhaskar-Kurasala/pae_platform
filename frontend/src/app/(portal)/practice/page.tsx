"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Sparkles } from "lucide-react";
import {
  exercisesApi,
  type ExerciseResponse,
  type SubmissionResponse,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

// Phase 2 builds the dedicated /practice/scratchpad route. Until then, the
// dynamic [problemId] segment swallows "scratchpad" and renders a broken
// workspace — disable the entry point.
const SCRATCHPAD_ENABLED = false;

type Tier = "foundations" | "core" | "capstone";

interface TierMeta {
  key: Tier;
  eyebrow: string;
  title: string;
  blurb: string;
  match: (d: string) => boolean;
}

const TIERS: ReadonlyArray<TierMeta> = [
  {
    key: "foundations",
    eyebrow: "Tier 1 · Foundations",
    title: "Build the reflexes every production AI engineer leans on.",
    blurb:
      "Short, sharp reps. Each one bakes in a habit you'll reach for inside real systems — retries, sanitization, bounded loops.",
    match: (d) => d === "beginner" || d === "easy",
  },
  {
    key: "core",
    eyebrow: "Tier 2 · Core craft",
    title: "Ship the patterns that show up in every senior LLM stack.",
    blurb:
      "Token-aware chunkers, streaming cost meters, defenses you'd put on the prod path.",
    match: (d) => d === "intermediate" || d === "medium",
  },
  {
    key: "capstone",
    eyebrow: "Tier 3 · Capstone",
    title: "Prove the depth that gets you hired into AI roles.",
    blurb:
      "End-to-end RAG plumbing — fusion, reranking, hallucination guardrails.",
    match: (d) => d === "advanced" || d === "hard",
  },
];

const DIFFICULTY_LABEL: Record<string, string> = {
  beginner: "Beginner",
  easy: "Beginner",
  intermediate: "Intermediate",
  medium: "Intermediate",
  advanced: "Advanced",
  hard: "Advanced",
};

function tierFor(diff: string): Tier {
  return TIERS.find((t) => t.match(diff))?.key ?? "core";
}

function ExerciseCard({ ex }: { ex: ExerciseResponse }) {
  return (
    <Link
      href={`/practice/${ex.id}`}
      data-testid="practice-problem-card"
      aria-label={`Open practice problem: ${ex.title}`}
      className="group rounded-xl border border-border/60 bg-card p-5 transition-colors hover:border-primary/40 hover:bg-accent/30"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold leading-snug text-foreground">
            {ex.title}
          </h3>
          {ex.description && (
            <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
              {ex.description}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
              {DIFFICULTY_LABEL[ex.difficulty] ?? ex.difficulty}
            </span>
            <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
              {ex.points} pts
            </span>
          </div>
        </div>
        <ArrowRight
          className="h-4 w-4 text-muted-foreground transition-colors group-hover:text-primary"
          aria-hidden="true"
        />
      </div>
    </Link>
  );
}

export default function PracticeCatalogPage() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const exercisesQuery = useQuery<ExerciseResponse[]>({
    queryKey: ["practice", "catalog"],
    queryFn: () => exercisesApi.list(),
  });

  // TODO(practice-continue): replace this N+1 scan with a dedicated
  // GET /api/v1/practice/continue endpoint that returns the user's most
  // recent non-passed submission in one query. Acceptable at the current
  // ~7-exercise catalog scale; will get expensive past ~30.
  const continueQuery = useQuery<{
    exercise: ExerciseResponse;
    submission: SubmissionResponse;
  } | null>({
    queryKey: ["practice", "continue"],
    enabled: isAuthenticated && (exercisesQuery.data?.length ?? 0) > 0,
    queryFn: async () => {
      const exercises = exercisesQuery.data ?? [];
      for (const ex of exercises) {
        try {
          const subs = await exercisesApi.mySubmissions(ex.id, 1);
          if (subs.length > 0 && subs[0].status !== "passed") {
            return { exercise: ex, submission: subs[0] };
          }
        } catch {
          // ignore per-exercise failures
        }
      }
      return null;
    },
  });

  const grouped = useMemo(() => {
    const out: Record<Tier, ExerciseResponse[]> = {
      foundations: [],
      core: [],
      capstone: [],
    };
    for (const ex of exercisesQuery.data ?? []) {
      out[tierFor(ex.difficulty)].push(ex);
    }
    return out;
  }, [exercisesQuery.data]);

  const total = exercisesQuery.data?.length ?? 0;
  const cont = continueQuery.data;

  return (
    <div className="mx-auto w-full max-w-7xl px-6 py-10">
      <header
        data-testid="practice-header"
        className="mb-8 flex flex-col gap-4 border-b border-border/60 pb-6 sm:flex-row sm:items-end sm:justify-between"
      >
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-primary">
            Practice
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            Build, run, get reviewed by a senior engineer.
          </h1>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">
            Pick a problem, write a solution in the workspace, run it in a
            sandbox, and request an AI senior review when you want feedback.
          </p>
          <p
            data-testid="practice-preview-note"
            className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-300"
          >
            Preview · sandbox isolation pending — internal users only
          </p>
        </div>
        {SCRATCHPAD_ENABLED ? (
          <Link
            href="/practice/scratchpad"
            data-testid="new-scratchpad-btn"
            className="inline-flex h-10 items-center gap-2 self-start rounded-lg border border-primary/30 bg-primary/10 px-4 text-sm font-semibold text-primary hover:bg-primary/15 sm:self-end"
          >
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            New Scratchpad
          </Link>
        ) : (
          <button
            type="button"
            data-testid="new-scratchpad-btn"
            disabled
            title="Coming soon — scratchpad route ships in Phase 2"
            aria-disabled="true"
            className="inline-flex h-10 cursor-not-allowed items-center gap-2 self-start rounded-lg border border-border/60 bg-muted/40 px-4 text-sm font-semibold text-muted-foreground sm:self-end"
          >
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            New Scratchpad
            <span className="ml-1 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider">
              soon
            </span>
          </button>
        )}
      </header>

      {cont && (
        <section
          data-testid="practice-continue"
          className="mb-8 rounded-xl border border-primary/30 bg-primary/5 p-5"
        >
          <p className="text-xs font-semibold uppercase tracking-wider text-primary">
            Continue where you left off
          </p>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-base font-semibold text-foreground">
                {cont.exercise.title}
              </h3>
              <p className="text-xs text-muted-foreground">
                Last attempt — status: {cont.submission.status}
              </p>
            </div>
            <Link
              href={`/practice/${cont.exercise.id}`}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
            >
              Resume <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
          </div>
        </section>
      )}

      {exercisesQuery.isLoading && (
        <div data-testid="practice-loading" className="space-y-6">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-40 animate-pulse rounded-xl border border-border/40 bg-muted/30"
            />
          ))}
        </div>
      )}

      {exercisesQuery.error && (
        <div
          data-testid="practice-error"
          className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive"
        >
          Couldn&apos;t load problems right now. Please refresh.
        </div>
      )}

      {exercisesQuery.data && total === 0 && (
        <div className="rounded-xl border border-dashed border-border bg-muted/20 p-8 text-sm text-muted-foreground">
          No practice problems yet.
        </div>
      )}

      {exercisesQuery.data && total > 0 && (
        <div className="space-y-12">
          {TIERS.map((tier) => {
            const list = grouped[tier.key];
            return (
              <section key={tier.key} data-testid={`tier-${tier.key}`}>
                <header className="mb-4 flex items-end justify-between gap-4">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wider text-primary">
                      {tier.eyebrow}
                    </p>
                    <h2 className="mt-1 text-xl font-semibold text-foreground">
                      {tier.title}
                    </h2>
                    <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                      {tier.blurb}
                    </p>
                  </div>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {list.length} {list.length === 1 ? "problem" : "problems"}
                  </span>
                </header>
                {list.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-border/60 bg-muted/10 p-6 text-sm text-muted-foreground">
                    Nothing in this tier yet.
                  </div>
                ) : (
                  <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                    {list.map((ex) => (
                      <ExerciseCard key={ex.id} ex={ex} />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
