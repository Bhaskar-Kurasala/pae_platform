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
import { showErrorToast } from "@/lib/error-toast";

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
