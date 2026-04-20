"use client";

import { useState } from "react";
import { useMyResume, useRegenerateResume } from "@/lib/hooks/use-career";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MarkdownRenderer } from "@/components/features/markdown-renderer";
import { PageShell } from "@/components/layouts/page-shell";
import { PageHeader } from "@/components/layouts/page-header";
import { cn } from "@/lib/utils";

// ── Verdict badge ─────────────────────────────────────────────────

const VERDICT_LABELS: Record<string, string> = {
  strong_fit: "Strong Fit",
  good_fit: "Good Fit",
  needs_work: "Needs Work",
};

function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) return null;

  const variantMap: Record<string, "success" | "warning" | "destructive"> = {
    strong_fit: "success",
    good_fit: "warning",
    needs_work: "destructive",
  };

  const variant = variantMap[verdict] ?? "outline";
  const label = VERDICT_LABELS[verdict] ?? verdict;

  return (
    <Badge variant={variant} aria-label={`Verdict: ${label}`}>
      {label}
    </Badge>
  );
}

// ── Skeleton cards shown during initial load ─────────────────────

function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <Card>
      <CardHeader>
        <div className="h-4 w-40 rounded-md bg-muted animate-pulse" />
      </CardHeader>
      <CardContent className="space-y-2">
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className={cn(
              "h-3 rounded-md bg-muted animate-pulse",
              i === lines - 1 ? "w-2/3" : "w-full",
            )}
          />
        ))}
      </CardContent>
    </Card>
  );
}

// ── Copy-to-clipboard button ─────────────────────────────────────

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore clipboard errors in restricted contexts
    }
  };

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={handleCopy}
      aria-label={label}
      className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
    >
      {copied ? "Copied!" : "Copy"}
    </Button>
  );
}

// ── Page ─────────────────────────────────────────────────────────

export default function ResumePage() {
  const { data: resume, isLoading } = useMyResume();
  const regenerate = useRegenerateResume();

  const handleRegenerate = () => regenerate.mutate(false);
  const handleForceRefresh = () => regenerate.mutate(true);

  const headerActions = (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={handleRegenerate}
        disabled={regenerate.isPending}
        aria-label="Regenerate resume"
      >
        {regenerate.isPending ? (
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
              aria-hidden="true"
            />
            Regenerating…
          </span>
        ) : (
          "Regenerate"
        )}
      </Button>
      <Button
        variant="secondary"
        size="sm"
        onClick={handleForceRefresh}
        disabled={regenerate.isPending}
        aria-label="Force refresh resume from scratch"
      >
        Force Refresh
      </Button>
    </div>
  );

  if (isLoading) {
    return (
      <PageShell variant="default" density="compact" className="space-y-4">
        <PageHeader title="Resume Builder" />
        <SkeletonCard lines={4} />
        <SkeletonCard lines={6} />
        <SkeletonCard lines={2} />
      </PageShell>
    );
  }

  return (
    <PageShell variant="default" density="compact" className="space-y-4">
      {/* Section 1 — Header */}
      <PageHeader
        title="Resume Builder"
        description={resume?.title ?? undefined}
        actions={
          <div className="flex items-center gap-3">
            <VerdictBadge verdict={resume?.verdict ?? null} />
            {headerActions}
          </div>
        }
      />

      {/* Section 2 — Professional Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Professional Summary</CardTitle>
        </CardHeader>
        <CardContent>
          {resume?.summary ? (
            <MarkdownRenderer content={resume.summary} />
          ) : (
            <p className="text-sm text-muted-foreground">
              Generating your summary based on your skill profile…
            </p>
          )}
        </CardContent>
      </Card>

      {/* Section 3 — Experience Bullets */}
      {resume?.bullets && resume.bullets.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Experience Bullets</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {resume.bullets.map((bullet, idx) => (
              <div
                key={`${bullet.evidence_id}-${idx}`}
                className="flex flex-col gap-2 rounded-lg border border-border/50 bg-muted/20 p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="flex-1 text-sm text-foreground leading-6">
                    {bullet.text}
                  </p>
                  <CopyButton
                    text={bullet.text}
                    label={`Copy bullet ${idx + 1}`}
                  />
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge
                    variant="secondary"
                    aria-label={`Evidence ID: ${bullet.evidence_id}`}
                  >
                    {bullet.evidence_id}
                  </Badge>
                  {bullet.ats_keywords.map((kw) => (
                    <Badge
                      key={kw}
                      variant="outline"
                      className="text-[10px] text-muted-foreground"
                      aria-label={`ATS keyword: ${kw}`}
                    >
                      {kw}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Section 4 — LinkedIn Pack */}
      {resume?.linkedin_blurb && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-base">LinkedIn Headline</CardTitle>
            <CopyButton
              text={resume.linkedin_blurb}
              label="Copy LinkedIn blurb"
            />
          </CardHeader>
          <CardContent>
            <blockquote className="border-l-4 border-primary/40 pl-4 py-1 bg-primary/5 rounded-r-lg">
              <p className="text-sm text-muted-foreground italic leading-6">
                {resume.linkedin_blurb}
              </p>
            </blockquote>
          </CardContent>
        </Card>
      )}

      {/* Section 5 — ATS Keywords */}
      {resume?.ats_keywords && resume.ats_keywords.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">ATS Keywords</CardTitle>
            <p className="text-xs text-muted-foreground mt-0.5">
              These keywords are optimized for applicant tracking systems
            </p>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2" role="list" aria-label="ATS keywords">
              {resume.ats_keywords.map((kw) => (
                <Badge
                  key={kw}
                  variant="secondary"
                  className="text-xs"
                  role="listitem"
                  aria-label={`Keyword: ${kw}`}
                >
                  {kw}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </PageShell>
  );
}
