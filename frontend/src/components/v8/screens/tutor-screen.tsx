"use client";

/**
 * P-Tutor1 (2026-04-26) — TutorScreen.
 *
 * Editorial v8 shell for /chat. Wraps the existing <ChatArea> data engine
 * (streaming, modals, edits — all unchanged) inside the same visual
 * language used by Today / Studio / Promotion / Job Readiness:
 *
 *   - editorial topbar (eyebrow + italic-accent title + chips + progress)
 *   - 2-column layout: dark conversation card on the left, right rail
 *     with Recent conversations + Cohort live + Ready to graduate
 *   - mode picker as track-cards row (not floating ghost buttons)
 *   - empty state = 3 opener cards inside the dark card
 *   - session-flow numbered row underneath, like Today's "Your session flow"
 *
 * The inner <ChatArea> is passed in as a children prop — this component
 * never reaches into chat state, which keeps the data engine byte-identical
 * and de-risks the visual rebuild.
 */

import { useMemo } from "react";
import Link from "next/link";

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

interface OpenerCard {
  num: string;
  title: string;
  hint: string;
  prompt: string;
}

const OPENER_CARDS: ReadonlyArray<OpenerCard> = [
  {
    num: "01",
    title: "Explain something you almost understood",
    hint: "Best way to find the gap",
    prompt: "Walk me through how RAG works end-to-end — and stop me where I'm hand-waving.",
  },
  {
    num: "02",
    title: "Get a code review on your last attempt",
    hint: "PR-style, line by line",
    prompt: "Here's the async client I shipped today — review it like a senior reviewing a PR.",
  },
  {
    num: "03",
    title: "Practice a tough interview question",
    hint: "FAANG-level, with a hint budget",
    prompt: "Quiz me on async/await and rate limits like an interviewer at a FAANG AI team.",
  },
];

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
  onModeChange: (next: ModeOption["agentName"]) => void;
  /** True when the current chat has no messages — show editorial empty state. */
  isEmpty: boolean;
  /** Called when a student clicks an opener card. Caller fills the composer. */
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
  onModeChange,
  isEmpty,
  onOpenerPrompt,
}: TutorScreenProps) {
  const { data: dueCards } = useDueCards(50);
  const dueCount = dueCards?.length ?? 0;

  const turnsThisWeek = useMemo(
    () =>
      conversations.reduce((acc, c) => acc + (c.message_count ?? 0), 0),
    [conversations],
  );

  const activeMode = MODE_OPTIONS.find((m) => m.agentName === mode) ?? MODE_OPTIONS[0];

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
        <div className="grid today-grid">
          {/* ─── Left column: mode picker + dark conversation card + session-flow ─── */}
          <div className="grid">
            {/* Mode picker — editorial track cards */}
            <section className="card pad reveal">
              <div className="section-title">
                <div>
                  <h4>Pick a tutor mode</h4>
                  <p>
                    Auto picks for you — or pin a specialist if you know what
                    you want from this turn.
                  </p>
                </div>
                <div className="small">
                  Switching mid-conversation is fine.
                </div>
              </div>
              <div className="tutor-mode-track">
                {MODE_OPTIONS.map((m) => (
                  <button
                    key={m.label}
                    type="button"
                    onClick={() => onModeChange(m.agentName)}
                    className={cn(
                      "tutor-mode-card",
                      m.agentName === mode && "active",
                    )}
                    aria-pressed={m.agentName === mode}
                  >
                    <span className="tutor-mode-card-title">{m.label}</span>
                    <span className="tutor-mode-card-desc">{m.description}</span>
                  </button>
                ))}
              </div>
            </section>

            {/* The dark conversation card — earned thinking space */}
            <section className="tutor-conv-card reveal">
              <div className="tutor-conv-eyebrow">
                <span className="tutor-conv-eyebrow-left">
                  Tutor session · {activeMode.label} mode
                </span>
                <span className="tutor-conv-eyebrow-right">
                  {activeConversationId
                    ? "Resumed conversation"
                    : "Fresh thread"}
                </span>
              </div>

              {isEmpty && (
                <>
                  <div className="tutor-empty-hero">
                    <div className="eyebrow">Start with what&apos;s bothering you</div>
                    <h4>
                      Pick the question you&apos;ve been <i>avoiding</i>.
                    </h4>
                    <p>
                      The tutor learns from what you struggle with. Vague
                      prompts give you vague answers — start specific, even if
                      it feels small.
                    </p>
                  </div>
                  <div className="tutor-opener-row">
                    {OPENER_CARDS.map((c) => (
                      <button
                        key={c.num}
                        type="button"
                        onClick={() => onOpenerPrompt(c.prompt)}
                        className="tutor-opener-card"
                        aria-label={`Use opener: ${c.title}`}
                      >
                        <div className="tutor-opener-num">{c.num}</div>
                        <div className="tutor-opener-title">{c.title}</div>
                        <div className="tutor-opener-hint">{c.hint}</div>
                      </button>
                    ))}
                  </div>
                </>
              )}

              <div className="tutor-conv-body">
                {/* The actual <ChatArea> — passed in by the page. Wrapped in
                    a lighter inner shell so its existing bubble + composer
                    styles read cleanly on top of the dark card. */}
                <div className="tutor-conv-inner">{children}</div>
              </div>
            </section>

            {/* Session flow — three numbered cards, mirrors Today's pattern.
                Frames the chat as part of the learning loop, not a separate
                utility. */}
            <section className="card pad reveal">
              <div className="section-title">
                <div>
                  <h4>Your tutor flow</h4>
                  <p>
                    Each turn should leave a trace — a card you can review or
                    a note you can graduate.
                  </p>
                </div>
                <div className="small">
                  Reflection is part of learning, not a separate chore.
                </div>
              </div>
              <div className="step-row">
                <article className="step-card active">
                  <div className="step-top">
                    <div className="step-num">1</div>
                    <div className="step-state">Active now</div>
                  </div>
                  <h5>Ask the question you&apos;ve been avoiding</h5>
                  <p>
                    Specific beats vague. Bring a concrete example — code,
                    a confusion, a draft you don&apos;t trust yet.
                  </p>
                  <div className="step-meta">
                    <span className="mini-chip">{activeMode.label} mode</span>
                    <span className="mini-chip">2–5 min</span>
                    <span className="mini-chip">Specific wins</span>
                  </div>
                </article>
                <article className="step-card upcoming">
                  <div className="step-top">
                    <div className="step-num">2</div>
                    <div className="step-state">Unlocks next</div>
                  </div>
                  <h5>Make 1–2 flashcards in your own words</h5>
                  <p>
                    Generation effect: writing the card is what makes it
                    stick. Click &ldquo;Flashcards&rdquo; on a reply to author them.
                  </p>
                  <div className="step-meta">
                    <span className="mini-chip">60 sec</span>
                    <span className="mini-chip">Feeds warm-up</span>
                    <span className="mini-chip">SRS-tracked</span>
                  </div>
                </article>
                <article className="step-card upcoming">
                  <div className="step-top">
                    <div className="step-num">3</div>
                    <div className="step-state">Closes the loop</div>
                  </div>
                  <h5>Bookmark the answer to your notebook</h5>
                  <p>
                    Notes graduate after 2 successful recalls. Your future
                    self gets a clean, recall-tested summary.
                  </p>
                  <div className="step-meta">
                    <span className="mini-chip">30 sec</span>
                    <span className="mini-chip">Editable</span>
                    <span className="mini-chip">Graduates to Notebook</span>
                  </div>
                </article>
              </div>
            </section>
          </div>

          {/* ─── Right rail ─── */}
          <aside className="rail">
            <section className="rail-card reveal">
              <div className="section-title" style={{ marginBottom: 8 }}>
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
                  {conversations.slice(0, 6).map((c) => (
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

            <section className="rail-card reveal delay-1">
              <div className="section-title" style={{ marginBottom: 8 }}>
                <div>
                  <h4 style={{ fontSize: 16 }}>Ready to graduate</h4>
                </div>
              </div>
              <div className="big-number">{dueCount}</div>
              <p className="small" style={{ marginTop: 4 }}>
                cards waiting in your warm-up. Two clean recalls and the
                note behind each one graduates to your notebook.
              </p>
              <Link href="/today" className="btn ghost" style={{ marginTop: 10 }}>
                Open warm-up →
              </Link>
            </section>

            <section className="rail-card reveal delay-2">
              <div className="section-title" style={{ marginBottom: 8 }}>
                <div>
                  <h4 style={{ fontSize: 16 }}>Cohort, live</h4>
                </div>
              </div>
              <div className="cohort-stream">
                <div className="cohort-item">
                  <span className="live-dot" />
                  <span>Priya K. asked the tutor about LangGraph nodes · 12m ago</span>
                </div>
                <div className="cohort-item">
                  <span className="live-dot" />
                  <span>Marcus L. shipped after a Code Review session · 1h ago</span>
                </div>
                <div className="cohort-item">
                  <span className="live-dot" />
                  <span>Ana R. graduated 3 notes from yesterday&apos;s chat · 3h ago</span>
                </div>
              </div>
            </section>
          </aside>
        </div>
      </div>
    </section>
  );
}
