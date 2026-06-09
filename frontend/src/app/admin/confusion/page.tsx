"use client";

/**
 * /admin/confusion — RETIRED.
 *
 * Merged into /admin/content (Confusion tab) so admins have one
 * route for everything content-quality-related instead of two
 * sibling pages with overlapping data.
 *
 * Old bookmarks land here and redirect with the Confusion tab
 * pre-selected (default).
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function LegacyConfusionRedirectPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/content");
  }, [router]);
  return null;
}
