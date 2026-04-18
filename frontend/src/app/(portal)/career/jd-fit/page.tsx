"use client";

import { useState } from "react";
import { useFitScore, useLearningPlan } from "@/lib/hooks/use-career";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownRenderer } from "@/components/features/markdown-renderer";

export default function JdFitPage() {
  const [jdText, setJdText] = useState("");
  const fitScore = useFitScore();
  const learningPlan = useLearningPlan();

  const analyze = () => {
    fitScore.mutate({ jd_text: jdText, jd_title: "Position" });
  };

  const getPlan = () => {
    learningPlan.mutate({ jd_text: jdText, jd_title: "Position" });
  };

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-6">
      <h1 className="text-xl font-semibold">JD Fit Analysis</h1>
      <Textarea
        placeholder="Paste job description here…"
        value={jdText}
        onChange={(e) => setJdText(e.target.value)}
        rows={6}
        aria-label="Job description text"
      />
      <div className="flex gap-2">
        <Button
          onClick={analyze}
          disabled={!jdText || fitScore.isPending}
          aria-label="Get fit score"
        >
          Get Fit Score
        </Button>
        <Button
          variant="outline"
          onClick={getPlan}
          disabled={!jdText || learningPlan.isPending}
          aria-label="Get learning plan"
        >
          Get Learning Plan
        </Button>
      </div>

      {fitScore.data && (
        <div className="rounded-md border border-border p-4">
          <p className="text-lg font-bold">
            Fit Score: {Math.round(fitScore.data.fit_score * 100)}%
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Matched:{" "}
            {fitScore.data.matched_skills.length > 0
              ? fitScore.data.matched_skills.join(", ")
              : "none"}
          </p>
          {fitScore.data.skill_gap.length > 0 && (
            <p className="mt-1 text-sm text-destructive">
              Gap: {fitScore.data.skill_gap.join(", ")}
            </p>
          )}
        </div>
      )}

      {learningPlan.data && (
        <div className="rounded-md border border-border p-4">
          <MarkdownRenderer content={learningPlan.data.plan} />
        </div>
      )}
    </div>
  );
}
