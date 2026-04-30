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
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { X } from "lucide-react";
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

  // While the modal is open in dark mode, mirror the page-island
  // theme onto <html class="dark"> so portal-rendered popovers
  // (shadcn Select content, tooltips) inherit dark tokens too.
  // Without this, the Select's ChevronDown popup renders with
  // light-mode bg-popover even though the modal around it is dark.
  // We restore the prior value on close so the rest of the app
  // (which uses media-query-based dark mode) is unaffected.
  useEffect(() => {
    if (!open || !isDark) return;
    const html = document.documentElement;
    const had = html.classList.contains("dark");
    html.classList.add("dark");
    return () => {
      if (!had) html.classList.remove("dark");
    };
  }, [open, isDark]);

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
            {/* Close button — Esc / backdrop click also work. The
                "Full page" link was removed: the modal now contains
                the same data the route page does, and the route is
                still reachable via /admin/students/<id> for the rare
                deep-link/share case. */}
            <DialogPrimitive.Close
              className="inline-flex h-8 w-8 items-center justify-center rounded-full transition outline-none shrink-0"
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

          {/* Body — scrollable */}
          {showPanel && mounted ? (
            <div
              className="flex-1 overflow-y-auto px-6 py-5"
              style={{ backgroundColor: surface.bg }}
            >
              {/* The shared <StudentDetailPanel> uses Tailwind tokens
                  like bg-background / text-foreground / border-input
                  that are tuned for the global light theme. When the
                  page is in CareerForge dark, those tokens fall back
                  to colors that vanish into our dark surface (textarea
                  text reads black-on-near-black, the select renders
                  as a black stripe, etc.).

                  Rather than re-theming every utility class inside
                  the panel, we scope a small CSS block to the modal's
                  body when data-theme="dark" — explicit, isolated,
                  and only affects content rendered inside this
                  modal. */}
              {isDark && (
                <style>{`
                  .careerforge-modal-body textarea,
                  .careerforge-modal-body select,
                  .careerforge-modal-body input[type="text"],
                  .careerforge-modal-body input[type="email"],
                  .careerforge-modal-body input[type="search"] {
                    background-color: rgba(255, 255, 255, 0.04) !important;
                    color: #f0e8d3 !important;
                    border-color: rgba(208, 212, 207, 0.18) !important;
                  }
                  /* color-scheme: dark tells the browser to render
                     native form chrome (the <select> popup, the
                     scrollbar, the focus ring) in its dark variant
                     from the first paint — without it, Chrome opens
                     the popup in default light, then our CSS recolors
                     the options a frame later, producing a visible
                     white→dark flash. */
                  .careerforge-modal-body select {
                    color-scheme: dark;
                  }
                  .careerforge-modal-body textarea::placeholder,
                  .careerforge-modal-body input::placeholder {
                    color: #8a9890 !important;
                  }
                  .careerforge-modal-body select option {
                    background-color: #243430;
                    color: #f0e8d3;
                  }
                  /* "Schedule call" link, "Load older" button, and any
                     other ghost button rendered as a bordered link/btn. */
                  .careerforge-modal-body a[href^="mailto:"],
                  .careerforge-modal-body button.border,
                  .careerforge-modal-body a.border {
                    color: #f0e8d3 !important;
                  }
                  /* DM message body + admin notes saved rows: the panel
                     uses bg-background/50 and bg-primary/5 which both
                     render as near-black against our dark surface.
                     Override the body text + the message bubble bg. */
                  .careerforge-modal-body pre {
                    color: #f0e8d3 !important;
                  }
                  .careerforge-modal-body li.rounded-lg {
                    background-color: rgba(255, 255, 255, 0.03) !important;
                    border-color: rgba(208, 212, 207, 0.14) !important;
                  }
                  /* The admin's own DM bubble had a primary-tint highlight
                     in light mode; preserve the highlight in dark too. */
                  .careerforge-modal-body li.border-primary\\/30 {
                    background-color: rgba(95, 163, 127, 0.10) !important;
                    border-color: rgba(95, 163, 127, 0.40) !important;
                  }
                  /* Card surface — sits one shade above the modal bg
                     so cards have a subtle lift. */
                  .careerforge-modal-body [data-slot="card"] {
                    background-color: #243430 !important;
                    border-color: rgba(208, 212, 207, 0.10) !important;
                  }
                  /* All small muted/timestamp text inside the modal
                     was using text-muted-foreground which mapped to
                     a near-black hex. Bump it to a readable dim. */
                  .careerforge-modal-body .text-muted-foreground {
                    color: #8a9890 !important;
                  }
                  .careerforge-modal-body .text-foreground,
                  .careerforge-modal-body .font-semibold,
                  .careerforge-modal-body h1,
                  .careerforge-modal-body h2,
                  .careerforge-modal-body p {
                    color: #f0e8d3;
                  }
                `}</style>
              )}
              <div className="careerforge-modal-body">
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
