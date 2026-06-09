"use client";

/**
 * /admin/pulse — RETIRED.
 *
 * The cockpit at /admin already renders the canonical Platform Pulse
 * strip with 24h / 7d / 30d window toggles, and the underlying data
 * is the same. Two pages showing overlapping signals erodes trust
 * ("which one is right?"), so /admin/pulse was killed in favour of
 * the cockpit being the single source of truth.
 *
 * Old bookmarks land here and redirect to /admin so they don't 404.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function LegacyPulseRedirectPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin");
  }, [router]);
  return null;
}
