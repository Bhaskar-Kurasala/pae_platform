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
  // gold = the same accent the action band uses for promotions/
  // streaks, lifts important numbers + section eyebrows out of the
  // visual baseline.
  const surface = isDark
    ? {
        bg: "#1a2620",
        panelBg: "#243430",
        panelBg2: "#2c3e37",
        ink: "#f0e8d3",
        ink2: "#d6cebf",
        muted: "#8a9890",
        gold: "#d6a54d",
        border: "rgba(208, 212, 207, 0.10)",
        borderTop: "rgba(255, 255, 255, 0.06)", // chiselled top-edge
        ring: "rgba(208, 212, 207, 0.06)",
        backdrop: "rgba(8, 12, 10, 0.65)",
        // Subtle gradient to give cards depth without being noisy.
        cardGradient:
          "linear-gradient(180deg, rgba(255,255,255,0.02), transparent)",
      }
    : {
        bg: "#fbf8f1",
        panelBg: "#ffffff",
        panelBg2: "#fdfbf6",
        ink: "#1a2620",
        ink2: "#3a3a3a",
        muted: "#6f7a73",
        gold: "#b8862d",
        border: "rgba(26, 38, 32, 0.10)",
        borderTop: "rgba(255, 255, 255, 0.6)",
        ring: "rgba(26, 38, 32, 0.06)",
        backdrop: "rgba(8, 12, 10, 0.40)",
        cardGradient:
          "linear-gradient(180deg, rgba(255,255,255,0.6), transparent)",
      };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        {/* Backdrop — deep darken + subtle blur */}
        <DialogPrimitive.Backdrop
          className="fixed inset-0 z-50 transition-opacity duration-200 data-ending-style:opacity-0 data-starting-style:opacity-0 supports-backdrop-filter:backdrop-blur-sm"
          style={{ backgroundColor: surface.backdrop }}
        />
        {/* Popup — centered, ~920px, animated zoom-in.
            Chiselled top-edge highlight + softer corner radius +
            slightly heavier shadow gives the modal more presence
            against the cockpit backdrop. */}
        <DialogPrimitive.Popup
          data-theme={pageTheme}
          className="fixed top-1/2 left-1/2 z-50 flex w-[calc(100vw-2rem)] max-w-[920px] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden outline-none transition duration-200 data-ending-style:scale-[0.96] data-ending-style:opacity-0 data-starting-style:scale-[0.96] data-starting-style:opacity-0"
          style={{
            backgroundColor: surface.bg,
            color: surface.ink,
            borderRadius: 20,
            maxHeight: "calc(100vh - 4rem)",
            boxShadow: isDark
              ? `0 40px 100px rgba(0,0,0,0.7), 0 0 0 1px ${surface.ring}, inset 0 1px 0 ${surface.borderTop}`
              : `0 40px 100px rgba(20,30,25,0.20), 0 0 0 1px ${surface.ring}, inset 0 1px 0 ${surface.borderTop}`,
          }}
        >
          {/* Header — stays pinned while body scrolls. Subtle gradient
              gives it weight; a soft separator (not a hard 1px line)
              fades into the body. */}
          <div
            className="flex items-start gap-3 px-7 py-5"
            style={{
              background: surface.cardGradient,
              borderBottom: `1px solid ${surface.border}`,
            }}
          >
            <div className="min-w-0 flex-1">
              {/* Eyebrow — gold, mono, uppercase. Same vocabulary as
                  the action band's "THIS WEEK'S CALL LIST" eyebrow. */}
              <div
                className="text-[10px] font-semibold tracking-[0.18em] uppercase mb-1.5"
                style={{
                  color: surface.gold,
                  fontFamily: "var(--font-mono, ui-monospace, monospace)",
                }}
              >
                Student profile
              </div>
              <DialogPrimitive.Title
                className="truncate text-2xl font-bold leading-tight"
                style={{ color: surface.ink, letterSpacing: "-0.01em" }}
              >
                {student?.full_name ?? "Student"}
              </DialogPrimitive.Title>
              <DialogPrimitive.Description
                className="truncate text-sm mt-1"
                style={{ color: surface.muted }}
              >
                {student?.email ?? studentId ?? ""}
              </DialogPrimitive.Description>
              {student && (
                <div
                  className="mt-3 flex flex-wrap items-center gap-2.5 text-xs"
                  style={{ color: surface.muted }}
                >
                  <Badge
                    className={
                      student.is_active
                        ? "bg-emerald-500/15 text-emerald-600 hover:bg-emerald-500/20 border-0 dark:text-emerald-400"
                        : "bg-zinc-500/15 text-zinc-400 border-0"
                    }
                  >
                    {student.is_active ? "Active" : "Inactive"}
                  </Badge>
                  <span>
                    <span
                      className="font-semibold tabular-nums"
                      style={{
                        color: surface.ink,
                        fontFamily:
                          "var(--font-mono, ui-monospace, monospace)",
                      }}
                    >
                      {student.lessons_completed}
                    </span>{" "}
                    lessons
                  </span>
                  <span style={{ opacity: 0.4 }}>·</span>
                  <span>
                    <span
                      className="font-semibold tabular-nums"
                      style={{
                        color: surface.ink,
                        fontFamily:
                          "var(--font-mono, ui-monospace, monospace)",
                      }}
                    >
                      {student.agent_interactions}
                    </span>{" "}
                    chats
                  </span>
                  <span style={{ opacity: 0.4 }}>·</span>
                  <span>
                    Joined{" "}
                    <span
                      style={{
                        color: surface.ink2,
                        fontFamily:
                          "var(--font-mono, ui-monospace, monospace)",
                      }}
                    >
                      {new Date(student.created_at).toLocaleDateString()}
                    </span>
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
              className="flex-1 overflow-y-auto px-7 py-6"
              style={{ backgroundColor: surface.bg }}
            >
              {/* Premium-tone CSS scoped to the modal body. Splits
                  into light + dark blocks so the modal feels native
                  to whichever cockpit theme the operator chose:
                  • Cards lift via subtle gradient + chiselled
                    top-edge highlight (inset 0 1px 0 ...)
                  • Card section headings get a gold eyebrow accent
                  • All numerical values in counts/timestamps use
                    JetBrains Mono for the action-band aesthetic
                  • Card hover state: subtle shadow + border lift */}
              <style>{`
                /* === Shared (light + dark) === */
                .careerforge-modal-body [data-slot="card"] {
                  border-radius: 14px !important;
                  transition: box-shadow 200ms ease, border-color 200ms ease;
                  position: relative;
                }
                .careerforge-modal-body [data-slot="card-header"] h2 {
                  font-size: 13px;
                  letter-spacing: 0.01em;
                }
                .careerforge-modal-body .tabular-nums {
                  font-family: var(--font-mono, ui-monospace, monospace);
                }
                .careerforge-modal-body time,
                .careerforge-modal-body [data-slot="card-content"] p.text-\\[10px\\],
                .careerforge-modal-body [data-slot="card-content"] p.text-xs.text-muted-foreground {
                  font-family: var(--font-mono, ui-monospace, monospace);
                  font-feature-settings: "tnum";
                }
              `}</style>
              {isDark ? (
                <style>{`
                  /* === Dark cockpit theme === */
                  .careerforge-modal-body textarea,
                  .careerforge-modal-body input[type="text"],
                  .careerforge-modal-body input[type="email"],
                  .careerforge-modal-body input[type="search"] {
                    background-color: rgba(255, 255, 255, 0.03) !important;
                    color: ${surface.ink} !important;
                    border-color: ${surface.border} !important;
                  }
                  .careerforge-modal-body textarea:focus,
                  .careerforge-modal-body input:focus {
                    border-color: rgba(95, 163, 127, 0.40) !important;
                    box-shadow: 0 0 0 3px rgba(95, 163, 127, 0.10);
                  }
                  .careerforge-modal-body textarea::placeholder,
                  .careerforge-modal-body input::placeholder {
                    color: ${surface.muted} !important;
                  }
                  /* Ghost-style links/buttons (Schedule call, Load older). */
                  .careerforge-modal-body a[href^="mailto:"],
                  .careerforge-modal-body button.border,
                  .careerforge-modal-body a.border {
                    color: ${surface.ink} !important;
                    background-color: rgba(255, 255, 255, 0.02) !important;
                    border-color: ${surface.border} !important;
                  }
                  .careerforge-modal-body a[href^="mailto:"]:hover,
                  .careerforge-modal-body button.border:hover {
                    background-color: rgba(255, 255, 255, 0.05) !important;
                  }
                  /* Saved-message bodies + saved-note rows. */
                  .careerforge-modal-body pre {
                    color: ${surface.ink} !important;
                  }
                  .careerforge-modal-body li.rounded-lg {
                    background-color: rgba(255, 255, 255, 0.03) !important;
                    border-color: ${surface.border} !important;
                  }
                  .careerforge-modal-body li.border-primary\\/30 {
                    background-color: rgba(95, 163, 127, 0.10) !important;
                    border-color: rgba(95, 163, 127, 0.45) !important;
                  }
                  /* Card surface: layered (panel-bg + subtle gradient
                     + chiselled top-edge highlight) so cards feel
                     dimensional, not flat. */
                  .careerforge-modal-body [data-slot="card"] {
                    background-color: ${surface.panelBg} !important;
                    background-image: ${surface.cardGradient};
                    border: 1px solid ${surface.border} !important;
                    box-shadow: inset 0 1px 0 ${surface.borderTop};
                  }
                  .careerforge-modal-body [data-slot="card"]:hover {
                    border-color: rgba(208, 212, 207, 0.16) !important;
                    box-shadow:
                      inset 0 1px 0 ${surface.borderTop},
                      0 8px 24px rgba(0, 0, 0, 0.20);
                  }
                  .careerforge-modal-body .text-muted-foreground {
                    color: ${surface.muted} !important;
                  }
                  .careerforge-modal-body .text-foreground,
                  .careerforge-modal-body .font-semibold,
                  .careerforge-modal-body h1,
                  .careerforge-modal-body h2,
                  .careerforge-modal-body p {
                    color: ${surface.ink};
                  }
                  /* Card section headers ("Trigger agent", "Admin notes"
                     etc.) — keep their lucide icon in primary green;
                     bump the heading text to the gold accent so it
                     matches the cockpit's section eyebrows. */
                  .careerforge-modal-body [data-slot="card-header"] h2 {
                    color: ${surface.ink} !important;
                  }
                `}</style>
              ) : (
                <style>{`
                  /* === Light parchment theme === */
                  .careerforge-modal-body [data-slot="card"] {
                    background-color: ${surface.panelBg} !important;
                    background-image: ${surface.cardGradient};
                    border: 1px solid ${surface.border} !important;
                    box-shadow:
                      inset 0 1px 0 ${surface.borderTop},
                      0 1px 2px rgba(20, 30, 25, 0.04);
                  }
                  .careerforge-modal-body [data-slot="card"]:hover {
                    border-color: rgba(26, 38, 32, 0.16) !important;
                    box-shadow:
                      inset 0 1px 0 ${surface.borderTop},
                      0 8px 24px rgba(20, 30, 25, 0.08);
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
