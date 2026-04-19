"use client";

import { useMyResume } from "@/lib/hooks/use-career";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MarkdownRenderer } from "@/components/features/markdown-renderer";
import { PageShell } from "@/components/layouts/page-shell";
import { PageHeader } from "@/components/layouts/page-header";

export default function ResumePage() {
  const { data: resume, isLoading } = useMyResume();

  if (isLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Loading your resume…
      </div>
    );
  }

  return (
    <PageShell variant="narrow" density="compact" className="space-y-4">
      <PageHeader title="Resume" />
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
      {resume?.linkedin_blurb && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">LinkedIn Headline</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm">{resume.linkedin_blurb}</p>
          </CardContent>
        </Card>
      )}
    </PageShell>
  );
}
