"use client";

/**
 * <StudentDetailModal> — focused centered popup for a single student.
 *
 * The admin's daily triage flow: click any student card / roster row
 * on /admin → this modal rises into the centre with everything they
 * need to act on that one student. Press Esc / click backdrop /
 * click X → modal closes, admin is back in the cockpit, no nav,
 * no scroll loss.
 *
 * Why centered modal not side-drawer:
 *   • Student detail isn't "scan while glancing back at the list" —
 *     it's "focus + take action". Centered modal signals that.
 *   • Operator visually commits to one student at a time. Sending a
 *     refund offer or DM has weight — the modal makes it feel
 *     deliberate.
 *   • Backdrop blur turns the cockpit into ambient context the
 *     admin can return to instantly.
 *
 * Theme-aware: detects the page's data-theme="dark" island and
 * applies matching surface tokens, so the modal looks native to
 * both light (warm parchment) and CareerForge dark (deep green)
 * cockpit themes.
 *
 * Renders the canonical <StudentDetailPanel>. Same data, same
 * cards, same business logic the full-page route uses.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { ExternalLink, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useAdminStudents } from "@/lib/hooks/use-admin";
import { StudentDetailPanel } from "./student-detail-panel";

interface StudentDetailModalProps {
  studentId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Page-level theme. The /admin overview has its own data-theme
   * island (light/dark) controlled by the top-bar toggle. We pass
   * it in explicitly so the modal can match — feels native to
   * whichever cockpit theme the operator chose.
   */
  pageTheme?: "light" | "dark";
}

export function StudentDetailModal({
  studentId,
  open,
  onOpenChange,
  pageTheme = "light",
}: StudentDetailModalProps) {
  const { data: students } = useAdminStudents();
  const student = students?.find((s) => s.id === studentId) ?? null;

  // Don't render the panel until we have a target.
  const showPanel = open && !!studentId;

  // Mount-state tracker so we can avoid SSR mismatches on theme.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const isDark = pageTheme === "dark";

  // Surface tokens — handpicked to match the CareerForge palette
  // (console.module.css). Light mode uses the warm parchment from
  // --bg-2 / ink; dark mode uses the deep forest from --panel / ink.
  const surface = isDark
    ? {
        bg: "#1e2a23",
        panelBg: "#243430",
        ink: "#f0e8d3",
        ink2: "#d6cebf",
        muted: "#8a9890",
        border: "rgba(208, 212, 207, 0.10)",
        ring: "rgba(208, 212, 207, 0.06)",
        backdrop: "rgba(8, 12, 10, 0.65)",
      }
    : {
        bg: "#fbf8f1",
        panelBg: "#ffffff",
        ink: "#1a2620",
        ink2: "#3a3a3a",
        muted: "#6f7a73",
        border: "rgba(26, 38, 32, 0.10)",
        ring: "rgba(26, 38, 32, 0.06)",
        backdrop: "rgba(8, 12, 10, 0.40)",
      };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        {/* Backdrop — deep darken + subtle blur */}
        <DialogPrimitive.Backdrop
          className="fixed inset-0 z-50 transition-opacity duration-200 data-ending-style:opacity-0 data-starting-style:opacity-0 supports-backdrop-filter:backdrop-blur-sm"
          style={{ backgroundColor: surface.backdrop }}
        />
        {/* Popup — centered, ~920px, animated zoom-in */}
        <DialogPrimitive.Popup
          data-theme={pageTheme}
          className="fixed top-1/2 left-1/2 z-50 flex w-[calc(100vw-2rem)] max-w-[920px] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl shadow-2xl outline-none transition duration-200 data-ending-style:scale-[0.96] data-ending-style:opacity-0 data-starting-style:scale-[0.96] data-starting-style:opacity-0"
          style={{
            backgroundColor: surface.bg,
            color: surface.ink,
            // Cap height so the modal never blows past the viewport;
            // the inner body scrolls.
            maxHeight: "calc(100vh - 4rem)",
            boxShadow: isDark
              ? "0 30px 80px rgba(0,0,0,0.6), 0 0 0 1px " + surface.ring
              : "0 30px 80px rgba(20,30,25,0.18), 0 0 0 1px " + surface.ring,
          }}
        >
          {/* Header — stays pinned while body scrolls */}
          <div
            className="flex items-start gap-3 px-6 py-4"
            style={{ borderBottom: `1px solid ${surface.border}` }}
          >
            <div className="min-w-0 flex-1">
              <DialogPrimitive.Title
                className="truncate text-xl font-bold leading-tight"
                style={{ color: surface.ink }}
              >
                {student?.full_name ?? "Student"}
              </DialogPrimitive.Title>
              <DialogPrimitive.Description
                className="truncate text-sm mt-0.5"
                style={{ color: surface.muted }}
              >
                {student?.email ?? studentId ?? ""}
              </DialogPrimitive.Description>
              {student && (
                <div
                  className="mt-2 flex flex-wrap items-center gap-2 text-xs"
                  style={{ color: surface.muted }}
                >
                  <Badge
                    className={
                      student.is_active
                        ? "bg-emerald-500/15 text-emerald-500 hover:bg-emerald-500/20 border-0"
                        : "bg-zinc-500/15 text-zinc-400 border-0"
                    }
                  >
                    {student.is_active ? "Active" : "Inactive"}
                  </Badge>
                  <span>{student.lessons_completed} lessons</span>
                  <span>·</span>
                  <span>{student.agent_interactions} chats</span>
                  <span>·</span>
                  <span>
                    Joined {new Date(student.created_at).toLocaleDateString()}
                  </span>
                </div>
              )}
            </div>
            {/* Right-side header controls */}
            <div className="flex items-center gap-2 shrink-0 pt-0.5">
              {studentId && (
                <Link
                  href={`/admin/students/${studentId}`}
                  className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition"
                  title="Open the full-page view (good for bookmarks or sharing a direct link)"
                  style={{
                    color: surface.ink2,
                    border: `1px solid ${surface.border}`,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = isDark
                      ? "rgba(208,212,207,0.05)"
                      : "rgba(26,38,32,0.04)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = "transparent";
                  }}
                >
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                  Full page
                </Link>
              )}
              <DialogPrimitive.Close
                className="inline-flex h-8 w-8 items-center justify-center rounded-full transition outline-none"
                aria-label="Close"
                style={{ color: surface.ink2 }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = isDark
                    ? "rgba(208,212,207,0.08)"
                    : "rgba(26,38,32,0.06)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = "transparent";
                }}
              >
                <X className="h-4 w-4" />
              </DialogPrimitive.Close>
            </div>
          </div>

          {/* Body — scrollable */}
          {showPanel && mounted ? (
            <div
              className="flex-1 overflow-y-auto px-6 py-5"
              style={{ backgroundColor: surface.bg }}
            >
              {/* Wrap the panel in a div that overrides the cards'
                  bg-card with the modal surface, so cards sit on a
                  slightly raised panelBg above the modal bg. */}
              <div
                style={
                  {
                    "--card": surface.panelBg,
                    "--background": surface.bg,
                    "--foreground": surface.ink,
                    "--muted-foreground": surface.muted,
                    "--border": surface.border,
                  } as React.CSSProperties
                }
              >
                <StudentDetailPanel
                  studentId={studentId}
                  hideHeader
                  compact
                />
              </div>
            </div>
          ) : (
            <div
              className="flex-1 flex items-center justify-center text-sm py-16"
              style={{ color: surface.muted }}
            >
              Loading…
            </div>
          )}
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
