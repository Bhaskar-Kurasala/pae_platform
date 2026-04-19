/**
 * ChatSkeleton — loading shimmer for the chat surface.
 *
 * Used as the Suspense fallback on `/chat`. Mirrors the real layout:
 *   - Sidebar shimmer (lg+ only, same width as <Sidebar />).
 *   - Centered welcome-like shimmer: circular bot icon + title + subtitle
 *     + 2x3 grid of suggested-prompt tiles (matches SUGGESTED_PROMPTS count).
 *   - Composer shimmer: rounded pill at the bottom.
 *
 * Uses the shared <Skeleton /> primitive so colors adapt to light/dark mode
 * via the existing design tokens.
 */
import { Skeleton } from "@/components/ui/skeleton";

export function ChatSkeleton() {
  return (
    <div className="flex h-full w-full" aria-busy="true" aria-label="Loading chat">
      {/* Sidebar shimmer — hidden on mobile, matches <Sidebar /> widths */}
      <aside className="hidden lg:flex flex-col w-64 xl:w-72 border-r bg-card/50 shrink-0">
        <div className="flex items-center justify-between px-4 h-16 border-b shrink-0">
          <div className="flex items-center gap-2">
            <Skeleton className="h-7 w-7 rounded-lg" />
            <Skeleton className="h-4 w-20 rounded" />
          </div>
          <Skeleton className="h-8 w-8 rounded-lg" />
        </div>
        <div className="flex-1 overflow-hidden py-3 px-2 space-y-1">
          <Skeleton className="h-3 w-16 rounded mx-2 mb-3" />
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-xl px-3 py-2.5 space-y-2">
              <Skeleton className="h-4 w-full rounded" />
              <div className="flex gap-2">
                <Skeleton className="h-3 w-16 rounded" />
                <Skeleton className="h-3 w-12 rounded" />
              </div>
            </div>
          ))}
        </div>
      </aside>

      {/* Main area shimmer */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 gap-8">
          {/* Bot icon shimmer */}
          <Skeleton className="h-20 w-20 rounded-3xl" />

          {/* Title + subtitle */}
          <div className="flex flex-col items-center gap-3 max-w-md w-full">
            <Skeleton className="h-7 w-48 rounded-md" />
            <Skeleton className="h-4 w-72 rounded" />
          </div>

          {/* Suggested-prompt tile grid — matches SUGGESTED_PROMPTS (6 items) */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 w-full max-w-4xl">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="flex items-start gap-3 rounded-2xl border border-border/60 bg-card/80 px-4 py-3.5"
              >
                <Skeleton className="h-5 w-5 rounded shrink-0 mt-0.5" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3 w-full rounded" />
                  <Skeleton className="h-3 w-4/5 rounded" />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Composer shimmer */}
        <div className="border-t bg-background/80 backdrop-blur-sm px-4 py-4">
          <div className="max-w-3xl mx-auto">
            <Skeleton className="h-14 w-full rounded-full" />
          </div>
        </div>
      </div>
    </div>
  );
}
