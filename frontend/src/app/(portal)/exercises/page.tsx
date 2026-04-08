"use client";

import { Code2, ExternalLink } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

// Placeholder data — will be populated once exercises endpoint returns a list
const MOCK_EXERCISES = [
  {
    id: "ex-1",
    title: "Build a LangGraph ReAct Agent",
    difficulty: "intermediate",
    status: "not_started",
    points: 100,
  },
  {
    id: "ex-2",
    title: "Implement RAG with Pinecone",
    difficulty: "advanced",
    status: "submitted",
    points: 150,
  },
  {
    id: "ex-3",
    title: "Streaming FastAPI Endpoint",
    difficulty: "beginner",
    status: "graded",
    points: 75,
  },
];

const statusBadge: Record<string, { label: string; className: string }> = {
  not_started: { label: "Not started", className: "bg-muted text-muted-foreground" },
  submitted: { label: "Submitted", className: "bg-yellow-100 text-yellow-700" },
  graded: { label: "Graded", className: "bg-green-100 text-green-700" },
};

const diffBadge: Record<string, string> = {
  beginner: "bg-green-100 text-green-700",
  intermediate: "bg-yellow-100 text-yellow-700",
  advanced: "bg-red-100 text-red-700",
};

export default function ExercisesPage() {
  return (
    <div className="p-6 md:p-8 max-w-3xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Exercises</h1>
        <p className="text-muted-foreground mt-1">
          Hands-on coding challenges with AI-powered code review.
        </p>
      </div>

      <div className="space-y-3">
        {MOCK_EXERCISES.map((ex) => {
          const status = statusBadge[ex.status] ?? statusBadge.not_started;
          return (
            <Card key={ex.id} className="hover:shadow-sm transition-shadow">
              <CardContent className="flex items-center gap-4 py-4">
                <div className="rounded-lg bg-primary/10 p-2.5 shrink-0">
                  <Code2 className="h-5 w-5 text-primary" aria-hidden="true" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate">{ex.title}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${diffBadge[ex.difficulty] ?? ""}`}
                    >
                      {ex.difficulty}
                    </span>
                    <span className="text-xs text-muted-foreground">{ex.points} pts</span>
                  </div>
                </div>
                <span
                  className={`shrink-0 inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${status.className}`}
                >
                  {status.label}
                </span>
                <a
                  href={`/exercises/${ex.id}`}
                  aria-label={`Open exercise: ${ex.title}`}
                  className="shrink-0 text-muted-foreground hover:text-primary transition-colors"
                >
                  <ExternalLink className="h-4 w-4" />
                </a>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
