"use client";

import Link from "next/link";
import { Code2, ExternalLink, Loader2 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { exercisesApi, type ExerciseResponse } from "@/lib/api-client";

const diffBadge: Record<string, string> = {
  beginner: "bg-green-100 text-green-700",
  easy: "bg-green-100 text-green-700",
  intermediate: "bg-yellow-100 text-yellow-700",
  medium: "bg-yellow-100 text-yellow-700",
  advanced: "bg-red-100 text-red-700",
  hard: "bg-red-100 text-red-700",
};

export default function ExercisesPage() {
  const { data, isLoading, error } = useQuery<ExerciseResponse[]>({
    queryKey: ["exercises", "list"],
    queryFn: () => exercisesApi.list(),
  });

  return (
    <div className="p-6 md:p-8 max-w-3xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Exercises</h1>
        <p className="text-muted-foreground mt-1">
          Hands-on coding challenges with AI-powered code review.
        </p>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Loading exercises…
        </div>
      )}

      {error && (
        <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-4 py-3 text-sm text-destructive">
          Couldn&apos;t load exercises. Please try again.
        </div>
      )}

      {data && data.length === 0 && (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            No exercises yet. Check back once your course is set up.
          </CardContent>
        </Card>
      )}

      <div className="space-y-3">
        {data?.map((ex) => (
          <Card key={ex.id} className="hover:shadow-sm transition-shadow">
            <CardContent className="flex items-center gap-4 py-4">
              <div className="rounded-lg bg-primary/10 p-2.5 shrink-0">
                <Code2 className="h-5 w-5 text-primary" aria-hidden="true" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">{ex.title}</p>
                <div className="flex items-center gap-2 mt-1">
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${diffBadge[ex.difficulty] ?? "bg-muted text-muted-foreground"}`}
                  >
                    {ex.difficulty}
                  </span>
                  <span className="text-xs text-muted-foreground">{ex.points} pts</span>
                </div>
              </div>
              <Link
                href={`/exercises/${ex.id}`}
                aria-label={`Open exercise: ${ex.title}`}
                className="shrink-0 text-muted-foreground hover:text-primary transition-colors"
              >
                <ExternalLink className="h-4 w-4" />
              </Link>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
