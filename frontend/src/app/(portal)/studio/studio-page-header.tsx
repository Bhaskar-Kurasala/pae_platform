"use client";

import { useEffect, useState } from "react";
import { ListChecks, Medal, X } from "lucide-react";
import { StreakBadge } from "@/components/features/studio/streak-badge";
import { BadgeGallery } from "@/components/features/studio/badge-system";

/**
 * Client component that renders the Studio page header.
 * Owns the challenge-drawer open/close state so the server
 * page component stays as a Server Component.
 */
export function StudioPageHeader() {
  const [badgesOpen, setBadgesOpen] = useState(false);

  useEffect(() => {
    if (!badgesOpen) return;
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") setBadgesOpen(false); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [badgesOpen]);

  return (
    <>
      <div className="flex items-center justify-between border-b border-border bg-card px-4 py-3">
        <div className="flex items-center gap-3">
          {/* Challenge ladder trigger */}
          <button
            type="button"
            onClick={() => window.dispatchEvent(new CustomEvent("studio:open-challenges"))}
            aria-label="Open challenge ladder"
            title="Challenge Ladder — pick a coding challenge by difficulty"
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs font-medium text-foreground transition hover:bg-muted"
          >
            <ListChecks className="h-3.5 w-3.5" aria-hidden="true" />
            Challenges
          </button>

          <div>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Studio
            </p>
            <h1 className="text-lg font-semibold leading-tight">Code · Tutor · Trace</h1>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* P3-2 — badge gallery trigger */}
          <button
            type="button"
            onClick={() => setBadgesOpen(true)}
            aria-label="View earned badges"
            title="Badges — view your achievements"
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs font-medium text-foreground transition hover:bg-muted"
          >
            <Medal className="h-3.5 w-3.5" aria-hidden="true" />
            Badges
          </button>
          <StreakBadge />
        </div>
      </div>

      {/* P3-2 — Badge gallery modal */}
      {badgesOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Badge gallery"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget) setBadgesOpen(false);
          }}
        >
          <div className="w-full max-w-2xl rounded-xl border border-border bg-card shadow-xl">
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <div className="flex items-center gap-2">
                <Medal className="h-5 w-5 text-yellow-600" aria-hidden="true" />
                <h2 className="font-semibold">Your Badges</h2>
              </div>
              <button
                type="button"
                onClick={() => setBadgesOpen(false)}
                aria-label="Close badge gallery"
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            <div className="p-5">
              <BadgeGallery />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
