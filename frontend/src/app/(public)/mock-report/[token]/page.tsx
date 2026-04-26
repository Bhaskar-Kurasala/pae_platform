"use client";

import { use } from "react";
import { Report } from "@/components/features/mock-interview";
import { usePublicMockReport } from "@/lib/hooks/use-mock-interview";

interface PageProps {
  params: Promise<{ token: string }>;
}

export default function PublicMockReportPage({ params }: PageProps) {
  const { token } = use(params);
  const { data: report, isLoading, isError } = usePublicMockReport(token);

  return (
    <main
      style={{
        maxWidth: 1100,
        margin: "0 auto",
        padding: "60px 28px",
        display: "grid",
        gap: 18,
      }}
    >
      <header style={{ display: "grid", gap: 6 }}>
        <div
          style={{
            fontSize: 11,
            letterSpacing: ".18em",
            textTransform: "uppercase",
            color: "var(--muted)",
            fontWeight: 700,
          }}
        >
          CareerForge · Shared mock interview report
        </div>
        <h1
          style={{
            fontFamily: "var(--serif)",
            fontWeight: 500,
            fontSize: 28,
            letterSpacing: "-.02em",
            margin: 0,
          }}
        >
          Read-only report
        </h1>
        <p style={{ color: "var(--muted)", fontSize: 14, lineHeight: 1.55 }}>
          This report is shared by the candidate. Numeric scores reflect a
          rubric-calibrated AI evaluation — not a hiring signal.
        </p>
      </header>

      {isLoading ? (
        <div className="match-card" style={{ padding: 22 }}>
          <div className="k">Loading</div>
          <div className="big">Fetching the shared report…</div>
        </div>
      ) : null}

      {isError || !report ? (
        <div className="match-card" style={{ padding: 22 }}>
          <div className="k">Not found</div>
          <div className="big">
            This shared report is no longer available, or the link is incorrect.
          </div>
        </div>
      ) : null}

      {report ? <Report report={report} publicView /> : null}
    </main>
  );
}
