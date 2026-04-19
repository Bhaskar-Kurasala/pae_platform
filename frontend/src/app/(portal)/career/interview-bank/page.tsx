"use client";

import { useState } from "react";
import { useInterviewQuestions } from "@/lib/hooks/use-career";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { PageShell } from "@/components/layouts/page-shell";
import { PageHeader } from "@/components/layouts/page-header";

export default function InterviewBankPage() {
  const [query, setQuery] = useState("");
  const { data: questions = [], isLoading } = useInterviewQuestions(query);

  return (
    <PageShell variant="narrow" density="compact" className="space-y-4">
      <PageHeader title="Interview Question Bank" />
      <Input
        placeholder="Search questions…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Search interview questions"
      />
      {isLoading && (
        <p className="text-sm text-muted-foreground">Searching…</p>
      )}
      {questions.length === 0 && !isLoading && (
        <p className="text-sm text-muted-foreground">
          No questions found. Questions are added as you progress through
          courses.
        </p>
      )}
      <ul className="space-y-3">
        {questions.map((q) => (
          <li key={q.id}>
            <Card>
              <CardContent className="p-4">
                <div className="mb-1 flex items-center gap-2">
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] capitalize">
                    {q.difficulty}
                  </span>
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] capitalize">
                    {q.category}
                  </span>
                </div>
                <p className="text-sm font-medium">{q.question}</p>
                {q.answer_hint && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {q.answer_hint}
                  </p>
                )}
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
    </PageShell>
  );
}
