"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, History, Loader2, Send, Star } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  ApiError,
  exercisesApi,
  type ExerciseResponse,
  type SubmissionResponse,
} from "@/lib/api-client";
import { PeerGallery } from "@/components/features/peer-gallery";
import { SelfExplanationModal } from "@/components/features/self-explanation-modal";

const CODE_MIN = 1;
const CODE_MAX = 20000;

function formatRubric(rubric: Record<string, unknown> | null | undefined) {
  if (!rubric) return null;
  const entries = Object.entries(rubric).filter(([, v]) => v != null);
  if (entries.length === 0) return null;
  return entries;
}

export default function ExerciseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const exerciseQuery = useQuery<ExerciseResponse>({
    queryKey: ["exercise", id],
    queryFn: () => exercisesApi.get(id),
  });

  const historyQuery = useQuery<SubmissionResponse[]>({
    queryKey: ["exercise", id, "mine"],
    queryFn: () => exercisesApi.mySubmissions(id),
  });

  const exercise = exerciseQuery.data;

  const [code, setCode] = useState<string>("");
  const [codeInitialized, setCodeInitialized] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [activeSubmissionId, setActiveSubmissionId] = useState<string | null>(null);
  const [result, setResult] = useState<SubmissionResponse | null>(null);
  const [error, setError] = useState("");
  const [share, setShare] = useState(false);
  const [shareNote, setShareNote] = useState("");
  const [explainOpen, setExplainOpen] = useState(false);

  useEffect(() => {
    if (!codeInitialized && exercise) {
      setCode(exercise.starter_code ?? `# Write your solution here\n\n`);
      setCodeInitialized(true);
    }
  }, [exercise, codeInitialized]);

  // Poll the active submission every 3s while it's still pending.
  useEffect(() => {
    if (!activeSubmissionId) return;
    if (result && result.status !== "pending") return;
    const id = setInterval(async () => {
      try {
        const latest = await exercisesApi.getSubmission(activeSubmissionId);
        setResult(latest);
        if (latest.status !== "pending") {
          clearInterval(id);
          historyQuery.refetch();
          if (latest.status === "passed" && typeof window !== "undefined") {
            window.dispatchEvent(
              new CustomEvent("exercise.passed", {
                detail: { submission_id: latest.id, exercise_id: latest.exercise_id },
              }),
            );
          }
        }
      } catch {
        // ignore transient errors; keep polling
      }
    }, 3000);
    return () => clearInterval(id);
  }, [activeSubmissionId, result, historyQuery]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const trimmed = code.trim();
    if (trimmed.length < CODE_MIN) {
      setError("Please write some code before submitting.");
      return;
    }
    if (code.length > CODE_MAX) {
      setError(`Code is too long — ${code.length}/${CODE_MAX} characters.`);
      return;
    }
    setResult(null);
    setExplainOpen(true);
  }

  async function performSubmit(selfExplanation: string) {
    setSubmitting(true);
    try {
      const sub = await exercisesApi.submit(id, {
        code,
        shared_with_peers: share,
        share_note: share ? shareNote.trim() || undefined : undefined,
        self_explanation: selfExplanation || undefined,
      });
      setResult(sub);
      setActiveSubmissionId(sub.id);
      setExplainOpen(false);
      historyQuery.refetch();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Submission failed. Please try again.");
      }
      setExplainOpen(false);
    } finally {
      setSubmitting(false);
    }
  }

  const rubricEntries = formatRubric(exercise?.rubric);
  const overLimit = code.length > CODE_MAX;

  if (exerciseQuery.isLoading) {
    return (
      <div className="p-6 md:p-8 max-w-3xl mx-auto">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  if (exerciseQuery.error || !exercise) {
    return (
      <div className="p-6 md:p-8 max-w-3xl mx-auto">
        <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-4 py-3 text-sm text-destructive">
          Exercise not found.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-3xl mx-auto space-y-6">
      <Link
        href="/exercises"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back to exercises
      </Link>

      <div>
        <h1 className="text-2xl font-bold">{exercise.title}</h1>
        <div className="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
          <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 font-medium">
            {exercise.difficulty}
          </span>
          <span>{exercise.points} pts</span>
        </div>
      </div>

      {exercise.description && (
        <div className="rounded-xl border bg-card p-5">
          <h2 className="font-semibold mb-2">Prompt</h2>
          <pre className="whitespace-pre-wrap text-sm leading-relaxed font-sans">
            {exercise.description}
          </pre>
        </div>
      )}

      {rubricEntries && (
        <div className="rounded-xl border bg-card p-5">
          <h2 className="font-semibold mb-2">Rubric</h2>
          <ul className="text-sm space-y-1">
            {rubricEntries.map(([k, v]) => (
              <li key={k}>
                <span className="font-medium">{k}:</span>{" "}
                <span className="text-muted-foreground">
                  {typeof v === "string" || typeof v === "number"
                    ? String(v)
                    : JSON.stringify(v)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <div className="flex items-center justify-between mb-2">
            <label htmlFor="code-editor" className="block text-sm font-medium">
              Your solution
            </label>
            <span
              className={`text-xs ${overLimit ? "text-destructive" : "text-muted-foreground"}`}
            >
              {code.length}/{CODE_MAX}
            </span>
          </div>
          <textarea
            id="code-editor"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            rows={18}
            maxLength={CODE_MAX}
            spellCheck={false}
            className="w-full rounded-xl border bg-[#111827] text-green-300 font-mono text-sm p-4 outline-none focus:ring-2 focus:ring-primary/50 resize-y"
            aria-label="Code editor"
          />
        </div>

        <div className="rounded-lg border border-foreground/10 bg-card p-3">
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={share}
              onChange={(e) => setShare(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-foreground/20"
              aria-label="Share this submission with peers"
            />
            <span>
              <span className="font-medium">Share with peers (anonymous)</span>
              <span className="block text-xs text-muted-foreground">
                Others see your code under a handle like{" "}
                <code className="font-mono">peer_3fa7</code> — no name or email.
              </span>
            </span>
          </label>
          {share ? (
            <input
              type="text"
              value={shareNote}
              onChange={(e) => setShareNote(e.target.value)}
              placeholder="Optional — what should peers notice about your approach?"
              maxLength={500}
              className="mt-2 w-full rounded-md border border-foreground/10 bg-background px-3 py-1.5 text-sm"
              aria-label="Share note"
            />
          ) : null}
        </div>

        {error && (
          <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting || overLimit}
          className="inline-flex items-center gap-2 h-10 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60 transition-colors"
        >
          {submitting ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Send className="h-4 w-4" aria-hidden="true" />
          )}
          {submitting ? "Submitting…" : "Submit for review"}
        </button>
      </form>

      {result && (
        <div className="rounded-xl border bg-card p-5 space-y-3">
          <div className="flex items-center gap-2">
            <Star className="h-5 w-5 text-yellow-500" aria-hidden="true" />
            <h2 className="font-semibold">
              {result.status === "pending" ? "Grading…" : "Graded"}
            </h2>
          </div>
          {result.status === "pending" ? (
            <p className="text-sm text-muted-foreground">
              Your submission is queued. The grade should appear within ~10s.
            </p>
          ) : (
            <>
              {result.score != null && (
                <p className="text-sm">
                  Score:{" "}
                  <span className="font-bold text-primary">{result.score} pts</span>
                </p>
              )}
              {result.feedback && (
                <div>
                  <p className="text-sm font-medium mb-1">AI Feedback</p>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    {result.feedback}
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {historyQuery.data && historyQuery.data.length > 0 && (
        <div className="rounded-xl border bg-card p-5">
          <h2 className="font-semibold mb-3 inline-flex items-center gap-2">
            <History className="h-4 w-4" /> Previous attempts
          </h2>
          <ul className="divide-y text-sm">
            {historyQuery.data.map((s) => (
              <li key={s.id} className="flex items-center justify-between py-2">
                <div className="flex items-center gap-3">
                  <span className="text-muted-foreground tabular-nums">
                    #{s.attempt_number}
                  </span>
                  <span
                    className={
                      s.status === "passed"
                        ? "text-green-600 dark:text-green-400"
                        : s.status === "failed"
                          ? "text-destructive"
                          : "text-muted-foreground"
                    }
                  >
                    {s.status}
                  </span>
                  {s.score != null && (
                    <span className="font-medium">{s.score} pts</span>
                  )}
                </div>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {new Date(s.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <PeerGallery exerciseId={id} />

      <SelfExplanationModal
        open={explainOpen}
        submitting={submitting}
        onConfirm={(explanation) => void performSubmit(explanation)}
        onCancel={() => setExplainOpen(false)}
      />
    </div>
  );
}
