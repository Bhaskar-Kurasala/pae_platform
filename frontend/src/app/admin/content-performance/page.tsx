"use client";

/**
 * /admin/content-performance — RETIRED.
 *
 * Merged into /admin/content (Performance tab). Old bookmarks land
 * here and redirect; we don't bother pre-selecting the Performance
 * tab in the URL since admins arriving from this URL will likely
 * scan both tabs anyway.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function LegacyContentPerformanceRedirectPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/content");
  }, [router]);
  return null;
}
