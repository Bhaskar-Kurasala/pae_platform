"use client";

import {
  type CSSProperties,
  type FormEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";

import { readinessCopy } from "@/lib/copy/readiness";

export type ConversationRole = "agent" | "student";

export interface ConversationMessage {
  role: ConversationRole;
  content: string;
}

interface ConversationProps {
  messages: ConversationMessage[];
  isAgentThinking: boolean;
  isFinalizing: boolean;
  inputDisabled: boolean;
  onSend: (content: string) => void;
  /** Optional in-flow embed rendered between the message list and the
   * input. Used by the diagnostic ↔ JD decoder bundle to surface the
   * decoder inline when the interviewer requests it. */
  inlineEmbed?: ReactNode;
}

/**
 * Calm chat surface. Two reasons for inline styles over Tailwind:
 *
 *   1. The whole readiness page is inline-styled with the v8 token
 *      system; mixing in Tailwind here would be the inconsistent
 *      choice. We accepted this convention in the JD decoder PR.
 *   2. Spacing for the page's emotional anchor needs deliberate
 *      tuning — generous whitespace, not utility-class cadence.
 *
 * Tone:
 *   - Agent messages render in a Fraunces-serif voice block, tight
 *     line-height, full readable measure.
 *   - Student messages render right-aligned in a quiet Inter block.
 *   - Thinking indicator is a calm "Reading your work…" with three
 *     animated dots. NO spinner. The wait should feel like reading.
 *   - Finalizing indicator swaps to "Pulling the picture together…"
 *     while the verdict generator runs (3-5s).
 */
export function Conversation({
  messages,
  isAgentThinking,
  isFinalizing,
  inputDisabled,
  onSend,
  inlineEmbed,
}: ConversationProps) {
  const c = readinessCopy.diagnostic;
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll to bottom when a new message arrives.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, isAgentThinking, isFinalizing]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || inputDisabled) return;
    onSend(trimmed);
    setInput("");
  };

  return (
    <div
      className="diagnostic-conversation"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      <div
        ref={scrollRef}
        className="diagnostic-conversation-scroll"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          maxHeight: 420,
          overflowY: "auto",
          paddingRight: 4,
        }}
      >
        {messages.map((msg, idx) => (
          <Message key={idx} role={msg.role} content={msg.content} />
        ))}
        {isAgentThinking && !isFinalizing && (
          <ThinkingIndicator label={c.typingIndicator} />
        )}
        {isFinalizing && (
          <ThinkingIndicator label={c.finalizingIndicator} emphasis />
        )}
      </div>

      {inlineEmbed && (
        <div
          className="diagnostic-inline-embed"
          style={{
            padding: 14,
            borderRadius: 12,
            border: "1px dashed var(--forest-3)",
            background: "var(--bg, #fff)",
          }}
        >
          {inlineEmbed}
        </div>
      )}

      <form
        onSubmit={handleSubmit}
        style={{
          display: "flex",
          gap: 8,
          alignItems: "flex-end",
        }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={c.inputPlaceholder}
          disabled={inputDisabled}
          rows={2}
          onKeyDown={(e) => {
            // Enter sends; Shift+Enter newline. Standard chat affordance.
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSubmit(e as unknown as FormEvent);
            }
          }}
          style={{
            flex: 1,
            fontFamily: "var(--font-inter, Inter, system-ui)",
            fontSize: 14,
            padding: "10px 12px",
            border: "1px solid var(--forest-soft)",
            borderRadius: 8,
            background: "var(--bg, #fff)",
            color: "var(--ink)",
            resize: "vertical",
            minHeight: 50,
            maxHeight: 160,
            opacity: inputDisabled ? 0.6 : 1,
          }}
          aria-label="Type your reply"
        />
        <button
          type="submit"
          className="btn primary"
          disabled={inputDisabled || !input.trim()}
          style={{
            padding: "10px 18px",
            borderRadius: 8,
            background: "var(--forest)",
            color: "var(--forest-soft)",
            border: "none",
            fontWeight: 600,
            cursor:
              inputDisabled || !input.trim() ? "not-allowed" : "pointer",
            opacity: inputDisabled || !input.trim() ? 0.5 : 1,
            alignSelf: "stretch",
          }}
        >
          {c.sendLabel}
        </button>
      </form>
    </div>
  );
}

function Message({ role, content }: ConversationMessage) {
  const isAgent = role === "agent";
  const baseStyle: CSSProperties = {
    maxWidth: "92%",
    padding: "10px 14px",
    borderRadius: 12,
    lineHeight: 1.55,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  };
  const agentStyle: CSSProperties = {
    ...baseStyle,
    alignSelf: "flex-start",
    background: "var(--forest-soft)",
    color: "var(--ink)",
    fontFamily: "var(--serif, 'Fraunces', Georgia, serif)",
    fontSize: 16,
    border: "1px solid transparent",
  };
  const studentStyle: CSSProperties = {
    ...baseStyle,
    alignSelf: "flex-end",
    background: "var(--bg, #fff)",
    color: "var(--ink)",
    fontFamily: "var(--font-inter, Inter, system-ui)",
    fontSize: 14,
    border: "1px solid var(--forest-soft)",
  };
  return (
    <div style={isAgent ? agentStyle : studentStyle}>{content}</div>
  );
}

function ThinkingIndicator({
  label,
  emphasis = false,
}: {
  label: string;
  emphasis?: boolean;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        alignSelf: "flex-start",
        padding: "8px 14px",
        fontFamily: emphasis
          ? "var(--serif, 'Fraunces', Georgia, serif)"
          : "var(--font-inter, Inter, system-ui)",
        fontStyle: "italic",
        fontSize: emphasis ? 16 : 13,
        color: "var(--ink-2)",
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
      }}
    >
      <span>{label}</span>
      <span aria-hidden="true" style={{ letterSpacing: 1, opacity: 0.7 }}>
        ···
      </span>
    </div>
  );
}
