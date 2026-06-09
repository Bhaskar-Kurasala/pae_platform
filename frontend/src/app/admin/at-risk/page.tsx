"use client";

/**
 * /admin/at-risk — DEPRECATED.
 *
 * This page used to host a multi-signal at-risk-students view that
 * pre-dated the F1 retention engine. It detected a different cohort
 * (using last_login + lesson stall + help drought signals) and
 * surfaced different students than the F1 slip-pattern panels on
 * /admin Overview, creating two competing "at-risk" views.
 *
 * The retention engine (F4 panels on /admin) is now the canonical
 * surface. The legacy URL redirects to /admin to avoid breaking
 * any external bookmarks; the sidebar nav link was removed.
 *
 * Future cleanup: once we've confirmed no in-product references
 * remain (search "at-risk" across the repo), this route + its
 * `/api/v1/admin/at-risk-students` backend endpoint can be
 * deleted entirely.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function LegacyAtRiskRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/admin");
  }, [router]);

  return (
    <div className="p-6 md:p-8 max-w-2xl mx-auto">
      <h1 className="text-xl font-semibold mb-2">Redirecting…</h1>
      <p className="text-sm text-muted-foreground">
        The at-risk view has moved to the retention engine on the
        Overview screen. Taking you there now.
      </p>
    </div>
  );
}
