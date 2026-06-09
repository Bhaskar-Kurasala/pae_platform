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
import { ResourceAuditPanel } from "./resource-audit-panel";

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

  // Mirror the admin page theme — modal matches whatever the cockpit is set to.
  const isDark = pageTheme === "dark";

  useEffect(() => {
    if (!open) return;
    const html = document.documentElement;
    const body = document.body;
    const had = html.classList.contains("dark");
    if (isDark) html.classList.add("dark");
    body.setAttribute("data-cf-modal-theme", pageTheme);
    return () => {
      if (!had) html.classList.remove("dark");
      body.removeAttribute("data-cf-modal-theme");
    };
  }, [open, isDark, pageTheme]);

  // Surface tokens — locked to the v8.css palette so the modal is
  // visually indistinguishable from /path. Every value here either
  // reads from a v8 CSS variable or matches a hex from v8.css 1:1.
  //
  //   light:  --bg #f6f1e8, --ink #10120e, --forest-2 #356d50,
  //           --gold #b8862d, --line #dbd1bf
  //   dark:   --bg #0e1411, --ink #f0ece1, --forest-3 #8fd6b1,
  //           --gold-2 #e8be72, --line #2c3830
  //
  // The card surface uses rgba(white,.82) + backdrop-filter:blur(10px)
  // in light, mirroring v8.css line 745. In dark we use the v8 panel
  // hex with the same blur. This gives cards the "frosted glass over a
  // warm gradient" feel that makes /path read premium instead of like
  // a generic shadcn surface.
  // Surface tokens match the admin cockpit palette exactly — dark uses
  // the actionBand forest gradient, light uses the console parchment.
  const surface = isDark
    ? {
        bgGradient: "linear-gradient(135deg, #19241e 0%, #243128 55%, #2d3d31 100%)",
        bg: "#19241e",
        cardBg: "rgba(255,255,255,0.05)",
        cardBorder: "rgba(255,255,255,0.09)",
        cardShadow: "0 4px 16px rgba(0,0,0,0.28), 0 1px 0 rgba(255,255,255,0.03) inset",
        cardShadowHover: "0 8px 32px rgba(0,0,0,0.40)",
        ink: "#f7f2e8",
        ink2: "#d6cebf",
        muted: "#c4baa6",
        muted2: "#9a9382",
        eyebrow: "#c8b88d",
        eyebrowDot: "#d96252",
        accent: "#5fa37f",
        accentSoft: "rgba(95,163,127,0.18)",
        gold: "#e8be72",
        line: "rgba(255,255,255,0.09)",
        borderTop: "rgba(255,255,255,0.06)",
        ring: "rgba(255,255,255,0.04)",
        backdrop: "rgba(0,0,0,0.65)",
        ctaShadow: "0 8px 24px rgba(95,163,127,0.28)",
        goldShadow: "0 12px 32px rgba(232,190,114,0.28)",
      }
    : {
        // Matches console.module.css light tokens exactly
        bgGradient: "radial-gradient(ellipse 120% 80% at 20% 0%, #fdfaf3, #f7f3ea 55%, #efe9d9 100%)",
        bg: "#f7f3ea",
        cardBg: "rgba(255,255,255,0.92)",
        cardBorder: "#e7decd",
        cardShadow: "0 1px 2px rgba(20,20,15,0.05), 0 4px 12px rgba(20,20,15,0.06)",
        cardShadowHover: "0 4px 8px rgba(20,20,15,0.06), 0 12px 28px rgba(20,20,15,0.08)",
        ink: "#1a2620",
        ink2: "#3a3a3a",
        muted: "#7a7565",
        muted2: "#a39d8d",
        eyebrow: "#356d50",
        eyebrowDot: "#4e9470",
        accent: "#1f4f37",
        accentSoft: "rgba(95,163,127,0.14)",
        gold: "#d6a54d",
        line: "#e7decd",
        borderTop: "rgba(255,255,255,0.8)",
        ring: "rgba(26,38,32,0.06)",
        backdrop: "rgba(8,12,10,0.28)",
        ctaShadow: "0 8px 24px rgba(31,79,55,0.20)",
        goldShadow: "0 12px 32px rgba(214,165,77,0.22)",
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
          className="fixed top-1/2 left-1/2 z-50 flex w-[calc(100vw-3rem)] max-w-[1160px] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden outline-none transition duration-200 data-ending-style:scale-[0.96] data-ending-style:opacity-0 data-starting-style:scale-[0.96] data-starting-style:opacity-0"
          style={{
            // Warm radial gradient — same primitive v8.css uses on
            // .hero / .path-hero. The blur/glass cards inside this
            // popup read this gradient through their .82 alpha, which
            // is what makes them feel "alive."
            background: surface.bgGradient,
            color: surface.ink,
            borderRadius: 22,
            maxHeight: "calc(100vh - 2rem)",
            boxShadow: isDark
              ? `0 40px 100px rgba(0,0,0,0.75), 0 0 0 1px ${surface.ring}, inset 0 1px 0 ${surface.borderTop}`
              : `0 40px 100px rgba(20,30,25,0.18), 0 0 0 1px ${surface.ring}, inset 0 1px 0 ${surface.borderTop}`,
          }}
        >
          {/* Header — stays pinned while body scrolls. Subtle gradient
              gives it weight; a soft separator (not a hard 1px line)
              fades into the body. */}
          <div
            className="flex items-start gap-3 px-7 py-5"
            style={{
              borderBottom: `1px solid ${surface.line}`,
              // Subtle ambient orbs behind the header echo the v8.css
              // .hero treatment (forest + gold rgba bleed). Gives the
              // header internal warmth instead of a flat band.
              backgroundImage: isDark
                ? `radial-gradient(ellipse 600px 200px at 20% 0%, rgba(143,214,177,0.08), transparent 70%), radial-gradient(ellipse 600px 200px at 80% 0%, rgba(232,190,114,0.06), transparent 70%)`
                : `radial-gradient(ellipse 600px 200px at 20% 0%, rgba(78,148,112,0.07), transparent 70%), radial-gradient(ellipse 600px 200px at 80% 0%, rgba(214,165,77,0.06), transparent 70%)`,
            }}
          >
            <div className="min-w-0 flex-1">
              {/* Eyebrow with leading dot — same primitive v8.css uses
                  on `.card-face-eyebrow` (10px, 0.2em tracking, weight
                  700, mint dot ::before with halo). */}
              <div
                className="cf-modal-eyebrow"
                style={{
                  color: surface.eyebrow,
                  ["--cf-eyebrow-dot" as string]: surface.eyebrowDot,
                  ["--cf-eyebrow-halo" as string]: isDark
                    ? "rgba(143, 214, 177, 0.18)"
                    : "rgba(78, 148, 112, 0.18)",
                }}
              >
                Student profile
              </div>
              {/* Title — Fraunces 36px/-0.04em matching console .abTitle */}
              <DialogPrimitive.Title
                className="truncate leading-[1.05]"
                style={{
                  color: isDark ? surface.gold : surface.ink,
                  fontFamily: "var(--font-fraunces), Georgia, serif",
                  fontSize: "36px",
                  fontWeight: 600,
                  letterSpacing: "-0.04em",
                  fontStyle: isDark ? "italic" : "normal",
                }}
              >
                {student?.full_name ?? "Student"}
              </DialogPrimitive.Title>
              {/* Email — identifier, treat it as code (mono). */}
              <DialogPrimitive.Description
                className="truncate text-sm mt-1.5"
                style={{
                  color: surface.ink2,
                  opacity: 0.7,
                  fontFamily:
                    "var(--font-jetbrains-mono), ui-monospace, monospace",
                  fontSize: "13px",
                  letterSpacing: "0.005em",
                }}
              >
                {student?.email ?? studentId ?? ""}
              </DialogPrimitive.Description>
              {student && (
                <div
                  className="mt-2 flex flex-wrap items-center gap-2 text-xs"
                  style={{
                    color: surface.muted,
                    fontFamily:
                      "var(--font-jetbrains-mono), ui-monospace, monospace",
                    fontFeatureSettings: '"tnum"',
                    letterSpacing: "0.01em",
                  }}
                >
                  {/* Active/Inactive chip — v8 .chip.forest primitive:
                      forest-tinted bg, forest-tinted border, weight
                      600 mono inside. */}
                  <Badge
                    className="border-0 uppercase tracking-[0.14em] text-[10px] font-semibold px-2.5 py-1"
                    style={{
                      fontFamily:
                        "var(--font-jetbrains-mono), ui-monospace, monospace",
                      background: student.is_active
                        ? surface.accentSoft
                        : isDark
                          ? "rgba(255,255,255,0.05)"
                          : "rgba(0,0,0,0.04)",
                      color: student.is_active
                        ? surface.eyebrow
                        : surface.muted,
                      borderRadius: 999,
                      boxShadow: student.is_active
                        ? `0 0 0 1px ${
                            isDark
                              ? "rgba(143,214,177,0.20)"
                              : "rgba(78,148,112,0.18)"
                          }`
                        : `0 0 0 1px ${surface.line}`,
                    }}
                  >
                    {student.is_active ? "Active" : "Inactive"}
                  </Badge>
                  <span>
                    <span
                      className="font-semibold"
                      style={{ color: surface.ink }}
                    >
                      {student.lessons_completed}
                    </span>{" "}
                    lessons
                  </span>
                  <span style={{ opacity: 0.4 }}>·</span>
                  <span>
                    <span
                      className="font-semibold"
                      style={{ color: surface.ink }}
                    >
                      {student.agent_interactions}
                    </span>{" "}
                    chats
                  </span>
                  <span style={{ opacity: 0.4 }}>·</span>
                  <span>
                    Joined{" "}
                    <span style={{ color: surface.ink2 }}>
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

          {/* Body — scrollable. Background is transparent so the
              popup's warm radial gradient bleeds through, exactly like
              the /path screen renders content over the page bg. */}
          {showPanel && mounted ? (
            <div className="flex-1 overflow-y-auto px-7 py-6">
              {/* === Modal body chrome — v8.css primitives applied to
                  the shadcn surfaces inside <StudentDetailPanel>. ===

                  Strategy: rather than rewrite the panel to use v8 CSS
                  classes (which would diverge it from the full-page
                  /admin/students/[id] route), we map shadcn's
                  data-slot="card" / "card-header" onto the same chrome
                  v8.css uses for `.card.pad`. This means the modal is
                  literally made of the same parts as /path while the
                  shared panel keeps a single source of truth. */}
              {/* Header eyebrow (Student profile) — same primitive as
                  the panel cards' eyebrow. Lives outside .careerforge-
                  modal-body so we declare it globally on the popup. */}
              <style>{`
                /* Modal header eyebrow — v8 .eyebrow: Inter 10px/700/0.2em/uppercase */
                [data-theme="${pageTheme}"] .cf-modal-eyebrow {
                  display: inline-flex;
                  align-items: center;
                  gap: 8px;
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  font-size: 10px;
                  letter-spacing: 0.2em;
                  text-transform: uppercase;
                  font-weight: 700;
                  margin-bottom: 12px;
                  color: ${surface.eyebrow};
                }
                [data-theme="${pageTheme}"] .cf-modal-eyebrow::before {
                  content: "";
                  width: 6px; height: 6px;
                  border-radius: 50%;
                  background: ${surface.eyebrowDot};
                  box-shadow: 0 0 0 4px ${isDark ? "rgba(143,214,177,0.18)" : "rgba(78,148,112,0.18)"};
                }
              `}</style>
              <style>{`
                /* ============================================================
                   STUDENT PROFILE MODAL — typography locked to today screen
                   Source of truth: v8.css .eyebrow / .step-state / .step-card
                   h5 / .step-card p / .mini-chip / .step-num / .section-title

                   IMPORTANT: The modal popup is a dialog portal — it does NOT
                   inherit body font-family. We must set Inter explicitly on the
                   root container so all children inherit it, exactly like v8.css
                   sets --sans on <body>. Without this, browser falls back to
                   Times New Roman for any element without an explicit font-family.
                   ============================================================ */

                /* Root font reset — Inter as base, matching v8.css body/--sans */
                .careerforge-modal-body,
                .careerforge-modal-body * {
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  box-sizing: border-box;
                }

                /* Card eyebrow — exact v8 .step-state values:
                   Inter, 11px, 800, 0.12em, uppercase, var(--muted) */
                .careerforge-modal-body .cf-card-eyebrow {
                  display: inline-flex;
                  align-items: center;
                  gap: 8px;
                  font-size: 11px;
                  font-weight: 800;
                  letter-spacing: 0.12em;
                  text-transform: uppercase;
                  color: ${surface.muted};
                  margin-bottom: 12px;
                }
                .careerforge-modal-body .cf-card-eyebrow::before {
                  content: "";
                  width: 6px; height: 6px;
                  border-radius: 50%;
                  flex-shrink: 0;
                  background: ${surface.eyebrowDot};
                  box-shadow: 0 0 0 4px ${isDark ? "rgba(143,214,177,0.18)" : "rgba(78,148,112,0.18)"};
                }

                /* Card title — exact v8 .step-card h5 values:
                   Fraunces serif, 18px, 500, -0.02em */
                .careerforge-modal-body .cf-card-title {
                  margin: 0;
                  font-family: var(--font-fraunces), 'Fraunces', Georgia, serif;
                  font-size: 18px;
                  font-weight: 500;
                  letter-spacing: -0.02em;
                  line-height: 1.2;
                  color: ${surface.ink};
                }

                /* Card title icon — exact v8 .step-num values:
                   34px circle, Fraunces, weight 600, var(--panel-2) bg */
                .careerforge-modal-body .cf-card-title-icon {
                  display: inline-grid;
                  place-items: center;
                  width: 34px; height: 34px;
                  border-radius: 50%;
                  flex-shrink: 0;
                  background: ${isDark ? "rgba(143,214,177,0.12)" : "rgba(53,109,80,0.10)"};
                  border: 1px solid ${isDark ? "rgba(143,214,177,0.20)" : "rgba(53,109,80,0.16)"};
                  color: ${surface.accent};
                }
                .careerforge-modal-body .cf-card-title-icon svg { width: 15px; height: 15px; }

                /* Gold icon tint — 2nd and 5th cards */
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(2) .cf-card-title-icon,
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(5) .cf-card-title-icon {
                  background: ${isDark ? "rgba(232,190,114,0.12)" : "rgba(214,165,77,0.10)"} !important;
                  border-color: ${isDark ? "rgba(232,190,114,0.22)" : "rgba(214,165,77,0.20)"} !important;
                  color: ${surface.gold} !important;
                }
                /* Rose icon tint — 3rd card */
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(3) .cf-card-title-icon {
                  background: ${isDark ? "rgba(217,98,82,0.12)" : "rgba(192,97,79,0.09)"} !important;
                  border-color: ${isDark ? "rgba(217,98,82,0.22)" : "rgba(192,97,79,0.18)"} !important;
                  color: ${isDark ? "#d96252" : "#c0614f"} !important;
                }

                /* Card body prose — exact v8 .step-card p values:
                   Inter (no explicit family), 13px, line-height 1.58, var(--muted) */
                .careerforge-modal-body .cf-card-prose {
                  margin: 8px 0 0;
                  font-size: 13px;
                  line-height: 1.58;
                  color: ${surface.muted};
                }

                /* Tag pills — exact v8 .mini-chip values:
                   Inter, 11px, 700, 5px 9px pad, 999px radius, var(--panel-2) bg, var(--ink-2) color */
                .careerforge-modal-body .inline-flex.rounded-full,
                .careerforge-modal-body [class*="rounded-full"]:not(button):not([role="radio"]) {
                  background: ${isDark ? "rgba(255,255,255,0.08)" : "rgba(26,38,32,0.08)"} !important;
                  color: ${surface.ink2} !important;
                  border: none !important;
                  font-size: 11px !important;
                  font-weight: 700 !important;
                  letter-spacing: 0 !important;
                  text-transform: none !important;
                  padding: 5px 9px !important;
                  border-radius: 999px !important;
                }

                /* Agent trigger dropdown */
                .careerforge-modal-body .cf-agent-trigger {
                  height: 40px !important;
                  padding: 8px 14px !important;
                  border-radius: 12px !important;
                  font-size: 14px;
                  font-weight: 500;
                  color: ${surface.ink};
                }

                /* Card frame — left accent rail + per-card tinted background */
                .careerforge-modal-body [data-slot="card"] {
                  background: ${surface.cardBg} !important;
                  backdrop-filter: blur(10px);
                  -webkit-backdrop-filter: blur(10px);
                  border: 1px solid ${surface.cardBorder} !important;
                  border-left: 3px solid ${surface.accent} !important;
                  border-radius: 18px !important;
                  box-shadow: ${surface.cardShadow} !important;
                  position: relative;
                  overflow: hidden;
                  transition: transform .28s cubic-bezier(.2,.8,.2,1), box-shadow .28s cubic-bezier(.2,.8,.2,1);
                }
                /* Subtle top-glow strip (mirrors v8 .step-card::before) */
                .careerforge-modal-body [data-slot="card"]::before {
                  content: "";
                  position: absolute; left: 0; right: 0; top: 0;
                  height: 48px;
                  background: ${isDark
                    ? "linear-gradient(180deg, rgba(143,214,177,0.06) 0%, transparent 100%)"
                    : "linear-gradient(180deg, rgba(78,148,112,0.05) 0%, transparent 100%)"};
                  pointer-events: none; z-index: 0;
                }
                .careerforge-modal-body [data-slot="card"]:hover {
                  transform: translateY(-1px);
                  box-shadow: ${surface.cardShadowHover} !important;
                }
                /* Per-card tint: forest → gold → rose → forest → neutral */
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(1) {
                  background: ${isDark ? "rgba(30,40,34,0.88)" : "rgba(244,249,246,0.94)"} !important;
                }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(2) {
                  background: ${isDark ? "rgba(34,38,26,0.88)" : "rgba(252,249,242,0.94)"} !important;
                  border-left-color: ${surface.gold} !important;
                }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(3) {
                  background: ${isDark ? "rgba(36,28,28,0.88)" : "rgba(253,247,246,0.94)"} !important;
                  border-left-color: ${isDark ? "#d96252" : "#c0614f"} !important;
                }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(4) {
                  background: ${isDark ? "rgba(28,38,34,0.88)" : "rgba(244,249,246,0.90)"} !important;
                }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(5) {
                  background: ${isDark ? "rgba(30,34,40,0.88)" : "rgba(248,248,253,0.94)"} !important;
                  border-left-color: ${surface.gold} !important;
                }
                .careerforge-modal-body [data-slot="card-header"] {
                  padding: 20px 22px 10px !important;
                  position: relative; z-index: 1;
                }
                .careerforge-modal-body [data-slot="card-content"] {
                  padding: 0 22px 20px !important;
                  position: relative; z-index: 1;
                }

                /* Reveal animation — staggered like v8 .reveal */
                @keyframes cfReveal {
                  from { opacity: 0; filter: blur(6px); transform: translateY(14px) scale(.985); }
                  to   { opacity: 1; filter: blur(0); transform: translateY(0) scale(1); }
                }
                .careerforge-modal-body > div > [data-slot="card"] { animation: cfReveal .55s cubic-bezier(.2,.8,.2,1) both; }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(2) { animation-delay: .06s; }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(3) { animation-delay: .12s; }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(4) { animation-delay: .18s; }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(5) { animation-delay: .24s; }

                /* Activity timeline — v8 .step-card p for summary, v8 .eyebrow for timestamp */
                .careerforge-modal-body .cf-activity-summary {
                  font-size: 13px;
                  line-height: 1.58;
                  color: ${surface.ink};
                  margin: 0;
                }
                .careerforge-modal-body .cf-activity-time {
                  font-size: 10px;
                  font-weight: 700;
                  letter-spacing: 0.2em;
                  text-transform: uppercase;
                  color: ${surface.muted2 ?? surface.muted};
                  margin-top: 3px;
                }

                /* Body copy — ink color, no font override (inherits Inter) */
                .careerforge-modal-body p,
                .careerforge-modal-body span,
                .careerforge-modal-body div,
                .careerforge-modal-body li,
                .careerforge-modal-body label { color: ${surface.ink}; }
                .careerforge-modal-body .text-muted-foreground { color: ${surface.muted} !important; }

                /* Note / DM pre bodies — Inter prose, not mono */
                .careerforge-modal-body pre {
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  font-size: 13px;
                  line-height: 1.58;
                  color: ${surface.ink} !important;
                  white-space: pre-wrap;
                }

                /* Note/DM list rows */
                .careerforge-modal-body li.rounded-lg {
                  background: ${isDark ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.55)"} !important;
                  border-color: ${surface.line} !important;
                  border-radius: 14px !important;
                }
                .careerforge-modal-body li.border-primary\\/30 {
                  background: ${surface.accentSoft} !important;
                  border-color: ${surface.accent} !important;
                }

                /* Timestamps / counters only — mono tnum (the ONE place today screen uses it) */
                .careerforge-modal-body .tabular-nums {
                  font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
                  font-feature-settings: "tnum";
                }

                /* Inputs */
                .careerforge-modal-body textarea,
                .careerforge-modal-body input[type="text"],
                .careerforge-modal-body input[type="email"],
                .careerforge-modal-body input[type="search"] {
                  background: ${isDark ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.6)"} !important;
                  color: ${surface.ink} !important;
                  border-color: ${surface.line} !important;
                  border-radius: 12px !important;
                  font-size: 13px;
                  line-height: 1.58;
                  padding: 10px 14px !important;
                }
                .careerforge-modal-body textarea:focus,
                .careerforge-modal-body input:focus {
                  border-color: ${surface.accent} !important;
                  box-shadow: 0 0 0 3px ${surface.accentSoft} !important;
                  outline: none !important;
                }
                .careerforge-modal-body textarea::placeholder,
                .careerforge-modal-body input::placeholder { color: ${surface.muted} !important; }

                /* Primary buttons */
                .careerforge-modal-body button.bg-primary {
                  background: linear-gradient(135deg, ${surface.accent}, ${surface.eyebrow}) !important;
                  border: none !important;
                  color: ${isDark ? "#0e1411" : "#ffffff"} !important;
                  box-shadow: ${surface.ctaShadow} !important;
                  border-radius: 12px !important;
                  transition: transform .2s cubic-bezier(.2,.8,.2,1), box-shadow .2s cubic-bezier(.2,.8,.2,1);
                }
                .careerforge-modal-body button.bg-primary:hover:not(:disabled) {
                  transform: translateY(-1px);
                  box-shadow: 0 16px 40px ${isDark ? "rgba(143,214,177,0.30)" : "rgba(78,148,112,0.30)"} !important;
                }

                /* Ghost / outline buttons */
                .careerforge-modal-body a[href^="mailto:"],
                .careerforge-modal-body button.border,
                .careerforge-modal-body a.border {
                  background: ${isDark ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.5)"} !important;
                  border-color: ${surface.line} !important;
                  color: ${surface.ink} !important;
                  border-radius: 12px !important;
                }
                .careerforge-modal-body a[href^="mailto:"]:hover,
                .careerforge-modal-body button.border:hover {
                  background: ${isDark ? "rgba(255,255,255,0.07)" : "rgba(255,255,255,0.8)"} !important;
                  border-color: ${surface.accent} !important;
                }

                /* Select trigger */
                .careerforge-modal-body [data-slot="select-trigger"] {
                  background: ${isDark ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.7)"} !important;
                  border-color: ${surface.line} !important;
                  color: ${surface.ink} !important;
                  border-radius: 12px !important;
                }
                .careerforge-modal-body [data-slot="select-trigger"]:hover {
                  background: ${isDark ? "rgba(255,255,255,0.07)" : "rgba(255,255,255,0.9)"} !important;
                  border-color: ${surface.accent} !important;
                }
                .careerforge-modal-body [data-slot="select-value"] {
                  font-size: 14px;
                  font-weight: 500;
                  color: ${surface.ink};
                }

                .careerforge-modal-body textarea::placeholder,
                .careerforge-modal-body input::placeholder {
                  color: ${surface.muted2} !important;
                  font-style: italic;
                  letter-spacing: -0.005em;
                }

                /* Primary CTA labels — slightly tighter tracking + an
                   icon-text rhythm that matches v8 .btn.primary. */
                .careerforge-modal-body button.bg-primary,
                .careerforge-modal-body button[type="button"].bg-primary {
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  font-size: 14px;
                  font-weight: 600;
                  letter-spacing: -0.005em;
                  padding: 9px 18px !important;
                  height: auto !important;
                }
                /* Outline CTA labels (Schedule call, Add note when ghost,
                   Load older). */
                .careerforge-modal-body a[href^="mailto:"],
                .careerforge-modal-body button.border,
                .careerforge-modal-body a.border {
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  font-size: 14px;
                  font-weight: 500;
                  letter-spacing: -0.005em;
                  padding: 9px 14px !important;
                  height: auto !important;
                }

                /* === Activity timeline & DM rows ===
                   Lift each row into a v8 .lesson-row primitive: 14px
                   radius, panel-2 tint, soft hover, mono timestamp. */
                .careerforge-modal-body ol.space-y-2,
                .careerforge-modal-body ol.space-y-2\\.5 {
                  display: flex;
                  flex-direction: column;
                  gap: 8px;
                }
                /* Timeline rows — denser than before (10×14 padding,
                   8px gap to the icon) so each row reads as one tight
                   block instead of a half-empty card. */
                .careerforge-modal-body ol.space-y-2\\.5 > li {
                  background: ${
                    isDark
                      ? "rgba(255,255,255,0.025)"
                      : "rgba(255,255,255,0.55)"
                  };
                  border: 1px solid ${surface.line};
                  border-radius: 12px;
                  padding: 10px 14px;
                  gap: 12px !important;
                  align-items: center !important;
                  transition:
                    background .22s cubic-bezier(.2,.8,.2,1),
                    transform .22s cubic-bezier(.2,.8,.2,1),
                    border-color .22s cubic-bezier(.2,.8,.2,1);
                  backdrop-filter: blur(6px);
                }
                .careerforge-modal-body ol.space-y-2\\.5 > li:hover {
                  background: ${
                    isDark
                      ? "rgba(255,255,255,0.05)"
                      : "rgba(255,255,255,0.85)"
                  };
                  border-color: ${
                    isDark
                      ? "rgba(143,214,177,0.25)"
                      : "rgba(78,148,112,0.25)"
                  };
                }
                /* Timeline summary - Inter 14.5px weight 600 ink. The
                   path screen runs lesson-row strong at 14px Inter
                   for row-level primary text; serif at row scale
                   (especially in dark) reads chunky and competes with
                   the card title. Inter at this weight reads confident
                   and matches the rest of the cockpit row primitives. */
                .careerforge-modal-body .cf-activity-summary {
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  font-size: 14.5px;
                  font-weight: 600;
                  letter-spacing: -0.005em;
                  line-height: 1.35;
                  color: ${surface.ink};
                  margin: 0;
                }
                /* Timeline timestamp — mono 11px tnum, sits tight to
                   the summary so each row reads as one block, not two. */
                .careerforge-modal-body .cf-activity-time {
                  font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
                  font-size: 11px;
                  letter-spacing: 0.04em;
                  color: ${surface.muted2};
                  margin: 2px 0 0 !important;
                  font-feature-settings: "tnum";
                }
                /* Timeline icon — slightly smaller circle pad so the
                   row reads denser. */
                .careerforge-modal-body ol.space-y-2\\.5 > li > span:first-child {
                  display: inline-grid;
                  place-items: center;
                  width: 26px;
                  height: 26px;
                  border-radius: 50%;
                  background: ${
                    isDark
                      ? "rgba(143,214,177,0.10)"
                      : "rgba(78,148,112,0.08)"
                  };
                  border: 1px solid ${surface.line};
                  color: ${surface.eyebrow} !important;
                  flex-shrink: 0;
                  margin-top: 0 !important;
                }
                .careerforge-modal-body ol.space-y-2\\.5 > li > span:first-child svg {
                  width: 13px;
                  height: 13px;
                }

                /* DM row sender label (You / Student) — mono uppercase
                   already, just tighten size + color. */
                .careerforge-modal-body li.rounded-lg span.uppercase,
                .careerforge-modal-body li span.text-\\[10px\\].uppercase {
                  font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
                  font-size: 9.5px !important;
                  letter-spacing: 0.18em !important;
                  font-weight: 700 !important;
                  color: ${surface.eyebrow} !important;
                }
                /* DM row timestamp — mono 10px tnum. */
                .careerforge-modal-body li.rounded-lg span.text-\\[10px\\]:not(.uppercase) {
                  font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
                  font-size: 10px !important;
                  letter-spacing: 0.04em;
                  color: ${surface.muted2} !important;
                }
                /* DM body — Inter 14px ink, generous leading. */
                .careerforge-modal-body pre.font-sans {
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  font-size: 14px;
                  line-height: 1.55;
                  color: ${surface.ink} !important;
                  letter-spacing: -0.005em;
                }

                /* Saved-note row — pre + timestamp. */
                .careerforge-modal-body ol li pre:not(.font-sans) {
                  font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
                  font-size: 13px;
                  line-height: 1.6;
                  color: ${surface.ink} !important;
                }

                /* "No notes / messages / activity yet" empty-state
                   prose — Inter, italic, muted. */
                .careerforge-modal-body p.text-center {
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  font-size: 14px;
                  font-style: italic;
                  letter-spacing: -0.005em;
                  color: ${surface.muted} !important;
                  line-height: 1.55;
                }
              `}</style>
              {/* Dark-only globals for portal-rendered Select content
                  (the popup escapes the modal DOM, so we hang these
                  rules off html.dark which the open-effect adds). */}
              {/* Select content lives in a portal outside the modal,
                  so we hang these rules off body[data-cf-modal-theme]
                  which the open-effect sets. Both light + dark get
                  the cockpit pill aesthetic with frosted glass. */}
              <style>{`
                body[data-cf-modal-theme="${pageTheme}"] [data-slot="select-content"] {
                  background: ${
                    isDark ? "rgba(20, 28, 22, 0.95)" : "rgba(255, 255, 255, 0.96)"
                  } !important;
                  color: ${surface.ink} !important;
                  border: 1px solid ${surface.line} !important;
                  border-radius: 14px !important;
                  backdrop-filter: blur(12px);
                  -webkit-backdrop-filter: blur(12px);
                  box-shadow: ${
                    isDark
                      ? "0 24px 60px rgba(0, 0, 0, 0.55)"
                      : "0 24px 60px rgba(21, 19, 13, 0.14)"
                  } !important;
                  padding: 6px !important;
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                }
                body[data-cf-modal-theme="${pageTheme}"] [data-slot="select-item"] {
                  color: ${surface.ink};
                  border-radius: 10px !important;
                  font-size: 14px;
                  letter-spacing: -0.005em;
                  padding: 8px 10px !important;
                  transition: background .15s ease, color .15s ease;
                }
                body[data-cf-modal-theme="${pageTheme}"] [data-slot="select-item"][data-highlighted] {
                  background: ${surface.accentSoft} !important;
                  color: ${surface.ink} !important;
                }
                body[data-cf-modal-theme="${pageTheme}"] [data-slot="select-item"][data-selected] {
                  color: ${surface.eyebrow} !important;
                  font-weight: 500;
                }
              `}</style>
              <div className="careerforge-modal-body">
                <StudentDetailPanel
                  studentId={studentId}
                  hideHeader
                  compact
                />
                {studentId && (
                  <ResourceAuditPanel
                    resourceType="user"
                    resourceId={studentId}
                    pageTheme={pageTheme}
                    title="Admin actions on this student"
                  />
                )}
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
