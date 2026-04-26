"use client";

/**
 * P-Tutor1 (2026-04-26) — TutorScreen.
 *
 * Editorial v8 shell for /chat. Wraps the existing <ChatArea> data engine
 * (streaming, modals, edits — all unchanged) inside the v8 visual language.
 *
 * P-Tutor2 (2026-04-26 follow-up) — UI trimmed per product feedback:
 *   - Removed the always-visible "Pick a tutor mode" card (modes still live
 *     inside the composer footer).
 *   - Removed the "Your tutor flow" 3-step row.
 *   - Removed the empty-state opener cards + headline.
 *   - Removed the "Ready to graduate" + "Cohort, live" rail cards.
 *   - Added a small (?) Help button in the conversation card eyebrow.
 *     Clicking it opens a modal that hosts the OLD onboarding content
 *     (mode picker explanation + 3-step tutor flow). First-time visitors
 *     get the modal auto-opened once; localStorage flag suppresses it
 *     thereafter. The data engine + props are byte-identical.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { useDueCards } from "@/lib/hooks/use-srs";
import type { ConversationListItem } from "@/lib/chat-api";
import { cn } from "@/lib/utils";

interface ModeOption {
  /** Backend agent name; null = Auto routing. */
  agentName: string | null;
  label: string;
  description: string;
}

const MODE_OPTIONS: ReadonlyArray<ModeOption> = [
  { agentName: null, label: "Auto", description: "Pick the right agent for me" },
  { agentName: "socratic_tutor", label: "Tutor", description: "Guided socratic questions" },
  { agentName: "coding_assistant", label: "Code Review", description: "PR-style inline feedback" },
  { agentName: "career_coach", label: "Career", description: "Interview + role coaching" },
  { agentName: "adaptive_quiz", label: "Quiz Me", description: "Test what you nearly forgot" },
];

/** localStorage key for the first-time help auto-open. */
const HELP_SEEN_KEY = "tutor-help-seen-v1";

/** localStorage key for the rail-collapsed preference (P-Tutor4). */
const RAIL_COLLAPSED_KEY = "tutor-rail-collapsed-v1";

function relativeTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const min = Math.round(ms / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}d ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

export interface TutorScreenProps {
  /** Render slot — callers pass <ChatArea ... /> here. */
  children: React.ReactNode;
  /** Recent conversations list, server-truth from /api/v1/chat/conversations. */
  conversations: ReadonlyArray<ConversationListItem>;
  conversationsLoading: boolean;
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  mode: ModeOption["agentName"];
  // P-Tutor2: mode-change handler is no longer wired in the body of this
  // screen (the modes live inside ChatArea's composer). Kept on the prop
  // contract so the parent page doesn't need a churn — the help modal
  // doesn't switch modes; it only explains them.
  onModeChange: (next: ModeOption["agentName"]) => void;
  /** True when the current chat has no messages — show editorial empty state. */
  isEmpty: boolean;
  /** Called when a student clicks an opener card. Caller fills the composer.
   * P-Tutor2: opener cards are gone, but the prop remains so the page
   * compiles unchanged. We may surface 1–2 opener pills in a follow-up. */
  onOpenerPrompt: (prompt: string) => void;
}

export function TutorScreen({
  children,
  conversations,
  conversationsLoading,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
  mode,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- see prop comment
  onModeChange: _onModeChange,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- see prop comment
  isEmpty: _isEmpty,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- see prop comment
  onOpenerPrompt: _onOpenerPrompt,
}: TutorScreenProps) {
  const { data: dueCards } = useDueCards(50);
  const dueCount = dueCards?.length ?? 0;

  const turnsThisWeek = useMemo(
    () =>
      conversations.reduce((acc, c) => acc + (c.message_count ?? 0), 0),
    [conversations],
  );

  const activeMode = MODE_OPTIONS.find((m) => m.agentName === mode) ?? MODE_OPTIONS[0];

  // First-time-visitor auto-open of the help modal. Suppressed thereafter
  // via localStorage. The (?) button always works to re-open it.
  // Lazy initial state — read localStorage once on mount; lets us avoid the
  // "setState in effect" lint rule. SSR returns false (window is undefined).
  const [helpOpen, setHelpOpen] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.localStorage.getItem(HELP_SEEN_KEY) === null;
    } catch {
      return false;
    }
  });
  const closeHelp = useCallback(() => {
    setHelpOpen(false);
    try {
      window.localStorage.setItem(HELP_SEEN_KEY, "1");
    } catch {
      /* ignore */
    }
  }, []);
  const openHelp = useCallback(() => setHelpOpen(true), []);

  // P-Tutor4 (2026-04-26) — collapsible rail. Persisted in localStorage so
  // the user's choice survives reloads. Defaults to expanded.
  const [railCollapsed, setRailCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.localStorage.getItem(RAIL_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const toggleRail = useCallback(() => {
    setRailCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(RAIL_COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  useSetV8Topbar({
    eyebrow: "AI Tutor",
    titleHtml: "Think out loud with a tutor that <i>remembers</i> what you nearly forgot.",
    chips: [
      { label: `${dueCount} card${dueCount === 1 ? "" : "s"} due`, variant: "gold" },
      { label: `${turnsThisWeek} turns this week`, variant: "ink" },
      { label: `Mode · ${activeMode.label}`, variant: "forest" },
    ],
    progress: Math.min(100, Math.round((turnsThisWeek / 50) * 100)),
  });

  return (
    <section className="screen active" id="screen-tutor">
      <div className="pad">
        <div
          className={cn("grid tutor-grid", railCollapsed && "rail-collapsed")}
          style={{ position: "relative" }}
        >
          {/* P-Tutor4 — floating reopen pill, only when rail is collapsed.
              Anchored to the top-right of the grid so it sits where the rail
              header used to be. */}
          {railCollapsed ? (
            <button
              type="button"
              className="tutor-rail-reopen"
              onClick={toggleRail}
              aria-label="Show recent conversations"
              title="Show recent conversations"
            >
              <span aria-hidden="true">‹</span>
              <span>Recent</span>
            </button>
          ) : null}

          {/* ─── Left column: dark conversation card only ─── */}
          <div className="grid">
            <section className="tutor-conv-card reveal">
              <div className="tutor-conv-eyebrow">
                <span className="tutor-conv-eyebrow-left">
                  Tutor session · {activeMode.label} mode
                </span>
                <span
                  className="tutor-conv-eyebrow-right"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                  }}
                >
                  <span>
                    {activeConversationId
                      ? "Resumed conversation"
                      : "Fresh thread"}
                  </span>
                  <button
                    type="button"
                    onClick={openHelp}
                    aria-label="How the tutor works"
                    title="How the tutor works"
                    style={{
                      width: 22,
                      height: 22,
                      borderRadius: 11,
                      border: "1px solid rgba(255,255,255,0.25)",
                      background: "transparent",
                      color: "rgba(255,255,255,0.85)",
                      fontSize: 12,
                      fontWeight: 600,
                      lineHeight: 1,
                      cursor: "pointer",
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      padding: 0,
                    }}
                  >
                    ?
                  </button>
                </span>
              </div>

              <div className="tutor-conv-body">
                {/* The actual <ChatArea> — passed in by the page. The composer
                    lives inside <ChatArea> and already shows the mode chips,
                    so a separate "Pick a tutor mode" card above is redundant. */}
                <div className="tutor-conv-inner">{children}</div>
              </div>
            </section>
          </div>

          {/* ─── Right rail: Recent conversations only ─── */}
          <aside className="rail">
            <section className="rail-card reveal">
              <div
                className="section-title"
                style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}
              >
                <div>
                  <h4 style={{ fontSize: 16 }}>Recent conversations</h4>
                </div>
                <button
                  type="button"
                  className="btn ghost"
                  onClick={onNewConversation}
                  aria-label="Start a new conversation"
                  style={{ padding: "4px 10px", fontSize: 11 }}
                >
                  + New
                </button>
                {/* P-Tutor4 — collapse the rail to widen the chat surface. */}
                <button
                  type="button"
                  className="tutor-rail-collapse"
                  onClick={toggleRail}
                  aria-label="Hide recent conversations"
                  title="Hide recent conversations"
                >
                  <span aria-hidden="true">›</span>
                </button>
              </div>
              {conversationsLoading ? (
                <p className="tutor-recent-empty">Loading…</p>
              ) : conversations.length === 0 ? (
                <p className="tutor-recent-empty">
                  No conversations yet. Start one — your future self will
                  thank you.
                </p>
              ) : (
                <div className="tutor-recent-list">
                  {conversations.slice(0, 8).map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => onSelectConversation(c.id)}
                      className={cn(
                        "tutor-recent-item",
                        c.id === activeConversationId && "active",
                      )}
                      aria-current={c.id === activeConversationId}
                    >
                      <span className="tutor-recent-title">
                        {c.title || "Untitled conversation"}
                      </span>
                      <span className="tutor-recent-meta">
                        {relativeTime(c.updated_at)}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </section>
          </aside>
        </div>
      </div>

      {helpOpen ? (
        <TutorHelpModal onClose={closeHelp} activeMode={activeMode.label} />
      ) : null}
    </section>
  );
}

// ───────────────────────────────────────────────────────────────────────
// Help modal — onboarding for first-time users + on-demand reference for
// everyone else. Hosts the "Pick a tutor mode" + "Your tutor flow" content
// the previous layout dedicated full-page real estate to.
// ───────────────────────────────────────────────────────────────────────

interface TutorHelpModalProps {
  onClose: () => void;
  activeMode: string;
}

function TutorHelpModal({ onClose, activeMode }: TutorHelpModalProps) {
  // ESC closes the modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="tutor-help-title"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(16, 18, 14, 0.55)",
        backdropFilter: "blur(4px)",
        zIndex: 80,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card pad"
        style={{
          maxWidth: 760,
          width: "100%",
          maxHeight: "calc(100vh - 48px)",
          overflow: "auto",
          background: "var(--cream-1, #f7f3ea)",
          boxShadow: "0 30px 80px rgba(0,0,0,0.35)",
          borderRadius: 18,
          position: "relative",
        }}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close help"
          style={{
            position: "absolute",
            top: 14,
            right: 14,
            width: 30,
            height: 30,
            borderRadius: 15,
            border: "1px solid var(--ink-3, #d8d2c2)",
            background: "transparent",
            cursor: "pointer",
            fontSize: 16,
            lineHeight: 1,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          ×
        </button>

        <div className="eyebrow">How the tutor works</div>
        <h3 id="tutor-help-title" style={{ marginTop: 6, marginBottom: 8 }}>
          Two minutes that make every conversation sharper.
        </h3>
        <p style={{ marginBottom: 18 }}>
          The tutor learns from what you struggle with. These two surfaces
          shape what you get back — pick a mode, then move through the
          three-step loop on every meaningful turn.
        </p>

        {/* Mode picker explanation — same content as the old card, now
            informational only. The mode chips inside the composer are still
            the actual switcher. */}
        <div style={{ marginBottom: 22 }}>
          <h4 style={{ fontSize: 16, marginBottom: 6 }}>1 · Pick a tutor mode</h4>
          <p className="small" style={{ marginBottom: 10 }}>
            Auto picks for you — or pin a specialist if you know what you
            want from this turn. Switch any time using the chips inside the
            composer below the conversation. You&apos;re currently in{" "}
            <b>{activeMode}</b> mode.
          </p>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              gap: 10,
            }}
          >
            {MODE_OPTIONS.map((m) => (
              <div
                key={m.label}
                style={{
                  border: "1px solid var(--ink-3, #d8d2c2)",
                  borderRadius: 10,
                  padding: "10px 12px",
                  background: "white",
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: 2 }}>
                  {m.label}
                </div>
                <div className="small" style={{ color: "var(--ink-2, #6b6759)" }}>
                  {m.description}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* The 3-step tutor flow — same numbered cards, now reference. */}
        <div>
          <h4 style={{ fontSize: 16, marginBottom: 6 }}>2 · Your tutor flow</h4>
          <p className="small" style={{ marginBottom: 10 }}>
            Each turn should leave a trace — a card you can review or a note
            you can graduate. Reflection is part of learning, not a separate
            chore.
          </p>
          <ol style={{ paddingLeft: 0, margin: 0, listStyle: "none" }}>
            <li
              style={{
                border: "1px solid var(--ink-3, #d8d2c2)",
                borderRadius: 10,
                padding: "12px 14px",
                background: "white",
                marginBottom: 8,
              }}
            >
              <div className="small" style={{ color: "var(--gold-2, #b8862d)" }}>
                Step 1 · Active now
              </div>
              <div style={{ fontWeight: 600, marginTop: 2 }}>
                Ask the question you&apos;ve been avoiding
              </div>
              <div className="small" style={{ marginTop: 4 }}>
                Specific beats vague. Bring a concrete example — code, a
                confusion, a draft you don&apos;t trust yet.
              </div>
            </li>
            <li
              style={{
                border: "1px solid var(--ink-3, #d8d2c2)",
                borderRadius: 10,
                padding: "12px 14px",
                background: "white",
                marginBottom: 8,
              }}
            >
              <div className="small" style={{ color: "var(--ink-2, #6b6759)" }}>
                Step 2 · Unlocks next
              </div>
              <div style={{ fontWeight: 600, marginTop: 2 }}>
                Make 1–2 flashcards in your own words
              </div>
              <div className="small" style={{ marginTop: 4 }}>
                Generation effect — writing the card is what makes it stick.
                Click &ldquo;Flashcards&rdquo; on a reply to author them.
              </div>
            </li>
            <li
              style={{
                border: "1px solid var(--ink-3, #d8d2c2)",
                borderRadius: 10,
                padding: "12px 14px",
                background: "white",
              }}
            >
              <div className="small" style={{ color: "var(--ink-2, #6b6759)" }}>
                Step 3 · Closes the loop
              </div>
              <div style={{ fontWeight: 600, marginTop: 2 }}>
                Bookmark the answer to your notebook
              </div>
              <div className="small" style={{ marginTop: 4 }}>
                Notes graduate after 2 successful recalls. Your future self
                gets a clean, recall-tested summary.
              </div>
            </li>
          </ol>
        </div>

        <div
          className="rd-footer"
          style={{ justifyContent: "flex-end", marginTop: 18 }}
        >
          <button type="button" className="btn primary" onClick={onClose}>
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}
