"use client";

import { useEffect, useState } from "react";
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
  Network,
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
import { SkillGraph } from "./skill-graph";
import { SnippetToolbar } from "./snippet-toolbar";
import { StudioProvider, useStudio } from "./studio-context";
import { StuckBanner } from "./stuck-banner";
import { WarmupBanner } from "./warmup-banner";
import { QualityMeter } from "./quality-meter";
import { SaveToNotebookButton } from "./save-to-notebook-button";
import { PercentileToast } from "./percentile-toast";
import { BadgeSystem } from "./badge-system";
import { ChallengeDrawer } from "./challenge-picker";
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
      className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50 pointer-coarse:h-11 pointer-coarse:min-w-11 pointer-coarse:px-3 pointer-coarse:text-sm"
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
      className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium transition pointer-coarse:h-11 pointer-coarse:min-w-11 pointer-coarse:px-3 pointer-coarse:text-sm ${
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
      className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 pointer-coarse:h-11 pointer-coarse:min-w-11 pointer-coarse:px-3 pointer-coarse:text-sm"
    >
      <UserCheck className="h-3.5 w-3.5" aria-hidden="true" />
      <span>Senior review</span>
    </button>
  );
}

function CodePaneActions({ onReview }: { onReview: () => void }) {
  return (
    <div className="flex items-center gap-1.5">
      <QualityMeter />
      <DiffToggleButton />
      <SeniorReviewButton onClick={onReview} />
      <SaveToNotebookButton />
      <RunButton />
    </div>
  );
}

type BottomTab = "quality" | "mental-model" | "history" | "prompt-preview" | "skills";
type RightTab = "tutor" | "review" | "trace";

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

/** Tab strip rendered in the right rail header. */
function RightRailTabs({
  active,
  onSelect,
  hasReview,
}: {
  active: RightTab;
  onSelect: (tab: RightTab) => void;
  hasReview: boolean;
}) {
  const tabs: { id: RightTab; Icon: typeof MessageSquare; label: string }[] = [
    { id: "tutor",  Icon: MessageSquare, label: "Tutor chat" },
    { id: "review", Icon: UserCheck,     label: "Review results" },
    { id: "trace",  Icon: Play,          label: "Execution trace" },
  ];
  return (
    <div className="flex items-center gap-0.5" role="tablist" aria-label="Right panel">
      {tabs.map(({ id, Icon, label }) => {
        const isActive = active === id;
        const showDot = id === "review" && hasReview && !isActive;
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={isActive}
            aria-label={label}
            onClick={() => onSelect(id)}
            className={`relative inline-flex items-center justify-center rounded-md p-1.5 transition pointer-coarse:h-9 pointer-coarse:w-9 ${
              isActive
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            }`}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            {showDot && (
              <span
                className="absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-primary"
                aria-hidden="true"
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Inline review content — rendered inside the right rail without overlay chrome. */
function InlineReviewContent({
  loading,
  error,
  review,
}: {
  loading: boolean;
  error: string | null;
  review: import("@/lib/api-client").SeniorReview | null;
}) {
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">Reading your code…</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="m-4 rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-700 dark:text-red-300">
        {error}
      </div>
    );
  }
  if (!review) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-center text-muted-foreground">
        <UserCheck className="h-8 w-8 opacity-30" aria-hidden="true" />
        <p className="text-sm">No review yet. Click "Senior review" to request one.</p>
      </div>
    );
  }

  const verdictMap: Record<
    import("@/lib/api-client").SeniorReviewVerdict,
    { label: string; pill: string }
  > = {
    approve:         { label: "Approved",          pill: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" },
    request_changes: { label: "Changes requested", pill: "bg-red-500/15 text-red-700 dark:text-red-300" },
    comment:         { label: "Comments",           pill: "bg-muted text-muted-foreground" },
  };
  const verdictStyle = verdictMap[review.verdict];

  return (
    <div className="space-y-5 px-4 py-4">
      <div className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${verdictStyle.pill}`}>
        {verdictStyle.label}
      </div>
      <p className="text-base font-medium text-foreground">{review.headline}</p>
      {review.strengths.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Strengths
          </h3>
          <ul className="mt-2 space-y-1.5">
            {review.strengths.map((s, i) => (
              <li key={i} className="flex gap-2 text-sm text-foreground/90">
                <span className="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400">✓</span>
                {s}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Comments ({review.comments.length})
        </h3>
        {review.comments.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">No line-level comments.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {review.comments.map((c, i) => (
              <li key={i} className="rounded-lg border border-border bg-card p-3">
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider bg-muted text-muted-foreground border border-border">
                    {c.severity}
                  </span>
                  <span className="font-mono text-[11px] text-muted-foreground">L{c.line}</span>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-foreground">{c.message}</p>
                {c.suggested_change && (
                  <pre className="mt-2 overflow-x-auto rounded-md bg-muted/60 p-2 text-[12px] font-mono text-foreground">
                    {c.suggested_change}
                  </pre>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="rounded-lg border border-primary/30 bg-primary/5 p-3">
        <div className="text-xs font-semibold uppercase tracking-wider text-primary">Next step</div>
        <p className="mt-1.5 text-sm leading-relaxed text-foreground">{review.next_step}</p>
      </section>
    </div>
  );
}

function StudioLayoutInner() {
  const [bottomCollapsed, setBottomCollapsed] = useState(false);
  const [bottomTab, setBottomTab] = useState<BottomTab>("quality");
  const [rightTab, setRightTab] = useState<RightTab>("tutor");
  const [challengeDrawerOpen, setChallengeDrawerOpen] = useState(false);
  const { code, runCount } = useStudio();
  const review = useSeniorReview();

  // Listen for the header button dispatching studio:open-challenges
  useEffect(() => {
    function onOpen() { setChallengeDrawerOpen(true); }
    window.addEventListener("studio:open-challenges", onOpen);
    return () => window.removeEventListener("studio:open-challenges", onOpen);
  }, []);

  const toggleBottom = () => setBottomCollapsed((c) => !c);

  // Auto-switch right rail to "review" when a pending review starts or data arrives
  useEffect(() => {
    if (review.isPending) {
      setRightTab("review");
    }
  }, [review.isPending]);

  useEffect(() => {
    if (review.data !== null && review.data !== undefined) {
      setRightTab("review");
    }
  }, [review.data]);

  function handleRequestReview() {
    const trimmed = code.trim();
    if (!trimmed) return;
    review.reset();
    review.mutate(
      { code: trimmed },
      {
        onSuccess: () => {
          // P3-2 — notify badge system that a review completed
          window.dispatchEvent(new CustomEvent("studio:review-done"));
        },
      },
    );
  }

  const rightRailTitle =
    rightTab === "tutor"  ? "Tutor" :
    rightTab === "review" ? "Review" : "Trace";
  const RightRailIcon =
    rightTab === "tutor"  ? MessageSquare :
    rightTab === "review" ? UserCheck : Play;

  const rightRailAction = (
    <RightRailTabs
      active={rightTab}
      onSelect={setRightTab}
      hasReview={review.data !== null && review.data !== undefined}
    />
  );

  const rightRailContent =
    rightTab === "tutor" ? (
      <StudioChat />
    ) : rightTab === "review" ? (
      <div className="h-full overflow-y-auto">
        <InlineReviewContent
          loading={review.isPending}
          error={review.error ? review.error.message : null}
          review={review.data ?? null}
        />
      </div>
    ) : (
      <ExecutionTrace />
    );

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
          title={rightRailTitle}
          icon={RightRailIcon}
          action={rightRailAction}
        >
          {rightRailContent}
        </StudioPane>
      }
    />
  );

  const bottomTabs = (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => setBottomTab("quality")}
        aria-pressed={bottomTab === "quality"}
        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition pointer-coarse:h-11 pointer-coarse:min-w-11 pointer-coarse:px-3 pointer-coarse:text-sm ${
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
        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition pointer-coarse:h-11 pointer-coarse:min-w-11 pointer-coarse:px-3 pointer-coarse:text-sm ${
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
        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition pointer-coarse:h-11 pointer-coarse:min-w-11 pointer-coarse:px-3 pointer-coarse:text-sm ${
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
        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition pointer-coarse:h-11 pointer-coarse:min-w-11 pointer-coarse:px-3 pointer-coarse:text-sm ${
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
        onClick={() => setBottomTab("skills")}
        aria-pressed={bottomTab === "skills"}
        aria-label="Skill tree"
        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition pointer-coarse:h-11 pointer-coarse:min-w-11 pointer-coarse:px-3 pointer-coarse:text-sm ${
          bottomTab === "skills"
            ? "bg-muted text-foreground"
            : "text-muted-foreground hover:bg-muted/50"
        }`}
      >
        <Network className="h-3 w-3" aria-hidden="true" />
        Skills
      </button>
      <button
        type="button"
        onClick={toggleBottom}
        aria-label={bottomCollapsed ? "Expand panel" : "Collapse panel"}
        className="ml-1 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground pointer-coarse:h-11 pointer-coarse:w-11 pointer-coarse:flex pointer-coarse:items-center pointer-coarse:justify-center"
      >
        {bottomCollapsed ? (
          <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
        )}
      </button>
    </div>
  );

  const bottomTitle =
    bottomTab === "quality"
      ? "Code Quality"
      : bottomTab === "history"
        ? "Run History"
        : bottomTab === "prompt-preview"
          ? "Prompt Preview"
          : bottomTab === "skills"
            ? "Skill Tree"
            : "Mental Model Check";

  const BottomIcon =
    bottomTab === "quality"
      ? Sparkles
      : bottomTab === "history"
        ? Clock
        : bottomTab === "prompt-preview"
          ? Terminal
          : bottomTab === "skills"
            ? Network
            : Brain;

  const bottomRow = (
    <StudioPane title={bottomTitle} icon={BottomIcon} action={bottomTabs}>
      {bottomTab === "quality" ? (
        <QualityPanel />
      ) : bottomTab === "history" ? (
        <RunHistoryPanel />
      ) : bottomTab === "prompt-preview" ? (
        <PromptPreviewPanelWrapper />
      ) : bottomTab === "skills" ? (
        <SkillGraph />
      ) : (
        <MisconceptionsPanel />
      )}
    </StudioPane>
  );

  if (bottomCollapsed) {
    return (
      <div className="flex h-full flex-col overflow-hidden" data-slot="studio">
        <WarmupBanner />
        <StuckBanner />
        <div className="flex-1 overflow-hidden">{topRow}</div>
        <div className="h-10 shrink-0 border-t border-border">
          <StudioPane
            title="Code Quality"
            icon={Sparkles}
            action={
              <button
                type="button"
                onClick={toggleBottom}
                aria-label="Expand bottom panel"
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground pointer-coarse:h-11 pointer-coarse:w-11 pointer-coarse:flex pointer-coarse:items-center pointer-coarse:justify-center"
              >
                <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            }
          >
            <div />
          </StudioPane>
        </div>
        {/* P3-1/P3-2 — social reward floating toasts */}
        <PercentileToast runCount={runCount} code={code} />
        <BadgeSystem />
        <ChallengeDrawer open={challengeDrawerOpen} onClose={() => setChallengeDrawerOpen(false)} />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden" data-slot="studio">
      <WarmupBanner />
      <StuckBanner />
      <div className="flex-1 overflow-hidden">
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
      {/* P3-1/P3-2 — social reward floating toasts */}
      <PercentileToast runCount={runCount} code={code} />
      <BadgeSystem />
      <ChallengeDrawer open={challengeDrawerOpen} onClose={() => setChallengeDrawerOpen(false)} />
    </div>
  );
}

export function StudioLayout({ initialCode }: { initialCode?: string }) {
  return (
    <StudioProvider initialCode={initialCode}>
      <StudioLayoutInner />
    </StudioProvider>
  );
}
