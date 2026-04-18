"use client";

import { useState } from "react";
import {
  Brain,
  ChevronDown,
  ChevronUp,
  Clock,
  Code2,
  GitCompare,
  History,
  Loader2,
  MessageSquare,
  Play,
  Sparkles,
  Terminal,
  UserCheck,
} from "lucide-react";
import { ResizableSplit } from "./resizable-split";
import { StudioPane } from "./studio-pane";
import { CodeEditor } from "./code-editor";
import { DiffViewer } from "./diff-viewer";
import { StudioChat } from "./studio-chat";
import { ExecutionTrace } from "./execution-trace";
import { MisconceptionsPanel } from "./misconceptions-panel";
import { QualityPanel } from "./quality-panel";
import { RunHistoryPanel } from "./run-history-panel";
import { PromptPreviewPanel } from "./prompt-preview-panel";
import { SnippetToolbar } from "./snippet-toolbar";
import { StudioProvider, useStudio } from "./studio-context";
import { UglyDraftToggle } from "./ugly-draft-toggle";
import { SeniorReviewPanel } from "./senior-review-panel";
import { useSeniorReview } from "@/lib/hooks/use-senior-review";

function PromptPreviewPanelWrapper() {
  const { code } = useStudio();
  return <PromptPreviewPanel code={code} />;
}

function CodePane() {
  const { setCode, showDiff, previousCode, code } = useStudio();

  const handleInsert = (snippet: string) => {
    // Insert snippet at end of current code
    setCode(code + (code.endsWith("\n") ? "" : "\n") + snippet);
  };

  if (showDiff && previousCode !== null) {
    return (
      <div className="flex h-full flex-col">
        <DiffViewer original={previousCode} modified={code} />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <SnippetToolbar onInsert={handleInsert} />
      <div className="flex-1 overflow-hidden">
        <CodeEditor onCodeChange={setCode} />
      </div>
    </div>
  );
}

function RunButton() {
  const { run, running, code } = useStudio();
  const disabled = running || code.trim().length === 0;
  return (
    <button
      type="button"
      onClick={() => {
        void run();
      }}
      disabled={disabled}
      aria-label="Run code"
      className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {running ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
      ) : (
        <Play className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      <span>{running ? "Running" : "Run"}</span>
    </button>
  );
}

function DiffToggleButton() {
  const { showDiff, setShowDiff, previousCode } = useStudio();
  if (previousCode === null) return null;
  return (
    <button
      type="button"
      onClick={() => setShowDiff(!showDiff)}
      aria-pressed={showDiff}
      aria-label={showDiff ? "Show editor" : "Show diff from last run"}
      title={showDiff ? "Back to editor" : "Compare with last run"}
      className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium transition ${
        showDiff
          ? "border-primary bg-primary/10 text-primary"
          : "border-border bg-background text-foreground hover:bg-muted"
      }`}
    >
      <GitCompare className="h-3.5 w-3.5" aria-hidden="true" />
      <span>{showDiff ? "Editor" : "Diff"}</span>
    </button>
  );
}

function SeniorReviewButton({ onClick }: { onClick: () => void }) {
  const { code } = useStudio();
  const disabled = code.trim().length === 0;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label="Request senior engineer review"
      title="Ask a simulated senior engineer to review this code (PR-style feedback)"
      className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
    >
      <UserCheck className="h-3.5 w-3.5" aria-hidden="true" />
      <span>Senior review</span>
    </button>
  );
}

function CodePaneActions({ onReview }: { onReview: () => void }) {
  return (
    <div className="flex items-center gap-1.5">
      <DiffToggleButton />
      <SeniorReviewButton onClick={onReview} />
      <RunButton />
    </div>
  );
}

type BottomTab = "trace" | "quality" | "mental-model" | "history" | "prompt-preview";

function QualityBadge() {
  const { result } = useStudio();
  const issues = result?.quality?.issues ?? [];
  if (issues.length === 0) return null;
  const warnings = issues.filter((i) => i.severity === "warning").length;
  const tone = warnings > 0 ? "bg-amber-500/15 text-amber-500" : "bg-muted text-muted-foreground";
  return (
    <span className={`ml-1 rounded px-1.5 py-0.5 text-[10px] font-semibold ${tone}`}>
      {issues.length}
    </span>
  );
}

function HistoryBadge() {
  const { history } = useStudio();
  if (history.length === 0) return null;
  return (
    <span className="ml-1 rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
      {history.length}
    </span>
  );
}

function StudioLayoutInner() {
  const [traceCollapsed, setTraceCollapsed] = useState(false);
  const [bottomTab, setBottomTab] = useState<BottomTab>("trace");
  const [reviewOpen, setReviewOpen] = useState(false);
  const { code } = useStudio();
  const review = useSeniorReview();

  const toggleTrace = () => setTraceCollapsed((c) => !c);

  function handleRequestReview() {
    const trimmed = code.trim();
    if (!trimmed) return;
    setReviewOpen(true);
    review.reset();
    review.mutate({ code: trimmed });
  }

  const topRow = (
    <ResizableSplit
      direction="horizontal"
      initial={58}
      min={30}
      max={80}
      storageKey="studio.split.h"
      first={
        <StudioPane
          title="Code"
          icon={Code2}
          action={<CodePaneActions onReview={handleRequestReview} />}
        >
          <CodePane />
        </StudioPane>
      }
      second={
        <StudioPane
          title="Tutor"
          icon={MessageSquare}
          action={<UglyDraftToggle />}
        >
          <StudioChat />
        </StudioPane>
      }
    />
  );

  const bottomTabs = (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => setBottomTab("trace")}
        aria-pressed={bottomTab === "trace"}
        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition ${
          bottomTab === "trace"
            ? "bg-muted text-foreground"
            : "text-muted-foreground hover:bg-muted/50"
        }`}
      >
        <Play className="h-3 w-3" aria-hidden="true" />
        Trace
      </button>
      <button
        type="button"
        onClick={() => setBottomTab("quality")}
        aria-pressed={bottomTab === "quality"}
        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition ${
          bottomTab === "quality"
            ? "bg-muted text-foreground"
            : "text-muted-foreground hover:bg-muted/50"
        }`}
      >
        <Sparkles className="h-3 w-3" aria-hidden="true" />
        Quality
        <QualityBadge />
      </button>
      <button
        type="button"
        onClick={() => setBottomTab("mental-model")}
        aria-pressed={bottomTab === "mental-model"}
        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition ${
          bottomTab === "mental-model"
            ? "bg-muted text-foreground"
            : "text-muted-foreground hover:bg-muted/50"
        }`}
      >
        <Brain className="h-3 w-3" aria-hidden="true" />
        Mental model
      </button>
      <button
        type="button"
        onClick={() => setBottomTab("history")}
        aria-pressed={bottomTab === "history"}
        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition ${
          bottomTab === "history"
            ? "bg-muted text-foreground"
            : "text-muted-foreground hover:bg-muted/50"
        }`}
      >
        <History className="h-3 w-3" aria-hidden="true" />
        History
        <HistoryBadge />
      </button>
      <button
        type="button"
        onClick={() => setBottomTab("prompt-preview")}
        aria-pressed={bottomTab === "prompt-preview"}
        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition ${
          bottomTab === "prompt-preview"
            ? "bg-muted text-foreground"
            : "text-muted-foreground hover:bg-muted/50"
        }`}
      >
        <Terminal className="h-3 w-3" aria-hidden="true" />
        Preview
      </button>
      <button
        type="button"
        onClick={toggleTrace}
        aria-label={traceCollapsed ? "Expand panel" : "Collapse panel"}
        className="ml-1 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        {traceCollapsed ? (
          <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
        )}
      </button>
    </div>
  );

  const bottomTitle =
    bottomTab === "trace"
      ? "Execution Trace"
      : bottomTab === "quality"
        ? "Code Quality"
        : bottomTab === "history"
          ? "Run History"
          : bottomTab === "prompt-preview"
            ? "Prompt Preview"
            : "Mental Model Check";

  const BottomIcon =
    bottomTab === "trace"
      ? Play
      : bottomTab === "quality"
        ? Sparkles
        : bottomTab === "history"
          ? Clock
          : bottomTab === "prompt-preview"
            ? Terminal
            : Brain;

  const bottomRow = (
    <StudioPane title={bottomTitle} icon={BottomIcon} action={bottomTabs}>
      {bottomTab === "trace" ? (
        <ExecutionTrace />
      ) : bottomTab === "quality" ? (
        <QualityPanel />
      ) : bottomTab === "history" ? (
        <RunHistoryPanel />
      ) : bottomTab === "prompt-preview" ? (
        <PromptPreviewPanelWrapper />
      ) : (
        <MisconceptionsPanel />
      )}
    </StudioPane>
  );

  const reviewPanel = (
    <SeniorReviewPanel
      open={reviewOpen}
      loading={review.isPending}
      error={review.error ? review.error.message : null}
      review={review.data ?? null}
      onClose={() => setReviewOpen(false)}
    />
  );

  if (traceCollapsed) {
    return (
      <>
        <div className="flex h-full flex-col overflow-hidden" data-slot="studio">
          <div className="flex-1 overflow-hidden">{topRow}</div>
          <div className="h-10 shrink-0 border-t border-border">
            <StudioPane
              title="Execution Trace"
              icon={Play}
              action={
                <button
                  type="button"
                  onClick={toggleTrace}
                  aria-label="Expand trace"
                  className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              }
            >
              <div />
            </StudioPane>
          </div>
        </div>
        {reviewPanel}
      </>
    );
  }

  return (
    <>
      <div className="h-full overflow-hidden" data-slot="studio">
        <ResizableSplit
          direction="vertical"
          initial={72}
          min={50}
          max={90}
          storageKey="studio.split.v"
          first={topRow}
          second={bottomRow}
        />
      </div>
      {reviewPanel}
    </>
  );
}

export function StudioLayout() {
  return (
    <StudioProvider>
      <StudioLayoutInner />
    </StudioProvider>
  );
}
