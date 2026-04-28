"use client";

/**
 * P-Practice1 (2026-04-28) — unified `/practice` workspace.
 *
 * Merges the previously fragmented Exercises + Studio + Practice trio into
 * a single v8 surface that matches the `CareerForge v10 — Capstone bundle`
 * mock. The screen carries a real Monaco-backed editor, real Run+Review
 * round-trips against the backend sandbox, and Save-to-Notebook with a free-
 * form student note (mirroring the Tutor save flow).
 *
 * Modes
 *   - capstone   → labs from the active path level shown as a file tree.
 *   - exercises  → full exercise catalog in a grouped task list.
 *
 * Both modes share the same code/output/review state — the toggle is purely
 * about WHAT the rail picks; the editor never gets thrown away mid-thought.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import {
  BookmarkPlus,
  Check,
  ChevronRight,
  Code2,
  FileCode,
  FileText,
  FolderClosed,
  Lock,
  Play,
  Sparkles,
  TerminalSquare,
} from "lucide-react";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { v8Toast } from "@/components/v8/v8-toast";
import {
  executeApi,
  exercisesApi,
  type ExecuteResponse,
  type ExerciseResponse,
} from "@/lib/api-client";
import { chatApi } from "@/lib/chat-api";
import { useSeniorReview } from "@/lib/hooks/use-senior-review";
import { usePracticeWorkspace } from "@/lib/hooks/use-practice-workspace";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

const Monaco = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
      Loading editor…
    </div>
  ),
});

type PracticeMode = "capstone" | "exercises";

const STORAGE_KEY = "practice.code.v1";
const STARTER_CAPSTONE = `# CareerForge capstone · CLI AI Tool
import os
import asyncio
from anthropic import Anthropic, APIError

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

async def ask_claude(prompt: str) -> str:
    for attempt in range(3):
        try:
            resp = await client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text
        except APIError:
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError("Request failed after retries")

if __name__ == "__main__":
    print(asyncio.run(ask_claude("hello")))
`;
interface SaveDialogState {
  open: boolean;
  note: string;
  status: "idle" | "saving" | "saved" | "error";
}

function pluralLabs(n: number): string {
  return n === 1 ? "lab" : "labs";
}

function reviewItemsFrom(
  data: ReturnType<typeof useSeniorReview>["data"],
): Array<{ variant: "good" | "warn" | "todo"; heading: string; body: string }> {
  if (!data) {
    return [
      {
        variant: "good",
        heading: "Awaiting senior review",
        body: "Click Run & review to send your code for a PR-style read.",
      },
    ];
  }
  const items: Array<{
    variant: "good" | "warn" | "todo";
    heading: string;
    body: string;
  }> = [];
  if (data.strengths.length > 0) {
    items.push({
      variant: "good",
      heading: "What is working",
      body: data.strengths[0],
    });
  }
  const concern = data.comments.find(
    (c) => c.severity === "concern" || c.severity === "blocking",
  );
  if (concern) {
    items.push({
      variant: "warn",
      heading: `Close this gap (line ${concern.line})`,
      body: concern.message,
    });
  }
  if (data.next_step) {
    items.push({
      variant: "todo",
      heading: "Before submission",
      body: data.next_step,
    });
  }
  if (items.length === 0) {
    items.push({
      variant: "good",
      heading: data.headline || "Reviewed",
      body: "Nothing flagged. Ship it.",
    });
  }
  return items;
}

function readStoredCode(): string {
  if (typeof window === "undefined") return STARTER_CAPSTONE;
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? STARTER_CAPSTONE;
  } catch {
    return STARTER_CAPSTONE;
  }
}

export function PracticeScreen() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  const { resolvedTheme } = useTheme();

  const initialMode: PracticeMode =
    searchParams.get("mode") === "exercises" ? "exercises" : "capstone";
  const initialTaskId = searchParams.get("task");
  const labParam = searchParams.get("lab");

  const [mode, setMode] = useState<PracticeMode>(initialMode);
  const [selectedExerciseId, setSelectedExerciseId] = useState<string | null>(
    initialTaskId,
  );
  const [code, setCode] = useState<string>(readStoredCode);
  const [runResult, setRunResult] = useState<ExecuteResponse | null>(null);
  const [activeTab, setActiveTab] = useState<"code" | "trace" | "tests">("code");
  const [saveDialog, setSaveDialog] = useState<SaveDialogState>({
    open: false,
    note: "",
    status: "idle",
  });
  const seniorReview = useSeniorReview();
  const codeChangedSinceMount = useRef(false);

  // ── data ────────────────────────────────────────────────────────────
  const workspace = usePracticeWorkspace();

  // P-Path1 deep-link: /practice?lab=B comes from My Path. We resolve to the
  // matching exercise the first time exercises load, then strip the param so
  // refreshes don't repeatedly re-seed.
  useEffect(() => {
    if (!labParam || !workspace.exercises.length) return;
    // Lab tokens are letters in the mock; map A→0, B→1, C→2, etc.
    const idx =
      labParam.length === 1
        ? labParam.toUpperCase().charCodeAt(0) - "A".charCodeAt(0)
        : Number(labParam) - 1;
    if (idx >= 0 && idx < workspace.exercises.length) {
      const ex = workspace.exercises[idx];
      setMode("exercises");
      setSelectedExerciseId(ex.id);
    }
  }, [labParam, workspace.exercises]);

  // ── selected exercise (full record, with starter_code) ──────────────
  const [selectedExerciseDetail, setSelectedExerciseDetail] =
    useState<ExerciseResponse | null>(null);
  useEffect(() => {
    let cancelled = false;
    if (!selectedExerciseId) {
      setSelectedExerciseDetail(null);
      return;
    }
    void exercisesApi
      .get(selectedExerciseId)
      .then((ex) => {
        if (cancelled) return;
        setSelectedExerciseDetail(ex);
        // Seed the editor with starter_code only if the user hasn't typed
        // anything yet for this session. (`codeChangedSinceMount` flips to
        // true on first onChange.)
        if (!codeChangedSinceMount.current && ex.starter_code) {
          setCode(ex.starter_code);
        }
      })
      .catch(() => {
        if (!cancelled) setSelectedExerciseDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedExerciseId]);

  // ── persistent local code draft ─────────────────────────────────────
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(STORAGE_KEY, code);
    } catch {
      /* quota / disabled — ignore */
    }
  }, [code]);

  // ── topbar wiring ───────────────────────────────────────────────────
  const titleSuffix =
    mode === "capstone"
      ? workspace.capstone?.title ?? workspace.activeCourseTitle ?? "your capstone"
      : selectedExerciseDetail?.title ?? "an exercise";
  useSetV8Topbar({
    eyebrow: mode === "capstone" ? "Practice · Capstone" : "Practice · Exercises",
    titleHtml: `Write code, get senior review, ship the proof — <i>${titleSuffix}</i>.`,
    chips: [],
    progress: runResult?.quality?.score ?? 0,
  });

  // ── mode + selection ────────────────────────────────────────────────
  const switchMode = useCallback(
    (next: PracticeMode) => {
      setMode(next);
      const params = new URLSearchParams(Array.from(searchParams.entries()));
      params.set("mode", next);
      params.delete("lab");
      router.replace(`/practice?${params.toString()}`);
    },
    [router, searchParams],
  );

  const selectExercise = useCallback((id: string, starter: string | null) => {
    setSelectedExerciseId(id);
    if (starter && !codeChangedSinceMount.current) {
      setCode(starter);
    }
  }, []);

  // ── run + review pipeline ──────────────────────────────────────────
  const [running, setRunning] = useState(false);
  const handleRun = useCallback(async () => {
    if (!isAuthed) {
      v8Toast("Sign in to run code in the sandbox.");
      return;
    }
    setRunning(true);
    setActiveTab("trace");
    try {
      const result = await executeApi.run({ code });
      setRunResult(result);
    } catch {
      v8Toast("Run failed. Try again in a moment.");
    } finally {
      setRunning(false);
    }
  }, [code, isAuthed]);

  const handleRequestReview = useCallback(() => {
    if (!isAuthed) {
      v8Toast("Sign in to request a senior review.");
      return;
    }
    const ex = selectedExerciseDetail;
    const problemContext =
      mode === "exercises" && ex
        ? `Exercise: ${ex.title}\n\n${ex.description ?? ""}`.slice(0, 1900)
        : mode === "capstone" && workspace.capstone
          ? `Capstone: ${workspace.capstone.title}\n\n${workspace.capstone.blurb}`.slice(
              0,
              1900,
            )
          : undefined;
    seniorReview.mutate({ code, problemContext });
  }, [code, isAuthed, mode, selectedExerciseDetail, seniorReview, workspace.capstone]);

  const handleRunAndReview = useCallback(async () => {
    await handleRun();
    handleRequestReview();
  }, [handleRequestReview, handleRun]);

  // ── save to notebook ───────────────────────────────────────────────
  const openSaveDialog = useCallback(() => {
    if (!isAuthed) {
      v8Toast("Sign in to save notes.");
      return;
    }
    setSaveDialog({ open: true, note: "", status: "idle" });
  }, [isAuthed]);

  const closeSaveDialog = useCallback(() => {
    setSaveDialog({ open: false, note: "", status: "idle" });
  }, []);

  const handleSaveNote = useCallback(async () => {
    setSaveDialog((s) => ({ ...s, status: "saving" }));
    const stdout = runResult?.stdout?.trim() ?? "";
    const titleAnchor =
      mode === "exercises"
        ? selectedExerciseDetail?.title ?? "Practice exercise"
        : workspace.capstone?.title ?? "Practice capstone";
    const content = [
      `**${titleAnchor}**`,
      "",
      "```python",
      code.trim(),
      "```",
      stdout
        ? ["", "**Output**", "```", stdout, "```"].join("\n")
        : "",
    ]
      .filter(Boolean)
      .join("\n");
    try {
      await chatApi.saveToNotebook({
        messageId: `practice-${Date.now()}`,
        conversationId: "practice",
        content,
        title: `Practice · ${titleAnchor}`,
        sourceType: "studio",
        topic: "code-practice",
        userNote: saveDialog.note.trim() || undefined,
        tags: [mode === "exercises" ? "exercise" : "capstone"],
      });
      setSaveDialog((s) => ({ ...s, status: "saved" }));
      v8Toast("Saved to Notebook.");
      window.setTimeout(closeSaveDialog, 900);
    } catch {
      setSaveDialog((s) => ({ ...s, status: "error" }));
    }
  }, [
    closeSaveDialog,
    code,
    mode,
    runResult,
    saveDialog.note,
    selectedExerciseDetail?.title,
    workspace.capstone?.title,
  ]);

  // ── derived view-data ──────────────────────────────────────────────
  const reviewItems = useMemo(() => reviewItemsFrom(seniorReview.data), [
    seniorReview.data,
  ]);
  const qualityScore = runResult?.quality?.score ?? null;
  const showStdoutInTrace = activeTab === "trace";
  const showTestsTab = activeTab === "tests";

  // ── render ─────────────────────────────────────────────────────────
  return (
    <section className="screen active" id="screen-practice">
      <div className="pad" data-testid="practice-screen">
        {/* Slim breadcrumb-style header */}
        <div className="practice-bar reveal">
          <div className="pbar-crumbs">
            <span className="pbar-root">Practice</span>
            <span className="pbar-sep">/</span>
            <span className="pbar-crumb-ctx">
              {mode === "capstone" ? "Capstone" : "Exercises"}
            </span>
          </div>
          <div className="pbar-title">{titleSuffix}</div>
          <div
            className="pbar-modes"
            role="tablist"
            aria-label="Practice modes"
          >
            <button
              type="button"
              role="tab"
              aria-selected={mode === "exercises"}
              data-testid="mode-exercises"
              className={cn("pmode", mode === "exercises" && "active")}
              onClick={() => switchMode("exercises")}
            >
              Exercises
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "capstone"}
              data-testid="mode-capstone"
              className={cn("pmode", mode === "capstone" && "active")}
              onClick={() => switchMode("capstone")}
            >
              Capstone <span className="pmode-tag">Gate</span>
            </button>
          </div>
        </div>

        <div className="practice-grid">
          {/* ─── LEFT RAIL ─── */}
          <aside className="practice-rail reveal" data-testid="practice-rail">
            <div className="rail-expanded">
              {mode === "capstone" ? (
                <CapstoneRail
                  capstone={workspace.capstone}
                  loading={workspace.isLoading}
                  selectedLabId={selectedExerciseId}
                  onSelectLab={(id) => selectExercise(id, null)}
                />
              ) : (
                <ExerciseRail
                  exercises={workspace.exercises}
                  loading={workspace.isLoading}
                  selectedId={selectedExerciseId}
                  onSelect={(ex) => selectExercise(ex.id, ex.starter_code ?? null)}
                />
              )}
            </div>
          </aside>

          {/* ─── CENTER: editor + tabs ─── */}
          <section className="editor practice-editor reveal">
            <div className="editor-bar">
              <div className="editor-tabs">
                <button
                  type="button"
                  className={cn("editor-tab", activeTab === "code" && "active")}
                  onClick={() => setActiveTab("code")}
                  data-testid="tab-code"
                >
                  <Code2 className="inline-block h-3 w-3 mr-1" /> main.py
                </button>
                <button
                  type="button"
                  className={cn("editor-tab", activeTab === "trace" && "active")}
                  onClick={() => setActiveTab("trace")}
                  data-testid="tab-trace"
                >
                  <TerminalSquare className="inline-block h-3 w-3 mr-1" /> Output
                </button>
                <button
                  type="button"
                  className={cn("editor-tab", activeTab === "tests" && "active")}
                  onClick={() => setActiveTab("tests")}
                  data-testid="tab-tests"
                >
                  Tests
                </button>
              </div>
              <div className="editor-actions">
                <span className="editor-status">
                  {qualityScore !== null
                    ? `Quality ${qualityScore}/100`
                    : "Ready to run"}
                </span>
                <button
                  type="button"
                  className="editor-btn"
                  onClick={openSaveDialog}
                  data-testid="save-to-notebook"
                  aria-label="Save to notebook"
                >
                  <BookmarkPlus className="inline-block h-3 w-3 mr-1" />
                  Save to Notebook
                </button>
                <button
                  type="button"
                  className={cn("editor-btn run", running && "running")}
                  onClick={handleRunAndReview}
                  disabled={running || seniorReview.isPending}
                  data-testid="run-and-review"
                  aria-label="Run and review"
                >
                  <Play className="inline-block h-3 w-3 mr-1" />
                  {running
                    ? "Running…"
                    : seniorReview.isPending
                      ? "Reviewing…"
                      : "Run & review"}
                </button>
              </div>
            </div>

            {activeTab === "code" ? (
              <div className="practice-monaco-shell">
                <Monaco
                  height="560px"
                  defaultLanguage="python"
                  language="python"
                  value={code}
                  onChange={(v) => {
                    codeChangedSinceMount.current = true;
                    setCode(v ?? "");
                  }}
                  theme={resolvedTheme === "dark" ? "vs-dark" : "light"}
                  options={{
                    minimap: { enabled: false },
                    fontSize: 13,
                    tabSize: 4,
                    scrollBeyondLastLine: false,
                    automaticLayout: true,
                    wordWrap: "on",
                    padding: { top: 8, bottom: 8 },
                  }}
                />
              </div>
            ) : showStdoutInTrace ? (
              <OutputPane result={runResult} />
            ) : showTestsTab ? (
              <TestsPane result={runResult} />
            ) : null}
          </section>

          {/* ─── RIGHT RAIL: review panel ─── */}
          <aside
            className="review-panel practice-review reveal delay-1"
            data-testid="practice-review"
          >
            <div className="mentor-pulse">Senior review</div>
            <h4>
              {seniorReview.data?.headline ?? "Responsive guidance, not noisy grading"}
            </h4>
            <p>
              The reviewer reads your code with production eyes. Strengths,
              gaps, and one concrete next step.
            </p>

            <div className="score-ring">
              <div className="score-wheel">
                <strong>{qualityScore ?? "—"}</strong>
              </div>
              <div>
                <strong>Production readiness</strong>
                <div className="small">
                  {qualityScore !== null
                    ? runResult?.quality?.summary || "Code analysed."
                    : "Run the code to see a quality score."}
                </div>
              </div>
            </div>

            <div className="review-stack">
              {reviewItems.map((item, idx) => (
                <div
                  key={`${item.heading}-${idx}`}
                  className={`review-item show ${item.variant}`}
                >
                  <strong>{item.heading}</strong>
                  <span>{item.body}</span>
                </div>
              ))}
              {seniorReview.isError ? (
                <div className="review-item show warn">
                  <strong>Review unavailable</strong>
                  <span>
                    Couldn&apos;t reach the reviewer. Run again in a moment.
                  </span>
                </div>
              ) : null}
            </div>

            <div className="ask-box">
              <button
                type="button"
                className="btn ghost w-full"
                onClick={handleRequestReview}
                disabled={seniorReview.isPending}
                data-testid="request-review"
              >
                <Sparkles className="inline-block h-3 w-3 mr-1" />
                {seniorReview.isPending ? "Requesting…" : "Request review only"}
              </button>
            </div>
          </aside>
        </div>
      </div>

      {saveDialog.open ? (
        <SaveDialog
          state={saveDialog}
          onClose={closeSaveDialog}
          onChangeNote={(note) => setSaveDialog((s) => ({ ...s, note }))}
          onSave={handleSaveNote}
        />
      ) : null}
    </section>
  );
}

// ───────────────────────────────────────────────────────────────────────
// Sub-components
// ───────────────────────────────────────────────────────────────────────

interface CapstoneRailProps {
  capstone: ReturnType<typeof usePracticeWorkspace>["capstone"];
  loading: boolean;
  selectedLabId: string | null;
  onSelectLab: (id: string) => void;
}

function CapstoneRail({
  capstone,
  loading,
  selectedLabId,
  onSelectLab,
}: CapstoneRailProps) {
  if (loading) {
    return (
      <div className="rail-eyebrow" aria-busy="true">
        Loading bundle…
      </div>
    );
  }
  if (!capstone) {
    return (
      <div>
        <div className="rail-eyebrow">No capstone yet</div>
        <p className="small" style={{ padding: "10px 8px" }}>
          Enroll in a track to unlock a capstone bundle. Until then, switch to{" "}
          <b>Exercises</b>.
        </p>
      </div>
    );
  }
  return (
    <div data-testid="capstone-rail">
      <div className="rail-eyebrow">
        Bundle · {capstone.title}
        <span className="rail-count gold">{capstone.labs.length} labs</span>
      </div>
      <div className="tree-root">
        <div className="tree-folder">
          <FolderClosed className="inline-block h-3 w-3" />
          <span>capstone/</span>
        </div>
        <div className="tree-children">
          {capstone.labs.map((lab) => {
            const isLocked = lab.status === "locked";
            const isActive = lab.id === selectedLabId;
            return (
              <button
                key={lab.id}
                type="button"
                className={cn(
                  "tree-file editable",
                  isActive && "active",
                  isLocked && "locked",
                )}
                onClick={() => !isLocked && onSelectLab(lab.id)}
                disabled={isLocked}
                data-testid={`capstone-lab-${lab.id}`}
              >
                {isLocked ? (
                  <Lock className="tf-icon h-3 w-3" />
                ) : (
                  <FileCode className="tf-icon h-3 w-3" />
                )}
                <span className="tf-name">{lab.title}</span>
                <span className="tf-badge">
                  {isLocked ? "Locked" : lab.status === "done" ? "Done" : "Edit"}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

interface ExerciseRailProps {
  exercises: ExerciseResponse[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (ex: ExerciseResponse) => void;
}

function ExerciseRail({
  exercises,
  loading,
  selectedId,
  onSelect,
}: ExerciseRailProps) {
  const grouped = useMemo(() => {
    const out: Record<string, ExerciseResponse[]> = {
      Foundations: [],
      "Core craft": [],
      Capstone: [],
    };
    for (const ex of exercises) {
      const d = (ex.difficulty || "").toLowerCase();
      if (d === "beginner" || d === "easy") out.Foundations.push(ex);
      else if (d === "advanced" || d === "hard") out.Capstone.push(ex);
      else out["Core craft"].push(ex);
    }
    return out;
  }, [exercises]);

  if (loading) {
    return (
      <div className="rail-eyebrow" aria-busy="true">
        Loading exercises…
      </div>
    );
  }
  if (exercises.length === 0) {
    return (
      <div>
        <div className="rail-eyebrow">No exercises yet</div>
        <p className="small" style={{ padding: "10px 8px" }}>
          Your instructor hasn&apos;t published any exercises. Try{" "}
          <b>Capstone</b> mode.
        </p>
      </div>
    );
  }
  return (
    <div data-testid="exercise-rail">
      <div className="rail-eyebrow">
        Exercises · {exercises.length}
        <span className="rail-count">{pluralLabs(exercises.length)}</span>
      </div>
      {Object.entries(grouped).map(([groupLabel, list]) =>
        list.length === 0 ? null : (
          <div className="rail-group" key={groupLabel}>
            <div className="rail-group-h">{groupLabel}</div>
            {list.map((ex) => (
              <button
                key={ex.id}
                type="button"
                className={cn("rail-task", ex.id === selectedId && "active")}
                onClick={() => onSelect(ex)}
                data-testid={`exercise-task-${ex.id}`}
              >
                <span className="task-dot" />
                <span className="task-n">{ex.title}</span>
                <ChevronRight className="h-3 w-3 text-muted-foreground" />
              </button>
            ))}
          </div>
        ),
      )}
    </div>
  );
}

interface OutputPaneProps {
  result: ExecuteResponse | null;
}

function OutputPane({ result }: OutputPaneProps) {
  if (!result) {
    return (
      <div className="trace-shell" data-testid="output-pane-empty">
        <p className="small">No output yet — click Run & review to execute.</p>
      </div>
    );
  }
  const { stdout, stderr, exit_code, timed_out, error } = result;
  return (
    <div className="trace-shell" data-testid="output-pane">
      <div className="tests-summary">
        Exit code <strong>{exit_code}</strong>
        <span className="tests-time">
          {" "}
          · {timed_out ? "timed out" : `${result.events.length} steps traced`}
        </span>
      </div>
      {error ? (
        <pre className="break-shell" style={{ color: "var(--rose)" }}>
          {error}
        </pre>
      ) : null}
      {stdout ? (
        <div>
          <div className="rail-eyebrow">stdout</div>
          <pre>{stdout}</pre>
        </div>
      ) : null}
      {stderr ? (
        <div>
          <div className="rail-eyebrow">stderr</div>
          <pre style={{ color: "var(--rose)" }}>{stderr}</pre>
        </div>
      ) : null}
    </div>
  );
}

interface TestsPaneProps {
  result: ExecuteResponse | null;
}

function TestsPane({ result }: TestsPaneProps) {
  const issues = result?.quality?.issues ?? [];
  if (!result) {
    return (
      <div className="tests-shell" data-testid="tests-pane-empty">
        <p className="small">
          Quality issues appear after the first run. Click Run & review.
        </p>
      </div>
    );
  }
  if (issues.length === 0) {
    return (
      <div className="tests-shell" data-testid="tests-pane">
        <div className="test-row pass">
          <span className="test-ic">✓</span>
          <div className="test-body">
            <b>No quality issues</b>
            <span>Code passes the quality analyser. Ship it.</span>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="tests-shell" data-testid="tests-pane">
      <div className="tests-summary">
        <strong>{issues.length}</strong> quality{" "}
        {issues.length === 1 ? "issue" : "issues"}
        <span className="tests-time">
          {" "}
          · score {result.quality?.score ?? 0}/100
        </span>
      </div>
      {issues.map((it, idx) => (
        <div
          key={`${it.rule}-${idx}`}
          className={cn(
            "test-row",
            it.severity === "warning" ? "fail" : "pass",
          )}
        >
          <span className="test-ic">
            {it.severity === "warning" ? "!" : "·"}
          </span>
          <div className="test-body">
            <b>
              {it.rule} <span className="small">(line {it.line})</span>
            </b>
            <span>{it.message}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

interface SaveDialogProps {
  state: SaveDialogState;
  onClose: () => void;
  onChangeNote: (note: string) => void;
  onSave: () => void;
}

function SaveDialog({ state, onClose, onChangeNote, onSave }: SaveDialogProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="practice-save-title"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(16,18,14,0.55)",
        backdropFilter: "blur(4px)",
        zIndex: 80,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card pad"
        style={{
          maxWidth: 540,
          width: "100%",
          maxHeight: "calc(100vh - 48px)",
          overflow: "auto",
          background: "var(--cream-1, #f7f3ea)",
          boxShadow: "0 30px 80px rgba(0,0,0,0.35)",
          borderRadius: 18,
          position: "relative",
        }}
        data-testid="save-dialog"
      >
        <div className="eyebrow">Save to Notebook</div>
        <h3
          id="practice-save-title"
          style={{ marginTop: 6, marginBottom: 10 }}
        >
          What clicked? Add a note in your own words.
        </h3>
        <p className="small" style={{ marginBottom: 14 }}>
          Your code and any output are attached automatically. The note below
          becomes the front of an SRS card so future-you actually remembers
          this.
        </p>
        <label
          htmlFor="practice-note-textarea"
          className="small"
          style={{ display: "block", marginBottom: 6, fontWeight: 700 }}
        >
          Your note (optional)
        </label>
        <textarea
          id="practice-note-textarea"
          data-testid="save-note-input"
          value={state.note}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
            onChangeNote(e.target.value)
          }
          placeholder="One sentence: the idea you want to remember."
          rows={4}
          style={{
            width: "100%",
            padding: 12,
            borderRadius: 10,
            border: "1px solid var(--ink-3, #d8d2c2)",
            background: "white",
            fontFamily: "var(--sans)",
            fontSize: 13,
          }}
        />
        <div
          className="rd-footer"
          style={{
            justifyContent: "flex-end",
            marginTop: 18,
            display: "flex",
            gap: 8,
          }}
        >
          <button
            type="button"
            className="btn ghost"
            onClick={onClose}
            disabled={state.status === "saving"}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={onSave}
            disabled={state.status === "saving" || state.status === "saved"}
            data-testid="save-confirm"
          >
            {state.status === "saving"
              ? "Saving…"
              : state.status === "saved"
                ? (
                    <>
                      <Check className="inline-block h-3 w-3 mr-1" /> Saved
                    </>
                  )
                : state.status === "error"
                  ? "Try again"
                  : (
                      <>
                        <FileText className="inline-block h-3 w-3 mr-1" /> Save
                      </>
                    )}
          </button>
        </div>
      </div>
    </div>
  );
}
