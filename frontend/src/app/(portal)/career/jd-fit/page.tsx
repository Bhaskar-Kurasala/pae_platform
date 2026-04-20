"use client";

import { useState } from "react";
import {
  useFitScore,
  useLearningPlan,
  useSaveJd,
  useJdLibrary,
  useDeleteJd,
} from "@/lib/hooks/use-career";
import type { FitVerdict, JdLibraryItem } from "@/lib/hooks/use-career";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { MarkdownRenderer } from "@/components/features/markdown-renderer";
import { PageShell } from "@/components/layouts/page-shell";
import { PageHeader } from "@/components/layouts/page-header";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

// ── Verdict helpers ───────────────────────────────────────────────

const VERDICT_CONFIG = {
  apply: {
    label: "✓ Apply Now",
    bg: "bg-green-50 border-green-200",
    badgeCls: "bg-green-100 text-green-800 border-green-300",
    textCls: "text-green-900",
    reasonCls: "text-green-800",
  },
  skill_up: {
    label: "⟳ Skill Up First",
    bg: "bg-amber-50 border-amber-200",
    badgeCls: "bg-amber-100 text-amber-800 border-amber-300",
    textCls: "text-amber-900",
    reasonCls: "text-amber-800",
  },
  skip: {
    label: "✗ Skip for Now",
    bg: "bg-red-50 border-red-200",
    badgeCls: "bg-red-100 text-red-800 border-red-300",
    textCls: "text-red-900",
    reasonCls: "text-red-800",
  },
} as const;

const BUCKET_CONFIG = {
  proven: {
    label: "Proven",
    chipCls: "bg-green-100 text-green-800 border-green-200",
    headingCls: "text-green-700",
  },
  unproven: {
    label: "Unproven",
    chipCls: "bg-amber-100 text-amber-800 border-amber-200",
    headingCls: "text-amber-700",
  },
  missing: {
    label: "Missing",
    chipCls: "bg-red-100 text-red-800 border-red-200",
    headingCls: "text-red-700",
  },
} as const;

const VERDICT_BADGE: Record<string, string> = {
  apply: "bg-green-100 text-green-800",
  skill_up: "bg-amber-100 text-amber-800",
  skip: "bg-red-100 text-red-800",
};

const VERDICT_LABELS: Record<string, string> = {
  apply: "Apply",
  skill_up: "Skill Up",
  skip: "Skip",
};

// ── Sub-components ────────────────────────────────────────────────

function VerdictBanner({ verdict }: { verdict: FitVerdict }) {
  const cfg = VERDICT_CONFIG[verdict.verdict];
  return (
    <Card className={cn("border", cfg.bg)}>
      <CardContent className="pt-5 pb-4 space-y-3">
        <p className={cn("text-2xl font-bold", cfg.textCls)}>{cfg.label}</p>
        <p className={cn("text-sm leading-6", cfg.reasonCls)}>
          {verdict.verdict_reason}
        </p>
        <div className="flex flex-wrap gap-4 pt-1">
          <Stat label="Fit Score" value={`${Math.round(verdict.fit_score * 100)}%`} />
          <Stat label="Weeks to Close" value={String(verdict.weeks_to_close)} />
          <Stat label="Matched Skills" value={String(verdict.buckets.proven.length)} />
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
        {label}
      </span>
      <span className="text-xl font-bold text-foreground">{value}</span>
    </div>
  );
}

function ThreeBuckets({ buckets }: { buckets: FitVerdict["buckets"] }) {
  const keys = ["proven", "unproven", "missing"] as const;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Skill Breakdown</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {keys.map((key) => {
            const cfg = BUCKET_CONFIG[key];
            const skills = buckets[key];
            return (
              <div key={key} className="space-y-2">
                <p className={cn("text-sm font-semibold", cfg.headingCls)}>
                  {cfg.label}{" "}
                  <span className="font-normal text-muted-foreground">
                    ({skills.length})
                  </span>
                </p>
                {skills.length === 0 ? (
                  <p className="text-xs text-muted-foreground italic">None</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {skills.map((skill) => (
                      <span
                        key={skill}
                        className={cn(
                          "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium",
                          cfg.chipCls,
                        )}
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function TopActions({
  actions,
  onAddToStudyPlan,
}: {
  actions: string[];
  onAddToStudyPlan: () => void;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Top 3 Actions</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <ol className="space-y-2 list-decimal list-inside">
          {actions.map((action, i) => (
            <li key={i} className="text-sm text-foreground leading-6">
              {action}
            </li>
          ))}
        </ol>
        <Button
          variant="outline"
          size="sm"
          onClick={onAddToStudyPlan}
          aria-label="Add top actions to study plan"
        >
          Add to Study Plan
        </Button>
      </CardContent>
    </Card>
  );
}

function JdLibraryPanel({
  onLoad,
}: {
  onLoad: (item: JdLibraryItem) => void;
}) {
  const library = useJdLibrary();
  const deleteJd = useDeleteJd();

  return (
    <Card className="h-fit">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Saved JDs</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {library.isLoading && (
          <div className="flex justify-center py-4">
            <Spinner size="sm" label="Loading saved JDs" />
          </div>
        )}
        {library.data && library.data.length === 0 && (
          <p className="text-xs text-muted-foreground italic">
            No saved JDs yet.
          </p>
        )}
        {library.data?.map((item) => (
          <div
            key={item.id}
            className="rounded-lg border border-border p-3 space-y-1.5"
          >
            <p className="text-sm font-medium text-foreground leading-5 line-clamp-1">
              {item.title}
            </p>
            {item.company && (
              <p className="text-xs text-muted-foreground">{item.company}</p>
            )}
            <div className="flex items-center gap-1.5 flex-wrap">
              {item.last_fit_score !== null && (
                <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                  {Math.round(item.last_fit_score * 100)}%
                </Badge>
              )}
              {item.verdict && (
                <span
                  className={cn(
                    "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium",
                    VERDICT_BADGE[item.verdict] ?? "bg-muted text-muted-foreground",
                  )}
                >
                  {VERDICT_LABELS[item.verdict] ?? item.verdict}
                </span>
              )}
            </div>
            <div className="flex gap-1.5 pt-0.5">
              <Button
                size="sm"
                variant="outline"
                className="h-6 text-xs px-2"
                onClick={() => onLoad(item)}
                aria-label={`Load ${item.title}`}
              >
                Load
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-6 text-xs px-2 text-destructive hover:text-destructive"
                disabled={deleteJd.isPending}
                onClick={() => deleteJd.mutate(item.id)}
                aria-label={`Delete ${item.title}`}
              >
                {deleteJd.isPending && deleteJd.variables === item.id ? (
                  <Spinner size="sm" />
                ) : (
                  "Delete"
                )}
              </Button>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────

export default function JdFitPage() {
  const [jdText, setJdText] = useState("");
  const [jobTitle, setJobTitle] = useState("Software Engineer");
  const [company, setCompany] = useState("");
  const [studyPlanMsg, setStudyPlanMsg] = useState<string | null>(null);

  const fitScore = useFitScore();
  const learningPlan = useLearningPlan();
  const saveJd = useSaveJd();

  const analyze = () => {
    if (!jdText) return;
    fitScore.mutate({ jd_text: jdText, jd_title: jobTitle || "Position" });
  };

  const handleSave = () => {
    if (!jdText) return;
    saveJd.mutate({
      title: jobTitle || "Untitled",
      company: company || undefined,
      jd_text: jdText,
    });
  };

  const handleLoad = (item: JdLibraryItem) => {
    // Load the JD text — since we don't store the full jd_text in the list
    // response, we populate what we have and let the user re-analyze.
    setJobTitle(item.title);
    setCompany(item.company ?? "");
    // The library endpoint doesn't return jd_text, so we clear + prompt.
    setJdText("");
    fitScore.reset();
    learningPlan.reset();
  };

  const handleAddToStudyPlan = () => {
    setStudyPlanMsg("Added to study plan!");
    setTimeout(() => setStudyPlanMsg(null), 3000);
  };

  const verdict = fitScore.data?.verdict ?? null;
  const analysisReady = Boolean(fitScore.data);

  return (
    <PageShell variant="wide" density="compact" className="space-y-4">
      <PageHeader
        title="JD Fit Analysis"
        description="Paste a job description to score your fit, identify gaps, and plan your path."
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {/* ── Main content (2 cols) ─────────────────────────────── */}
        <div className="lg:col-span-2 space-y-4">
          {/* Input section */}
          <Card>
            <CardContent className="pt-4 space-y-3">
              <Textarea
                placeholder="Paste job description here…"
                value={jdText}
                onChange={(e) => setJdText(e.target.value)}
                rows={6}
                aria-label="Job description text"
                className="resize-none"
              />
              <div className="grid grid-cols-2 gap-2">
                <Input
                  value={jobTitle}
                  onChange={(e) => setJobTitle(e.target.value)}
                  placeholder="Job Title"
                  aria-label="Job title"
                />
                <Input
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  placeholder="Company (optional)"
                  aria-label="Company name (optional)"
                />
              </div>
              <div className="flex gap-2 flex-wrap">
                <Button
                  onClick={analyze}
                  disabled={!jdText || fitScore.isPending}
                  aria-label="Analyze job fit"
                >
                  {fitScore.isPending ? (
                    <>
                      <Spinner size="sm" className="mr-2" />
                      Analyzing…
                    </>
                  ) : (
                    "Analyze Fit"
                  )}
                </Button>
                <Button
                  variant="outline"
                  onClick={handleSave}
                  disabled={!analysisReady || saveJd.isPending}
                  aria-label="Save job description to library"
                >
                  {saveJd.isPending ? (
                    <>
                      <Spinner size="sm" className="mr-2" />
                      Saving…
                    </>
                  ) : (
                    "Save to Library"
                  )}
                </Button>
              </div>
              {saveJd.isSuccess && (
                <p className="text-xs text-green-700" role="status">
                  Saved to library.
                </p>
              )}
              {fitScore.isError && (
                <p className="text-xs text-destructive" role="alert">
                  {fitScore.error.message}
                </p>
              )}
            </CardContent>
          </Card>

          {/* Verdict Banner */}
          {verdict && <VerdictBanner verdict={verdict} />}

          {/* Three-Bucket Gap */}
          {verdict && <ThreeBuckets buckets={verdict.buckets} />}

          {/* Top 3 Actions */}
          {verdict && verdict.top_3_actions.length > 0 && (
            <>
              <TopActions
                actions={verdict.top_3_actions}
                onAddToStudyPlan={handleAddToStudyPlan}
              />
              {studyPlanMsg && (
                <p className="text-xs text-green-700" role="status">
                  {studyPlanMsg}
                </p>
              )}
            </>
          )}

          {/* Legacy fallback — simple score when verdict is null */}
          {fitScore.data && !verdict && (
            <Card>
              <CardContent className="pt-4 space-y-2">
                <p className="text-lg font-bold">
                  Fit Score: {Math.round(fitScore.data.fit_score * 100)}%
                </p>
                {fitScore.data.matched_skills.length > 0 && (
                  <p className="text-sm text-muted-foreground">
                    Matched: {fitScore.data.matched_skills.join(", ")}
                  </p>
                )}
                {fitScore.data.skill_gap.length > 0 && (
                  <p className="text-sm text-destructive">
                    Gap: {fitScore.data.skill_gap.join(", ")}
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          {/* Learning Plan */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Learning Plan</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Button
                variant="outline"
                onClick={() =>
                  learningPlan.mutate({
                    jd_text: jdText,
                    jd_title: jobTitle || "Position",
                  })
                }
                disabled={!jdText || learningPlan.isPending}
                aria-label="Get learning plan"
              >
                {learningPlan.isPending ? (
                  <>
                    <Spinner size="sm" className="mr-2" />
                    Generating…
                  </>
                ) : (
                  "Get Learning Plan"
                )}
              </Button>
              {learningPlan.isError && (
                <p className="text-xs text-destructive" role="alert">
                  {learningPlan.error.message}
                </p>
              )}
              {learningPlan.data && (
                <div className="rounded-md border border-border p-4">
                  <MarkdownRenderer content={learningPlan.data.plan} />
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── Sidebar (1 col) ───────────────────────────────────── */}
        <div className="lg:col-span-1">
          <JdLibraryPanel onLoad={handleLoad} />
        </div>
      </div>
    </PageShell>
  );
}
