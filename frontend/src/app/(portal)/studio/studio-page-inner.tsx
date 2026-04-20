"use client";

import { useSearchParams } from "next/navigation";
import { StudioLayout } from "@/components/features/studio/studio-layout";

/**
 * Thin client wrapper that reads the optional `?code=` search param
 * (base64-encoded source code from "Try in Studio" deep-links) and
 * passes it to StudioLayout as the initial editor contents.
 *
 * Must be wrapped in <Suspense> by the parent server component because
 * Next.js requires Suspense around useSearchParams() calls.
 */
export function StudioPageInner() {
  const searchParams = useSearchParams();
  const encoded = searchParams.get("code");

  let initialCode: string | undefined;
  if (encoded) {
    try {
      // Symmetric decode of btoa(unescape(encodeURIComponent(code))) used in chat
      initialCode = decodeURIComponent(escape(atob(encoded)));
    } catch {
      // Malformed base64 — ignore and open with blank editor
    }
  }

  return <StudioLayout initialCode={initialCode} />;
}
