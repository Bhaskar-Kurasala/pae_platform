"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";
import { useStream, type StreamMessage } from "@/hooks/use-stream";
import { clarifyApi, type ClarifyPill } from "@/lib/api-client";
import { ChatSuggestionPills } from "@/components/features/chat-suggestion-pills";

const CLARIFY_MODIFIER: Record<string, string> = {
  direct: "Please just give me the direct answer.",
  hint: "Please give me a hint rather than the full answer.",
  challenge: "Please challenge me with a question rather than answering.",
};

// ── Suggested prompts shown in the empty state ───────────────────
const SUGGESTED_PROMPTS = [
  "What is RAG and how does it work?",
  "Review my Python code for production readiness",
  "Quiz me on LangGraph concepts",
  "Help me build my AI engineering portfolio",
];

// ── Agent colour palette for the avatar circle ──────────────────
const AGENT_COLORS: Record<string, string> = {
  socratic_tutor: "bg-[#1D9E75]",
  code_review: "bg-[#7C3AED]",
  adaptive_quiz: "bg-amber-500",
  mock_interview: "bg-rose-500",
  portfolio_builder: "bg-blue-500",
  progress_report: "bg-cyan-500",
  default: "bg-[#7C3AED]",
};

const AGENT_SPECIALTIES: Record<string, string> = {
  socratic_tutor: "Guided Learning",
  code_review: "Code Quality",
  adaptive_quiz: "Knowledge Testing",
  mock_interview: "Career Prep",
  portfolio_builder: "Portfolio",
  progress_report: "Analytics",
  mcq_factory: "MCQ Generation",
  coding_assistant: "Code Help",
  student_buddy: "Quick Explanations",
  adaptive_path: "Learning Paths",
  project_evaluator: "Project Grading",
  job_match: "Career",
  peer_matching: "Community",
  community_celebrator: "Milestones",
  disrupt_prevention: "Re-engagement",
  default: "AI Coach",
};

function agentInitials(name: string): string {
  return name
    .split("_")
    .map((w) => w[0]?.toUpperCase() ?? "")
    .slice(0, 2)
    .join("");
}

function agentLabel(name: string): string {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// ── Code block with copy button ──────────────────────────────────
function CodeBlock({
  children,
  className,
}: {
  children?: React.ReactNode;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const code = typeof children === "string" ? children : String(children ?? "");
  const language = className?.replace("language-", "") ?? "code";

  const handleCopy = () => {
    void navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="relative my-3 rounded-lg overflow-hidden border border-border/50">
      <div className="flex items-center justify-between bg-[#1A1A1A] px-4 py-2">
        <span className="text-xs text-zinc-400 font-mono">{language}</span>
        <button
          onClick={handleCopy}
          aria-label={copied ? "Copied" : "Copy code"}
          className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-[#1D9E75]" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto bg-[#111111] p-4 text-sm font-mono text-zinc-200 leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  );
}

// ── Single message bubble ────────────────────────────────────────
function MessageBubble({
  message,
  isStreaming,
}: {
  message: StreamMessage;
  isStreaming: boolean;
}) {
  const isUser = message.role === "user";
  const isLast = isStreaming && !isUser && message.content === "";

  if (isUser) {
    return (
      <div className="flex justify-end mb-4">
        <div className="max-w-[70%] rounded-2xl rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground leading-relaxed">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="mb-6 max-w-3xl">
      {message.agentName && message.agentName !== "system" && (
        <div className="flex items-center gap-2 mb-2">
          <div
            className={cn(
              "h-6 w-6 rounded-full flex items-center justify-center text-white text-xs font-bold shrink-0",
              AGENT_COLORS[message.agentName] ?? AGENT_COLORS.default,
            )}
            aria-hidden="true"
          >
            {agentInitials(message.agentName)}
          </div>
          <span className="text-xs font-medium text-muted-foreground">
            {agentLabel(message.agentName)}
          </span>
        </div>
      )}

      <div className="prose prose-sm dark:prose-invert max-w-none text-foreground leading-relaxed">
        {isLast ? (
          <span className="inline-block w-0.5 h-4 bg-primary animate-pulse rounded-full" aria-label="Streaming" />
        ) : (
          <>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                code({ className, children, ...props }: any) {
                  const isBlock = String(className ?? "").startsWith("language-");
                  if (isBlock) {
                    return (
                      <CodeBlock className={String(className ?? "")}>
                        {String(children ?? "")}
                      </CodeBlock>
                    );
                  }
                  return (
                    <code
                      className="rounded bg-muted px-1.5 py-0.5 text-sm font-mono text-foreground"
                      {...props}
                    >
                      {children}
                    </code>
                  );
                },
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                pre({ children }: any) {
                  // Prevent double-wrapping — CodeBlock renders its own <pre>
                  return <>{children}</>;
                },
              }}
            >
              {message.content}
            </ReactMarkdown>
            {isStreaming && message.content.length > 0 && (
              <span
                className="inline-block w-0.5 h-4 bg-primary animate-pulse rounded-full ml-0.5 align-middle"
                aria-hidden="true"
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Agent Header Bar ─────────────────────────────────────────────
function AgentHeaderBar({ name }: { name: string | undefined }) {
  const displayName = name ? agentLabel(name) : "AI Coach";
  const specialty = name
    ? (AGENT_SPECIALTIES[name] ?? AGENT_SPECIALTIES.default)
    : "Auto-routing";
  const colorClass = name ? (AGENT_COLORS[name] ?? AGENT_COLORS.default) : AGENT_COLORS.default;
  const initials = name ? agentInitials(name) : "AI";

  return (
    <div className="flex items-center gap-3 h-14 px-4 border-b bg-card shrink-0">
      <div
        className={cn(
          "h-8 w-8 rounded-full flex items-center justify-center text-white text-xs font-bold shrink-0",
          colorClass,
        )}
        aria-hidden="true"
      >
        {initials}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold leading-none">{displayName}</p>
        <p className="text-xs text-muted-foreground mt-0.5">{specialty}</p>
      </div>
      <span className="shrink-0 rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
        {name ? "Pinned" : "Auto"}
      </span>
    </div>
  );
}

// ── Main exported component ──────────────────────────────────────
export interface AgentChatStreamProps {
  agentName?: string;
  initialContext?: Record<string, unknown>;
}

export function AgentChatStream({ agentName, initialContext }: AgentChatStreamProps) {
  const { messages, isStreaming, sendMessage } = useStream({ agentName, initialContext });
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [clarifyPills, setClarifyPills] = useState<ClarifyPill[]>([]);
  const [pendingMessage, setPendingMessage] = useState<string>("");
  const [followupPills, setFollowupPills] = useState<ClarifyPill[]>([]);
  const [followupAnchorId, setFollowupAnchorId] = useState<string | null>(null);

  // After a streamed assistant reply finishes, fetch follow-up pills
  const lastMsg = messages[messages.length - 1];
  useEffect(() => {
    if (isStreaming) return;
    if (!lastMsg || lastMsg.role !== "assistant") return;
    if (lastMsg.agentName === "system") return;
    if (!lastMsg.content || lastMsg.content.length < 80) {
      setFollowupPills([]);
      setFollowupAnchorId(null);
      return;
    }
    if (followupAnchorId === lastMsg.id) return;

    let cancelled = false;
    clarifyApi
      .followups(lastMsg.content)
      .then((res) => {
        if (cancelled) return;
        setFollowupPills(res.pills);
        setFollowupAnchorId(lastMsg.id);
      })
      .catch(() => {
        /* pills are optional — degrade silently */
      });
    return () => {
      cancelled = true;
    };
  }, [isStreaming, lastMsg, followupAnchorId]);

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const maxHeight = 4 * 24 + 24; // 4 rows × ~24px + padding
    ta.style.height = `${Math.min(ta.scrollHeight, maxHeight)}px`;
  }, [input]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    // Clear any stale pill state from prior turns
    setFollowupPills([]);
    setFollowupAnchorId(null);

    // Ask backend whether to show clarify pills first
    try {
      const decision = await clarifyApi.check(text);
      if (decision.show_pills && decision.pills.length > 0) {
        setClarifyPills(decision.pills);
        setPendingMessage(text);
        setInput("");
        return;
      }
    } catch {
      // If clarify check fails, fall through and send normally
    }

    setInput("");
    await sendMessage(text);
  }, [input, isStreaming, sendMessage]);

  const handleClarifyPick = useCallback(
    async (pill: ClarifyPill) => {
      const base = pendingMessage;
      const modifier = CLARIFY_MODIFIER[pill.key] ?? "";
      const composed = modifier ? `${base}\n\n(${modifier})` : base;
      setClarifyPills([]);
      setPendingMessage("");
      await sendMessage(composed);
    },
    [pendingMessage, sendMessage],
  );

  const handleFollowupPick = useCallback((pill: ClarifyPill) => {
    setInput(pill.label);
    textareaRef.current?.focus();
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void handleSend();
    }
  };

  const handleSuggestedPrompt = (prompt: string) => {
    setInput(prompt);
    textareaRef.current?.focus();
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Agent identity bar */}
      <AgentHeaderBar name={agentName} />

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-6" aria-live="polite" aria-label="Chat messages">
        {isEmpty ? (
          // Empty state with suggested prompts
          <div className="flex flex-col items-center justify-center h-full text-center gap-6 py-16">
            <div
              className={cn(
                "h-14 w-14 rounded-full flex items-center justify-center text-white text-lg font-bold",
                agentName ? (AGENT_COLORS[agentName] ?? AGENT_COLORS.default) : AGENT_COLORS.default,
              )}
              aria-hidden="true"
            >
              {agentName ? agentInitials(agentName) : "AI"}
            </div>
            <div className="max-w-sm">
              <h2 className="font-semibold text-lg">
                {agentName ? `Ask ${agentLabel(agentName)}` : "Ask your AI Coach"}
              </h2>
              <p className="text-muted-foreground text-sm mt-1.5 leading-relaxed">
                {agentName
                  ? `${AGENT_SPECIALTIES[agentName] ?? "AI"} — powered by Claude`
                  : "The right agent is automatically selected for each question."}
              </p>
            </div>
            <div className="flex flex-wrap gap-2 justify-center max-w-lg">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => handleSuggestedPrompt(prompt)}
                  aria-label={`Suggested prompt: ${prompt}`}
                  className="rounded-full border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => {
            const isLastAssistant =
              msg.role === "assistant" && idx === messages.length - 1;
            return (
              <div key={msg.id}>
                <MessageBubble
                  message={msg}
                  isStreaming={
                    isStreaming &&
                    msg === messages[messages.length - 1] &&
                    msg.role === "assistant"
                  }
                />
                {isLastAssistant &&
                  !isStreaming &&
                  followupAnchorId === msg.id &&
                  followupPills.length > 0 && (
                    <ChatSuggestionPills
                      pills={followupPills}
                      onPick={handleFollowupPick}
                      variant="followup"
                    />
                  )}
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Clarify pills — rendered above the input when show_pills returns true */}
      {clarifyPills.length > 0 && (
        <div className="shrink-0 border-t bg-card px-4 pt-3">
          <div className="max-w-3xl mx-auto">
            <ChatSuggestionPills
              pills={clarifyPills}
              onPick={handleClarifyPick}
              variant="clarify"
            />
          </div>
        </div>
      )}

      {/* Input area */}
      <div className="shrink-0 border-t bg-card px-4 py-4">
        <div className="flex gap-3 max-w-3xl mx-auto items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask your AI coach anything..."
            rows={1}
            disabled={isStreaming}
            aria-label="Message input"
            className={cn(
              "flex-1 resize-none rounded-xl border border-input bg-background px-4 py-3 text-sm leading-relaxed outline-none",
              "focus:ring-2 focus:ring-primary/30 focus:border-primary transition",
              "max-h-[120px] overflow-y-auto",
              "disabled:opacity-60",
            )}
          />
          <button
            onClick={() => void handleSend()}
            disabled={isStreaming || !input.trim()}
            aria-label={isStreaming ? "Sending…" : "Send message"}
            className={cn(
              "shrink-0 h-11 w-11 rounded-xl flex items-center justify-center transition-colors",
              "bg-primary text-primary-foreground hover:bg-primary/90",
              "disabled:opacity-40 disabled:cursor-not-allowed",
            )}
          >
            {isStreaming ? (
              // Animated dots while streaming
              <span className="flex gap-0.5" aria-hidden="true">
                <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:0ms]" />
                <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:300ms]" />
              </span>
            ) : (
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="currentColor"
                className="h-5 w-5"
                aria-hidden="true"
              >
                <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
              </svg>
            )}
          </button>
        </div>
        <p className="text-center text-xs text-muted-foreground mt-2">
          {isStreaming
            ? "Generating response…"
            : "Cmd+Enter to send · Powered by Claude"}
        </p>
      </div>
    </div>
  );
}
