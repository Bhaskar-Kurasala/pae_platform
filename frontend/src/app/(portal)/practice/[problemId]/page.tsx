"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Loader2,
  Play,
  RotateCcw,
  Send,
  Sparkles,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  exercisesApi,
  executeApi,
  practiceApi,
  type ExerciseResponse,
  type SeniorReview,
  type SubmissionResponse,
} from "@/lib/api-client";
import {
  PracticeEditor,
  type PracticeEditorHandle,
} from "@/components/features/practice/practice-editor";
import { AiReviewPanel } from "@/components/features/practice/ai-review-panel";

type Tab = "output" | "review" | "tests" | "history";

interface RunResult {
  stdout: string;
  stderr: string;
  exit_code: number;
  duration_ms?: number;
  timed_out?: boolean;
  error?: string | null;
}

export default function PracticeWorkspacePage({
  params,
}: {
  params: Promise<{ problemId: string }>;
}) {
  const { problemId } = use(params);
  const queryClient = useQueryClient();
  const editorRef = useRef<PracticeEditorHandle>(null);

  const exerciseQuery = useQuery<ExerciseResponse>({
    queryKey: ["practice", "exercise", problemId],
    queryFn: () => exercisesApi.get(problemId),
  });

  const historyQuery = useQuery<SubmissionResponse[]>({
    queryKey: ["practice", "history", problemId],
    queryFn: () => exercisesApi.mySubmissions(problemId),
  });

  const exercise = exerciseQuery.data;

  const [code, setCode] = useState<string>("");
  const [codeInitialized, setCodeInitialized] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>("output");
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [latestReview, setLatestReview] = useState<SeniorReview | null>(null);
  const [reviewBadge, setReviewBadge] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [activeSubmissionId, setActiveSubmissionId] = useState<string | null>(
    null,
  );
  const [submission, setSubmission] = useState<SubmissionResponse | null>(null);
  const [resetConfirm, setResetConfirm] = useState(false);

  const starterCode = exercise?.starter_code ?? "# Write your solution here\n\n";

  useEffect(() => {
    if (!codeInitialized && exercise) {
      setCode(starterCode);
      setCodeInitialized(true);
    }
  }, [exercise, codeInitialized, starterCode]);

  const reviewMutation = useMutation({
    mutationFn: (codeNow: string) =>
      practiceApi.review({
        code: codeNow,
        problem_id: problemId,
        problem_context: exercise?.title,
      }),
    onSuccess: (record) => {
      setLatestReview(record.review);
      setReviewError(null);
      if (activeTab !== "review") setReviewBadge(true);
    },
    onError: (err: unknown) => {
      const msg =
        err instanceof ApiError
          ? "Review unavailable right now — try again in a moment."
          : "Review unavailable right now — try again in a moment.";
      setReviewError(msg);
    },
  });

  const handleRun = useCallback(async () => {
    setRunning(true);
    setRunError(null);
    setActiveTab("output");
    const codeNow = editorRef.current?.getValue() ?? code;
    const startedAt = performance.now();
    try {
      const res = await executeApi.run({ code: codeNow, timeout_seconds: 10 });
      const elapsed = Math.round(performance.now() - startedAt);
      setRunResult({
        stdout: res.stdout,
        stderr: res.stderr,
        exit_code: res.exit_code,
        timed_out: res.timed_out,
        error: res.error,
        duration_ms: elapsed,
      });
    } catch (err) {
      setRunError(
        err instanceof ApiError
          ? err.message
          : "Couldn't reach the sandbox. Try again.",
      );
    } finally {
      setRunning(false);
    }
  }, [code]);

  const handleGetReview = useCallback(() => {
    setReviewError(null);
    setActiveTab("review");
    setReviewBadge(false);
    const codeNow = editorRef.current?.getValue() ?? code;
    reviewMutation.mutate(codeNow);
  }, [code, reviewMutation]);

  const handleSubmit = useCallback(async () => {
    setSubmitting(true);
    setActiveTab("tests");
    setSubmission(null);
    const codeNow = editorRef.current?.getValue() ?? code;
    try {
      const sub = await exercisesApi.submit(problemId, { code: codeNow });
      setSubmission(sub);
      setActiveSubmissionId(sub.id);
    } catch (err) {
      setRunError(
        err instanceof ApiError ? err.message : "Submission failed.",
      );
    } finally {
      setSubmitting(false);
    }
  }, [code, problemId]);

  const handleReset = useCallback(() => {
    if (!resetConfirm) {
      setResetConfirm(true);
      window.setTimeout(() => setResetConfirm(false), 4000);
      return;
    }
    // Update React state *and* push the value into Monaco directly. The
    // @monaco-editor/react `value` prop is initial-only after mount, so the
    // state update alone won't replace the editor's contents.
    setCode(starterCode);
    editorRef.current?.setValue(starterCode);
    setResetConfirm(false);
  }, [resetConfirm, starterCode]);

  // Poll the active submission until graded.
  useEffect(() => {
    if (!activeSubmissionId) return;
    if (submission && submission.status !== "pending") return;
    const id = window.setInterval(async () => {
      try {
        const latest = await exercisesApi.getSubmission(activeSubmissionId);
        setSubmission(latest);
        if (latest.status !== "pending") {
          window.clearInterval(id);
          queryClient.invalidateQueries({
            queryKey: ["practice", "history", problemId],
          });
        }
      } catch {
        /* keep polling */
      }
    }, 3000);
    return () => window.clearInterval(id);
  }, [activeSubmissionId, submission, problemId, queryClient]);

  const handleJumpToLine = useCallback((line: number) => {
    editorRef.current?.revealLine(line);
  }, []);

  const tabs: { key: Tab; label: string; badge?: boolean }[] = useMemo(
    () => [
      { key: "output", label: "Output" },
      { key: "review", label: "AI Review", badge: reviewBadge },
      { key: "tests", label: "Tests" },
      { key: "history", label: "History" },
    ],
    [reviewBadge],
  );

  // Bug-1 fix: when the exercise can't be loaded (404, malformed id, etc.),
  // render a full-screen error and do NOT mount the editor or action bar.
  // Otherwise the user gets a live Submit button that 404s silently.
  if (exerciseQuery.isError) {
    return (
      <div
        data-testid="practice-workspace-error"
        className="flex h-[calc(100vh-3.5rem)] w-full items-center justify-center bg-background p-6"
      >
        <div className="max-w-md text-center">
          <h1 className="text-xl font-semibold text-foreground">
            We couldn&apos;t load this problem.
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            The link may be broken, the problem may have been removed, or you
            may not have access to it.
          </p>
          <Link
            href="/practice"
            className="mt-6 inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to practice catalog
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)] w-full flex-col bg-background">
      {/* Mobile gate */}
      <div
        data-testid="practice-mobile-gate"
        className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground md:hidden"
      >
        Practice works best on desktop. Open this page on a larger screen to
        start coding.
      </div>

      <div className="hidden h-full flex-col md:flex">
        <header className="flex items-center justify-between gap-4 border-b border-border/60 px-6 py-3">
          <div className="flex items-center gap-3">
            <Link
              href="/practice"
              data-testid="back-to-catalog"
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" /> Back
            </Link>
            <span className="text-muted-foreground">/</span>
            <h1
              data-testid="problem-title"
              className="text-sm font-semibold text-foreground"
            >
              {exercise?.title ?? "Loading…"}
            </h1>
            {exercise && (
              <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                {exercise.difficulty}
              </span>
            )}
          </div>
        </header>

        <div className="grid flex-1 grid-cols-[40%_1fr] overflow-hidden">
          {/* Left pane — problem */}
          <aside
            data-testid="problem-pane"
            className="flex flex-col overflow-y-auto border-r border-border/60 bg-card/30 p-6"
          >
            {exerciseQuery.isLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Loading problem…
              </div>
            )}
            {exercise && (
              <>
                <p className="text-xs font-semibold uppercase tracking-wider text-primary">
                  Problem
                </p>
                <h2 className="mt-1 text-xl font-semibold text-foreground">
                  {exercise.title}
                </h2>
                <div className="mt-2 flex flex-wrap gap-2">
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    {exercise.difficulty}
                  </span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    {exercise.points} pts
                  </span>
                </div>
                {exercise.description && (
                  <pre
                    data-testid="problem-description"
                    className="mt-4 whitespace-pre-wrap font-sans text-sm leading-relaxed text-foreground"
                  >
                    {exercise.description}
                  </pre>
                )}
              </>
            )}
          </aside>

          {/* Right pane — editor + output */}
          <section className="flex min-w-0 flex-col">
            <div className="grid flex-1 grid-rows-[1fr_auto_minmax(180px,40%)] overflow-hidden">
              {/* Editor */}
              <div className="min-h-0 p-3">
                <PracticeEditor
                  ref={editorRef}
                  value={code}
                  onChange={setCode}
                  onRun={() => {
                    if (!running) void handleRun();
                  }}
                />
              </div>

              {/* Action bar */}
              <div
                data-testid="action-bar"
                className="flex items-center justify-between gap-2 border-t border-border/60 bg-card/40 px-4 py-2"
              >
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    data-testid="run-btn"
                    onClick={() => void handleRun()}
                    disabled={running}
                    title="Run (Ctrl/Cmd+Enter)"
                    className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                  >
                    {running ? (
                      <Loader2
                        className="h-3.5 w-3.5 animate-spin"
                        aria-hidden="true"
                      />
                    ) : (
                      <Play className="h-3.5 w-3.5" aria-hidden="true" />
                    )}
                    {running ? "Running…" : "Run"}
                  </button>
                  <button
                    type="button"
                    data-testid="review-btn"
                    onClick={handleGetReview}
                    disabled={reviewMutation.isPending}
                    className="inline-flex h-9 items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-3 text-sm font-medium text-primary hover:bg-primary/15 disabled:opacity-50"
                  >
                    {reviewMutation.isPending ? (
                      <Loader2
                        className="h-3.5 w-3.5 animate-spin"
                        aria-hidden="true"
                      />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                    )}
                    {reviewMutation.isPending
                      ? "Reviewing…"
                      : "Get AI Review"}
                  </button>
                  <button
                    type="button"
                    data-testid="submit-btn"
                    onClick={() => void handleSubmit()}
                    disabled={submitting}
                    className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border/60 bg-background px-3 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-50"
                  >
                    {submitting ? (
                      <Loader2
                        className="h-3.5 w-3.5 animate-spin"
                        aria-hidden="true"
                      />
                    ) : (
                      <Send className="h-3.5 w-3.5" aria-hidden="true" />
                    )}
                    {submitting ? "Submitting…" : "Submit"}
                  </button>
                </div>
                <button
                  type="button"
                  data-testid="reset-btn"
                  onClick={handleReset}
                  className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border/60 bg-background px-3 text-xs font-medium text-muted-foreground hover:text-foreground"
                >
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                  {resetConfirm ? "Click again to confirm" : "Reset"}
                </button>
              </div>

              {/* Output panel with tabs */}
              <div className="flex min-h-0 flex-col border-t border-border/60">
                <div className="flex shrink-0 items-center gap-1 border-b border-border/60 bg-card/30 px-2">
                  {tabs.map((t) => (
                    <button
                      key={t.key}
                      type="button"
                      data-testid={`tab-${t.key}`}
                      onClick={() => {
                        setActiveTab(t.key);
                        if (t.key === "review") setReviewBadge(false);
                      }}
                      className={`relative h-9 px-3 text-xs font-medium transition-colors ${
                        activeTab === t.key
                          ? "border-b-2 border-primary text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {t.label}
                      {t.badge && (
                        <span
                          data-testid="review-badge"
                          className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-primary align-middle"
                          aria-label="New review available"
                        />
                      )}
                    </button>
                  ))}
                </div>

                <div
                  data-testid="output-panel"
                  className="flex-1 overflow-y-auto bg-background"
                >
                  {activeTab === "output" && (
                    <div data-testid="output-tab">
                      {runError && (
                        <div className="m-4 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                          {runError}
                        </div>
                      )}
                      {!runResult && !runError && (
                        <div
                          data-testid="output-empty"
                          className="p-6 text-sm text-muted-foreground"
                        >
                          Click <span className="font-medium">Run</span> to
                          execute your code.
                        </div>
                      )}
                      {runResult && (
                        <div className="p-4 font-mono text-xs">
                          <div className="mb-2 flex items-center gap-3 text-muted-foreground">
                            <span data-testid="output-exit-code">
                              exit {runResult.exit_code}
                            </span>
                            {runResult.duration_ms != null && (
                              <span data-testid="output-duration">
                                {runResult.duration_ms} ms
                              </span>
                            )}
                            {runResult.timed_out && (
                              <span className="text-destructive">
                                timed out
                              </span>
                            )}
                          </div>
                          {runResult.stdout && (
                            <pre
                              data-testid="output-stdout"
                              className="whitespace-pre-wrap text-foreground"
                            >
                              {runResult.stdout}
                            </pre>
                          )}
                          {runResult.stderr && (
                            <pre
                              data-testid="output-stderr"
                              className="mt-2 whitespace-pre-wrap text-destructive"
                            >
                              {runResult.stderr}
                            </pre>
                          )}
                          {runResult.error && (
                            <pre className="mt-2 whitespace-pre-wrap text-destructive">
                              {runResult.error}
                            </pre>
                          )}
                          {!runResult.stdout &&
                            !runResult.stderr &&
                            !runResult.error && (
                              <div className="text-muted-foreground">
                                (no output)
                              </div>
                            )}
                        </div>
                      )}
                    </div>
                  )}

                  {activeTab === "review" && (
                    <div data-testid="review-tab">
                      <AiReviewPanel
                        review={latestReview}
                        loading={reviewMutation.isPending}
                        error={reviewError}
                        onJumpToLine={handleJumpToLine}
                      />
                    </div>
                  )}

                  {activeTab === "tests" && (
                    <div data-testid="tests-tab" className="p-4">
                      {!submission && !submitting && (
                        <div className="text-sm text-muted-foreground">
                          Submit to run hidden tests.
                        </div>
                      )}
                      {submitting && !submission && (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          <Loader2
                            className="h-4 w-4 animate-spin"
                            aria-hidden="true"
                          />
                          Submitting…
                        </div>
                      )}
                      {submission && submission.status === "pending" && (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          <Loader2
                            className="h-4 w-4 animate-spin"
                            aria-hidden="true"
                          />
                          Grading…
                        </div>
                      )}
                      {submission && submission.status !== "pending" && (
                        <div className="space-y-3">
                          <div className="flex items-center gap-2 text-sm">
                            <span
                              data-testid="submission-status"
                              className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                                submission.status === "passed"
                                  ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                                  : "bg-destructive/15 text-destructive"
                              }`}
                            >
                              {submission.status}
                            </span>
                            {submission.score != null && (
                              <span className="font-medium text-foreground">
                                {submission.score} pts
                              </span>
                            )}
                          </div>
                          {submission.feedback && (
                            <p className="text-sm text-muted-foreground">
                              {submission.feedback}
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {activeTab === "history" && (
                    <div data-testid="history-tab" className="p-4">
                      {historyQuery.isLoading && (
                        <div className="text-sm text-muted-foreground">
                          Loading history…
                        </div>
                      )}
                      {historyQuery.data && historyQuery.data.length === 0 && (
                        <div className="text-sm text-muted-foreground">
                          No submissions yet.
                        </div>
                      )}
                      {historyQuery.data && historyQuery.data.length > 0 && (
                        <ul className="divide-y divide-border/60 text-sm">
                          {historyQuery.data.map((s) => (
                            <li
                              key={s.id}
                              data-testid="history-row"
                              className="flex items-center justify-between py-2"
                            >
                              <div className="flex items-center gap-3">
                                <span className="tabular-nums text-muted-foreground">
                                  #{s.attempt_number}
                                </span>
                                <span
                                  className={
                                    s.status === "passed"
                                      ? "text-emerald-600 dark:text-emerald-400"
                                      : s.status === "failed"
                                        ? "text-destructive"
                                        : "text-muted-foreground"
                                  }
                                >
                                  {s.status}
                                </span>
                                {s.score != null && (
                                  <span className="font-medium">
                                    {s.score} pts
                                  </span>
                                )}
                              </div>
                              <span className="text-xs text-muted-foreground tabular-nums">
                                {new Date(s.created_at).toLocaleString()}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
