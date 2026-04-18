"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Loader2, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { usePeerGallery } from "@/lib/hooks/use-peer-gallery";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

interface Props {
  exerciseId: string;
  className?: string;
}

export function PeerGallery({ exerciseId, className }: Props) {
  const { data, isLoading, isError } = usePeerGallery(exerciseId);
  const [openId, setOpenId] = useState<string | null>(null);

  if (isLoading) {
    return (
      <div
        className={cn(
          "rounded-xl border border-foreground/10 bg-card p-4 text-sm text-muted-foreground",
          className,
        )}
      >
        <Loader2 className="mr-2 inline-block h-4 w-4 animate-spin" aria-hidden="true" />
        Loading peer submissions…
      </div>
    );
  }

  if (isError) {
    return (
      <div
        className={cn(
          "rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400",
          className,
        )}
      >
        Couldn&apos;t load peer gallery.
      </div>
    );
  }

  const items = data ?? [];

  return (
    <section
      className={cn("rounded-xl border border-foreground/10 bg-card p-4 md:p-5", className)}
      aria-labelledby="peer-gallery-heading"
    >
      <header className="flex items-center gap-2">
        <Users className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        <h3
          id="peer-gallery-heading"
          className="text-sm font-semibold uppercase tracking-wider text-muted-foreground"
        >
          Peer solutions
        </h3>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {items.length}
        </span>
      </header>

      {items.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          No one has shared a solution yet. Be the first by ticking
          &ldquo;share with peers&rdquo; on your next submission.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {items.map((item) => {
            const isOpen = openId === item.id;
            return (
              <li
                key={item.id}
                className="rounded-lg border border-foreground/10 bg-background"
              >
                <button
                  type="button"
                  onClick={() => setOpenId(isOpen ? null : item.id)}
                  aria-expanded={isOpen}
                  className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition hover:bg-foreground/[0.02]"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-foreground">
                        {item.author_handle}
                      </span>
                      <span className="text-[11px] text-muted-foreground">
                        {formatDate(item.created_at)}
                      </span>
                      {typeof item.score === "number" ? (
                        <span className="rounded border border-foreground/10 bg-foreground/[0.04] px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          {item.score}
                        </span>
                      ) : null}
                    </div>
                    {item.share_note ? (
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {item.share_note}
                      </p>
                    ) : null}
                  </div>
                  {isOpen ? (
                    <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                </button>
                {isOpen && item.code ? (
                  <pre className="overflow-x-auto border-t border-foreground/10 bg-muted/40 p-3 text-[12px] font-mono leading-relaxed text-foreground">
                    {item.code}
                  </pre>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
