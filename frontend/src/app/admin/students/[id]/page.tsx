"use client";

/**
 * /admin/students/[id] — full-page drilldown for a single student.
 *
 * Used as the canonical deep-link / bookmark target. The operator's
 * daily triage flow goes through the side-drawer on /admin instead;
 * this route is for the cases where a direct URL is shared (email,
 * Slack, support) or someone wants the student in their own browser
 * tab.
 *
 * Renders the same <StudentDetailPanel> the drawer renders, so the
 * UI is guaranteed identical between the two surfaces.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { StudentDetailPanel } from "../../_components/student-detail-panel";

export default function StudentDrilldownPage() {
  const params = useParams<{ id: string }>();
  const studentId = params?.id ?? null;

  return (
    <div className="p-6 md:p-8 max-w-5xl mx-auto space-y-6">
      <Link
        href="/admin/students"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        Back to students
      </Link>

      <StudentDetailPanel studentId={studentId} />
    </div>
  );
}
