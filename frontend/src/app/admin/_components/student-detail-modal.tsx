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
    if (!open) return;
    const html = document.documentElement;
    const body = document.body;
    const had = html.classList.contains("dark");
    if (isDark) html.classList.add("dark");
    // Mark body so portal-rendered popups (Select content lives outside
    // the modal DOM) can pick up the cockpit chrome regardless of theme.
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
  const surface = isDark
    ? {
        // Page bg — radial gradient like v8 dark hero, not flat.
        bgGradient:
          "radial-gradient(circle at top left, #1a2520, #0e1411 42%)",
        bg: "#0e1411",
        // Glass card: panel hex with subtle alpha + blur. Border picks
        // up forest-tinted line color so it doesn't fight the card.
        cardBg: "rgba(26, 34, 28, 0.82)",
        cardBorder: "rgba(143, 214, 177, 0.12)",
        cardShadow:
          "0 18px 60px rgba(0, 0, 0, 0.40), 0 1px 0 rgba(143, 214, 177, 0.04) inset",
        cardShadowHover:
          "0 28px 90px rgba(0, 0, 0, 0.55), 0 1px 0 rgba(143, 214, 177, 0.06) inset",
        ink: "#f0ece1", // --ink
        ink2: "#d6d2c6", // --ink-2
        muted: "#9a9588", // --muted
        muted2: "#7a7568", // --muted-2
        eyebrow: "#8fd6b1", // --forest-3
        eyebrowDot: "#73c79c", // --forest-2
        accent: "#73c79c",
        accentSoft: "rgba(143, 214, 177, 0.14)",
        gold: "#e8be72",
        line: "#2c3830",
        borderTop: "rgba(255, 255, 255, 0.04)",
        ring: "rgba(208, 212, 207, 0.04)",
        backdrop: "rgba(0, 0, 0, 0.62)",
        ctaShadow: "0 12px 32px rgba(143, 214, 177, 0.20)",
        goldShadow: "0 16px 40px rgba(232, 190, 114, 0.28)",
      }
    : {
        // Page bg — same warm radial gradient v8 light uses.
        bgGradient:
          "radial-gradient(circle at top left, #fbf7f0, #f6f1e8 42%)",
        bg: "#f6f1e8",
        cardBg: "rgba(255, 255, 255, 0.82)",
        cardBorder: "rgba(219, 209, 191, 0.92)",
        cardShadow: "0 10px 30px rgba(21, 19, 13, 0.05)",
        cardShadowHover: "0 18px 60px rgba(21, 19, 13, 0.09)",
        ink: "#10120e", // --ink
        ink2: "#232720", // --ink-2
        muted: "#686559", // --muted
        muted2: "#8f897d", // --muted-2
        eyebrow: "#356d50", // --forest-2
        eyebrowDot: "#4e9470", // --forest-3
        accent: "#244f39",
        accentSoft: "#e5efe8",
        gold: "#b8862d",
        line: "#dbd1bf",
        borderTop: "rgba(255, 255, 255, 0.7)",
        ring: "rgba(26, 38, 32, 0.04)",
        backdrop: "rgba(8, 12, 10, 0.32)",
        ctaShadow: "0 12px 32px rgba(78, 148, 112, 0.22)",
        goldShadow: "0 16px 40px rgba(214, 165, 77, 0.25)",
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
            // Warm radial gradient — same primitive v8.css uses on
            // .hero / .path-hero. The blur/glass cards inside this
            // popup read this gradient through their .82 alpha, which
            // is what makes them feel "alive."
            background: surface.bgGradient,
            color: surface.ink,
            borderRadius: 22,
            maxHeight: "calc(100vh - 4rem)",
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
                  fontFamily:
                    "var(--font-jetbrains-mono), ui-monospace, monospace",
                  ["--cf-eyebrow-dot" as string]: surface.eyebrowDot,
                  ["--cf-eyebrow-halo" as string]: isDark
                    ? "rgba(143, 214, 177, 0.18)"
                    : "rgba(78, 148, 112, 0.18)",
                }}
              >
                Student profile
              </div>
              {/* Title — Fraunces 32px with -0.03em tracking, matching
                  v8 hero/section-title typography. Tighter tracking is
                  the difference between "default serif" and "premium
                  editorial." */}
              <DialogPrimitive.Title
                className="truncate font-medium leading-[1.05]"
                style={{
                  color: surface.ink,
                  fontFamily: "var(--font-fraunces), Georgia, serif",
                  fontSize: "32px",
                  letterSpacing: "-0.03em",
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
                [data-theme="${pageTheme}"] .cf-modal-eyebrow {
                  display: inline-flex;
                  align-items: center;
                  gap: 8px;
                  font-size: 10px;
                  letter-spacing: 0.2em;
                  text-transform: uppercase;
                  font-weight: 700;
                  margin-bottom: 12px;
                  color: var(--cf-eyebrow-color, ${surface.eyebrow});
                }
                [data-theme="${pageTheme}"] .cf-modal-eyebrow::before {
                  content: "";
                  width: 6px;
                  height: 6px;
                  border-radius: 50%;
                  background: var(--cf-eyebrow-dot, ${surface.eyebrowDot});
                  box-shadow: 0 0 0 4px var(--cf-eyebrow-halo, ${
                    isDark ? "rgba(143,214,177,0.18)" : "rgba(78,148,112,0.18)"
                  });
                }
              `}</style>
              <style>{`
                /* === Shared chrome — v8 primitives === */
                .careerforge-modal-body {
                  --admin-eyebrow: ${surface.eyebrow};
                  --admin-eyebrow-dot: ${surface.eyebrowDot};
                  --admin-eyebrow-halo: ${
                    isDark ? "rgba(143,214,177,0.18)" : "rgba(78,148,112,0.18)"
                  };
                  --admin-ink: ${surface.ink};
                  --admin-ink-2: ${surface.ink2};
                  --admin-muted: ${surface.muted};
                }

                /* Eyebrow above each card — the v8 .card-face-eyebrow
                   primitive: 10px, 0.2em tracking, weight 700, mint
                   dot ::before with halo glow. */
                .careerforge-modal-body .cf-card-eyebrow {
                  display: inline-flex;
                  align-items: center;
                  gap: 8px;
                  font-size: 10px;
                  letter-spacing: 0.2em;
                  text-transform: uppercase;
                  font-weight: 700;
                  color: ${surface.eyebrow};
                  margin-bottom: 10px;
                }
                .careerforge-modal-body .cf-card-eyebrow::before {
                  content: "";
                  width: 6px;
                  height: 6px;
                  border-radius: 50%;
                  background: ${surface.eyebrowDot};
                  box-shadow: 0 0 0 4px ${
                    isDark ? "rgba(143,214,177,0.18)" : "rgba(78,148,112,0.18)"
                  };
                }

                /* Card title — Fraunces 22px, weight 500, -0.03em. The
                   /path screen uses 22-24px serifs at this tracking
                   for every card and section title. */
                .careerforge-modal-body .cf-card-title {
                  margin: 0;
                  font-size: 22px;
                  font-weight: 500;
                  letter-spacing: -0.03em;
                  line-height: 1.15;
                  color: ${surface.ink};
                }
                /* Card title icon — sits in a soft 32px circle pad with
                   a tinted bg, like the v8 .lesson-icon primitive.
                   Reads as an "instrument" rather than a stray glyph. */
                .careerforge-modal-body .cf-card-title-icon {
                  display: inline-grid;
                  place-items: center;
                  width: 32px;
                  height: 32px;
                  border-radius: 10px;
                  background: ${
                    isDark ? "rgba(143,214,177,0.10)" : "rgba(78,148,112,0.08)"
                  };
                  border: 1px solid ${surface.line};
                  flex-shrink: 0;
                }
                .careerforge-modal-body .cf-card-title-icon svg {
                  width: 16px;
                  height: 16px;
                }

                /* Card body prose — sits tight under the title, muted.
                   Sized small enough that it reads as helper, not as a
                   competing line of body copy. */
                .careerforge-modal-body .cf-card-prose {
                  margin: 6px 0 0;
                  color: ${surface.muted};
                  font-size: 13.5px;
                  line-height: 1.55;
                }

                /* Agent trigger — single-font Inter pill. */
                .careerforge-modal-body .cf-agent-trigger {
                  height: 40px !important;
                  padding: 8px 14px !important;
                  border-radius: 12px !important;
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  font-size: 14px;
                  font-weight: 500;
                  letter-spacing: -0.005em;
                  color: ${surface.ink};
                }

                /* Card frame — frosted glass, 22px radius, warm shadow.
                   Mirrors v8.css .card line 744-753 exactly. */
                .careerforge-modal-body [data-slot="card"] {
                  background: ${surface.cardBg} !important;
                  backdrop-filter: blur(10px);
                  -webkit-backdrop-filter: blur(10px);
                  border: 1px solid ${surface.cardBorder} !important;
                  border-radius: 22px !important;
                  box-shadow: ${surface.cardShadow} !important;
                  transition:
                    transform .28s cubic-bezier(.2,.8,.2,1),
                    box-shadow .28s cubic-bezier(.2,.8,.2,1),
                    border-color .28s cubic-bezier(.2,.8,.2,1);
                  position: relative;
                  overflow: hidden;
                }
                .careerforge-modal-body [data-slot="card"]:hover {
                  box-shadow: ${surface.cardShadowHover} !important;
                }
                /* Card header: 18px top so the eyebrow has breathing
                   room, 10px bottom so the prose helper sits tight to
                   the action row below it (was 14px → felt stretched). */
                .careerforge-modal-body [data-slot="card-header"] {
                  padding: 18px 22px 10px !important;
                }
                .careerforge-modal-body [data-slot="card-content"] {
                  padding: 0 22px 18px !important;
                }

                /* Reveal animation — borrowed from v8.css .reveal. Each
                   card focuses into existence with a soft blur + lift,
                   staggered so the eye reads them sequentially. */
                @keyframes cfReveal {
                  from { opacity: 0; filter: blur(6px); transform: translateY(14px) scale(.985); }
                  to   { opacity: 1; filter: blur(0); transform: translateY(0) scale(1); }
                }
                .careerforge-modal-body > div > [data-slot="card"] {
                  animation: cfReveal .55s cubic-bezier(.2,.8,.2,1) both;
                }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(2) { animation-delay: .06s; }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(3) { animation-delay: .12s; }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(4) { animation-delay: .18s; }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(5) { animation-delay: .24s; }
                .careerforge-modal-body > div > [data-slot="card"]:nth-child(6) { animation-delay: .30s; }

                /* Numerics + identifiers in the panel — JetBrains Mono
                   with tnum. Matches the v8 .cp-label primitive. */
                .careerforge-modal-body .tabular-nums,
                .careerforge-modal-body .font-mono,
                .careerforge-modal-body time,
                .careerforge-modal-body [data-slot="card-content"] p.text-\\[10px\\],
                .careerforge-modal-body [data-slot="card-content"] p.text-xs.text-muted-foreground {
                  font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
                  font-feature-settings: "tnum";
                  letter-spacing: 0.01em;
                }

                /* Body copy & muted text in cockpit ink (cream in dark,
                   ink in light) instead of shadcn defaults. */
                .careerforge-modal-body p,
                .careerforge-modal-body span,
                .careerforge-modal-body div,
                .careerforge-modal-body li,
                .careerforge-modal-body label {
                  color: ${surface.ink};
                }
                .careerforge-modal-body .text-muted-foreground {
                  color: ${surface.muted} !important;
                }

                /* Inputs — translucent over the warm gradient, focus
                   ring matches the cockpit accent. */
                .careerforge-modal-body textarea,
                .careerforge-modal-body input[type="text"],
                .careerforge-modal-body input[type="email"],
                .careerforge-modal-body input[type="search"] {
                  background: ${
                    isDark ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.6)"
                  } !important;
                  color: ${surface.ink} !important;
                  border-color: ${surface.line} !important;
                  border-radius: 12px !important;
                }
                .careerforge-modal-body textarea:focus,
                .careerforge-modal-body input:focus {
                  border-color: ${surface.accent} !important;
                  box-shadow: 0 0 0 3px ${surface.accentSoft} !important;
                  outline: none !important;
                }
                .careerforge-modal-body textarea::placeholder,
                .careerforge-modal-body input::placeholder {
                  color: ${surface.muted} !important;
                }

                /* Primary action buttons — gradient + colored shadow,
                   the same "jewelry" treatment v8.css uses on
                   .star.goal and .btn.gold. */
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
                  box-shadow: 0 16px 40px ${
                    isDark ? "rgba(143,214,177,0.30)" : "rgba(78,148,112,0.30)"
                  } !important;
                }

                /* Ghost / outline buttons (Schedule call, Load older). */
                .careerforge-modal-body a[href^="mailto:"],
                .careerforge-modal-body button.border,
                .careerforge-modal-body a.border {
                  background: ${
                    isDark ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.5)"
                  } !important;
                  border-color: ${surface.line} !important;
                  color: ${surface.ink} !important;
                  border-radius: 12px !important;
                  backdrop-filter: blur(6px);
                }
                .careerforge-modal-body a[href^="mailto:"]:hover,
                .careerforge-modal-body button.border:hover {
                  background: ${
                    isDark ? "rgba(255,255,255,0.07)" : "rgba(255,255,255,0.8)"
                  } !important;
                  border-color: ${surface.accent} !important;
                }

                /* Saved-message bodies + saved-note rows. */
                .careerforge-modal-body pre {
                  color: ${surface.ink} !important;
                  font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
                  font-size: 13px;
                  line-height: 1.6;
                }
                .careerforge-modal-body li.rounded-lg {
                  background: ${
                    isDark ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.55)"
                  } !important;
                  border-color: ${surface.line} !important;
                  border-radius: 14px !important;
                  backdrop-filter: blur(6px);
                }
                .careerforge-modal-body li.border-primary\\/30 {
                  background: ${surface.accentSoft} !important;
                  border-color: ${surface.accent} !important;
                }

                /* Select trigger + portal popup — match the cockpit
                   pill aesthetic instead of the default shadcn input. */
                .careerforge-modal-body [data-slot="select-trigger"] {
                  background: ${
                    isDark ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.7)"
                  } !important;
                  border-color: ${surface.line} !important;
                  color: ${surface.ink} !important;
                  border-radius: 12px !important;
                  backdrop-filter: blur(6px);
                }
                .careerforge-modal-body [data-slot="select-trigger"]:hover {
                  background: ${
                    isDark ? "rgba(255,255,255,0.07)" : "rgba(255,255,255,0.9)"
                  } !important;
                  border-color: ${surface.accent} !important;
                }

                /* Select trigger value — the resolved label like "Re-engage
                   (disrupt_prevention)". Same prose font as body, but a
                   touch tighter so it reads as a controlled selection. */
                .careerforge-modal-body [data-slot="select-value"] {
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  font-size: 14px;
                  letter-spacing: -0.005em;
                  font-weight: 500;
                  color: ${surface.ink};
                }

                /* Textareas + their placeholder ghost text — Inter 14px
                   with generous leading. Was 13px and felt cramped vs.
                   the new 22px Fraunces card titles. */
                .careerforge-modal-body textarea,
                .careerforge-modal-body input[type="text"],
                .careerforge-modal-body input[type="email"],
                .careerforge-modal-body input[type="search"] {
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  font-size: 14px;
                  line-height: 1.6;
                  letter-spacing: -0.005em;
                  padding: 12px 14px !important;
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
