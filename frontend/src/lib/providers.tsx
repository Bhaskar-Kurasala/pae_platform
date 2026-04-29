"use client";

import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState } from "react";
import { GlobalCommandPalette } from "@/components/features/global-command-palette";
import { RouteLoadingBar } from "@/components/ui/route-loading-bar";
import { Toaster } from "@/components/ui/sonner";
import { ApiError, ApiTimeoutError } from "@/lib/api-client";
import { toast } from "@/lib/toast";

/**
 * PR2/B1.1 — global error toasts for every useQuery / useMutation.
 *
 * Classifies the error and shows a single sane toast unless the hook
 * opts out by setting `meta: { skipErrorToast: true }`. The classifier
 * is intentionally short — three buckets cover the vast majority of
 * failures students will hit in production:
 *
 *   - ApiTimeoutError → "Request took too long"
 *   - ApiError 401     → silent (the api-client interceptor already
 *                        handles refresh + redirect; surfacing a toast
 *                        on top would be noise)
 *   - ApiError 4xx/5xx → backend message if user-readable, else a
 *                        bland "Something went wrong" with the
 *                        request_id we can ship to support
 *   - everything else   → "Something went wrong"
 *
 * Mutations always get the toast because a failed mutation is something
 * the user is actively trying to do; a query failure on a passive
 * background refetch can get suppressed via `meta`.
 */
function showErrorToast(
  err: unknown,
  meta: { skipErrorToast?: boolean } | undefined,
): void {
  if (meta?.skipErrorToast) return;
  if (err instanceof ApiTimeoutError) {
    toast.error(err.message);
    return;
  }
  if (err instanceof ApiError) {
    if (err.status === 401) return; // refresh+redirect handled in api-client
    // Backend wraps errors in {"error": {"message", "request_id"}} via
    // the PR2/B4.1 exception handler. Prefer that over slowapi's
    // "detail" or the canned message we built when the JSON had no
    // `detail` field at all.
    const body = err.body as
      | { error?: { message?: string; request_id?: string } }
      | { detail?: string }
      | undefined;
    const fromEnvelope = body && "error" in body ? body.error?.message : null;
    const fromDetail = body && "detail" in body ? body.detail : null;
    const text = fromEnvelope || fromDetail || err.message || "Something went wrong";
    toast.error(text);
    return;
  }
  toast.error("Something went wrong. Please try again.");
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({
          onError: (error, query) => {
            // For passive background refetches, only toast when there's
            // no cached data (i.e. the user is staring at a spinner).
            // A silent refetch that fails but the screen still has data
            // shouldn't bother the student.
            const hasCachedData = query.state.data !== undefined;
            if (hasCachedData) return;
            showErrorToast(
              error,
              query.meta as { skipErrorToast?: boolean } | undefined,
            );
          },
        }),
        mutationCache: new MutationCache({
          onError: (error, _vars, _ctx, mutation) => {
            showErrorToast(
              error,
              mutation.meta as { skipErrorToast?: boolean } | undefined,
            );
          },
        }),
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            retry: 1,
          },
          mutations: {
            retry: 0,
          },
        },
      }),
  );

  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      <QueryClientProvider client={queryClient}>
        <RouteLoadingBar />
        {children}
        <GlobalCommandPalette />
        <Toaster position="bottom-right" richColors closeButton />
      </QueryClientProvider>
    </ThemeProvider>
  );
}
