"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowUp, Bot, BriefcaseBusiness, Clock, Code2, GraduationCap, Plus, RefreshCw, Sparkles, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { MarkdownRenderer } from "@/components/features/markdown-renderer";
import { useStream } from "@/hooks/use-stream";
import { exercisesApi } from "@/lib/api-client";

// ── Mode chips ───────────────────────────────────────────────────
const MODES = [
  { label: "Auto",        agentName: null,               icon: Sparkles,       color: "text-primary" },
  { label: "Tutor",       agentName: "socratic_tutor",   icon: GraduationCap,  color: "text-violet-500" },
  { label: "Code Review", agentName: "coding_assistant", icon: Code2,          color: "text-blue-500" },
  { label: "Career",      agentName: "career_coach",     icon: BriefcaseBusiness, color: "text-orange-500" },
  { label: "Quiz Me",     agentName: "adaptive_quiz",    icon: Bot,            color: "text-green-500" },
] as const;

type ModeAgent = (typeof MODES)[number]["agentName"];

// ── Helpers ──────────────────────────────────────────────────────
const AGENT_GRADIENTS: Record<string, string> = {
  socratic_tutor:   "from-violet-500 to-purple-600",
  coding_assistant: "from-blue-500 to-cyan-600",
  adaptive_quiz:    "from-green-500 to-emerald-600",
  career_coach:     "from-orange-500 to-amber-600",
};

function agentGradient(name: string | undefined) {
  if (!name) return "from-primary to-primary/70";
  return AGENT_GRADIENTS[name] ?? "from-primary to-primary/70";
}

interface ConversationEntry {
  id: string;
  preview: string;
  agentName?: string;
  timestamp: Date;
}

// DISC-45 — persist the sidebar's recent-conversations index to localStorage
// so refresh + tab-reopen preserves history. Only 20 most recent are kept,
// matching the existing cap in handleNewMessage. Each entry is tiny (id +
// preview + agent + ts) so we stay well under localStorage quota.
const CONVERSATIONS_KEY = "chat-conversations-v1";
const CONVERSATIONS_CAP = 20;

type StoredConversation = Omit<ConversationEntry, "timestamp"> & { timestamp: string };

function readStoredConversations(): ConversationEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(CONVERSATIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((e): ConversationEntry | null => {
        if (!e || typeof e !== "object") return null;
        const s = e as Partial<StoredConversation>;
        if (typeof s.id !== "string" || typeof s.preview !== "string") return null;
        const ts = typeof s.timestamp === "string" ? new Date(s.timestamp) : new Date();
        return {
          id: s.id,
          preview: s.preview,
          agentName: typeof s.agentName === "string" ? s.agentName : undefined,
          timestamp: Number.isNaN(ts.getTime()) ? new Date() : ts,
        };
      })
      .filter((x): x is ConversationEntry => x !== null)
      .slice(0, CONVERSATIONS_CAP);
  } catch {
    return [];
  }
}

// ── Sidebar ──────────────────────────────────────────────────────
function Sidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
}: {
  conversations: ConversationEntry[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <aside className="hidden lg:flex flex-col w-64 xl:w-72 border-r bg-card/50 shrink-0">
      <div className="flex items-center justify-between px-4 h-16 border-b shrink-0">
        <div className="flex items-center gap-2">
          <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-primary to-primary/60 flex items-center justify-center">
            <Bot className="h-4 w-4 text-white" aria-hidden="true" />
          </div>
          <span className="font-semibold text-sm">AI Tutor</span>
        </div>
        <button
          onClick={onNew}
          aria-label="New conversation"
          className="h-8 w-8 rounded-lg flex items-center justify-center hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-3 px-2">
        {conversations.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 gap-3 text-center px-4">
            <Clock className="h-8 w-8 text-muted-foreground/30" aria-hidden="true" />
            <p className="text-xs text-muted-foreground">No conversations yet</p>
          </div>
        ) : (
          <>
            <p className="px-2 mb-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50">
              Recent
            </p>
            {conversations.map((conv) => (
              <button
                key={conv.id}
                onClick={() => onSelect(conv.id)}
                aria-label={`Open conversation: ${conv.preview}`}
                className={cn(
                  "w-full text-left rounded-xl px-3 py-2.5 mb-0.5 transition-colors",
                  activeId === conv.id ? "bg-primary/10 text-primary" : "hover:bg-muted/70 text-foreground",
                )}
              >
                <p className="text-sm font-medium truncate leading-snug">{conv.preview}</p>
                <div className="flex items-center gap-1.5 mt-1">
                  {conv.agentName && (
                    <span className={cn("text-[10px] font-medium capitalize", activeId === conv.id ? "text-primary/70" : "text-primary/60")}>
                      {MODES.find((m) => m.agentName === conv.agentName)?.label ?? conv.agentName.split("_").join(" ")}
                    </span>
                  )}
                  <span className="text-[10px] text-muted-foreground">
                    {conv.timestamp.toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                  </span>
                </div>
              </button>
            ))}
          </>
        )}
      </div>
    </aside>
  );
}

// ── Welcome screen ───────────────────────────────────────────────
const SUGGESTED_PROMPTS = [
  { text: "What is RAG and how does it work?",                    icon: "🔍" },
  { text: "Review my Python code for production readiness",       icon: "🐍" },
  { text: "Quiz me on LangGraph concepts",                        icon: "⚡" },
  { text: "Help me build my AI engineering portfolio",            icon: "🚀" },
  { text: "Explain the difference between ReAct and CoT",         icon: "🧠" },
  { text: "How do I deploy a LangGraph agent to production?",     icon: "☁️" },
];

function WelcomeScreen({ mode, onPrompt }: { mode: typeof MODES[number]; onPrompt: (text: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full px-6 py-12 gap-8">
      <div className="relative">
        <div className={cn("h-20 w-20 rounded-3xl bg-gradient-to-br flex items-center justify-center shadow-lg", agentGradient(mode.agentName ?? undefined))}>
          <Bot className="h-10 w-10 text-white" aria-hidden="true" />
        </div>
        <div className="absolute -bottom-1 -right-1 h-6 w-6 rounded-full bg-green-500 border-2 border-background flex items-center justify-center">
          <Sparkles className="h-3 w-3 text-white" aria-hidden="true" />
        </div>
      </div>

      <div className="text-center max-w-md">
        <h2 className="text-2xl font-bold tracking-tight">
          {mode.agentName ? `${mode.label} Mode` : "Your AI Coach"}
        </h2>
        <p className="text-muted-foreground text-sm mt-2 leading-relaxed">
          {mode.agentName
            ? `Focused on ${mode.label.toLowerCase()}. Ask me anything.`
            : "The right agent is automatically selected based on your question."}
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 w-full max-w-4xl">
        {SUGGESTED_PROMPTS.map((p) => (
          <button
            key={p.text}
            onClick={() => onPrompt(p.text)}
            aria-label={`Suggested prompt: ${p.text}`}
            className="group flex items-start gap-3 rounded-2xl border border-border/60 bg-card/80 px-4 py-3.5 text-left hover:border-primary/40 hover:bg-primary/5 hover:shadow-sm transition-all duration-150"
          >
            <span className="text-lg leading-none mt-0.5 shrink-0">{p.icon}</span>
            <span className="text-sm text-muted-foreground group-hover:text-foreground transition-colors line-clamp-2 leading-snug">
              {p.text}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Message bubbles ──────────────────────────────────────────────
function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end gap-3">
      <div className="max-w-[60%]">
        <div className="rounded-3xl rounded-tr-lg bg-primary px-5 py-3.5 text-sm text-primary-foreground leading-relaxed shadow-sm">
          {content}
        </div>
      </div>
      <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center shrink-0 mt-1 border border-border/50">
        <User className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      </div>
    </div>
  );
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 py-1" aria-label="Thinking">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="h-2 w-2 rounded-full bg-muted-foreground/40 animate-bounce"
          style={{ animationDelay: `${delay}ms` }}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}

function AssistantBubble({ content, agentName, isStreaming, isLast, isThinking }: {
  content: string; agentName?: string; isStreaming: boolean; isLast: boolean; isThinking?: boolean;
}) {
  const modeLabel = MODES.find((m) => m.agentName === agentName)?.label;

  return (
    <div className="flex gap-3">
      <div className={cn(
        "h-8 w-8 rounded-full bg-gradient-to-br flex items-center justify-center shrink-0 mt-1 shadow-sm",
        isThinking ? "animate-pulse" : "",
        agentGradient(agentName),
      )}>
        <Bot className="h-4 w-4 text-white" aria-hidden="true" />
      </div>
      <div className="flex-1 min-w-0">
        {agentName && agentName !== "system" && (
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/60 mb-1.5 ml-1">
            {modeLabel ?? agentName.split("_").join(" ")}
          </p>
        )}
        <div className="rounded-3xl rounded-tl-lg bg-card border border-border/50 px-5 py-4 shadow-sm">
          {isThinking ? (
            <ThinkingDots />
          ) : (
            <MarkdownRenderer content={content} isStreaming={isStreaming && isLast} />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Mode chip row ────────────────────────────────────────────────
function ModeChips({ active, onChange }: { active: ModeAgent; onChange: (m: ModeAgent) => void }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {MODES.map((mode) => {
        const Icon = mode.icon;
        const isActive = active === mode.agentName;
        return (
          <button
            key={mode.label}
            onClick={() => onChange(mode.agentName)}
            aria-pressed={isActive}
            aria-label={`Switch to ${mode.label} mode`}
            className={cn(
              "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all",
              isActive
                ? "bg-primary text-primary-foreground shadow-sm"
                : "border border-border/60 text-muted-foreground hover:border-primary/40 hover:text-foreground hover:bg-primary/5",
            )}
          >
            <Icon className={cn("h-3.5 w-3.5", isActive ? "text-primary-foreground" : mode.color)} aria-hidden="true" />
            {mode.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Input bar ────────────────────────────────────────────────────
function InputBar({ value, onChange, onSend, isStreaming, activeMode, onModeChange }: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  isStreaming: boolean;
  activeMode: ModeAgent;
  onModeChange: (m: ModeAgent) => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }, [value]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // DISC-46 — plain Enter sends; Shift+Enter inserts a newline. Matches
    // the prevailing convention across ChatGPT / Claude.ai / Gemini.
    if (e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <div className="shrink-0 px-4 pb-4 pt-2">
      <div className={cn(
        "max-w-5xl mx-auto rounded-3xl border bg-card shadow-lg transition-shadow",
        "focus-within:shadow-xl focus-within:border-primary/40",
        isStreaming ? "border-primary/30" : "border-border/60",
      )}>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask your AI coach anything…"
          rows={1}
          disabled={isStreaming}
          aria-label="Message input"
          className="w-full resize-none bg-transparent px-5 pt-4 pb-2 text-sm leading-relaxed outline-none placeholder:text-muted-foreground/50 disabled:opacity-60 max-h-[160px] overflow-y-auto"
        />
        <div className="flex items-center justify-between px-4 pb-3 gap-3">
          <ModeChips active={activeMode} onChange={onModeChange} />
          <div className="flex items-center gap-2 shrink-0">
            <span className="hidden sm:block text-[11px] text-muted-foreground/50">
              {isStreaming ? "Generating…" : "Enter to send · Shift+Enter newline"}
            </span>
            <button
              onClick={onSend}
              disabled={isStreaming || !value.trim()}
              aria-label={isStreaming ? "Generating response" : "Send message"}
              className={cn(
                "h-9 w-9 rounded-2xl flex items-center justify-center transition-all",
                "bg-primary text-primary-foreground shadow-sm",
                "hover:bg-primary/90 hover:shadow-md active:scale-95",
                "disabled:opacity-30 disabled:cursor-not-allowed",
              )}
            >
              {isStreaming ? (
                <span className="flex gap-0.5" aria-hidden="true">
                  <span className="h-1 w-1 rounded-full bg-current animate-bounce [animation-delay:0ms]" />
                  <span className="h-1 w-1 rounded-full bg-current animate-bounce [animation-delay:120ms]" />
                  <span className="h-1 w-1 rounded-full bg-current animate-bounce [animation-delay:240ms]" />
                </span>
              ) : (
                <ArrowUp className="h-4 w-4" aria-hidden="true" />
              )}
            </button>
          </div>
        </div>
      </div>
      <p className="text-center text-[11px] text-muted-foreground/40 mt-2">
        Powered by Claude · Responses may be inaccurate
      </p>
    </div>
  );
}

// ── Chat area ────────────────────────────────────────────────────
function ChatArea({ mode, onNewMessage, onModeChange, prefill }: {
  mode: typeof MODES[number];
  onNewMessage: (preview: string, agent: string | undefined) => void;
  onModeChange: (m: ModeAgent) => void;
  prefill?: string;
}) {
  const { messages, isStreaming, error, sendMessage, retry } = useStream({ agentName: mode.agentName ?? undefined });
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastReportedLength = useRef(0);
  const prefillApplied = useRef(false);

  // DISC-38 — when routed from a failing submission (?submission_id=...),
  // seed the composer with a concrete prompt so the student can send it or
  // edit first. Only runs once per mount — switching modes remounts this
  // component via `key={chatKey}`, so the prefill stays available until
  // it's been typed/sent.
  useEffect(() => {
    if (prefillApplied.current) return;
    if (!prefill) return;
    if (messages.length > 0) return;
    setInput(prefill);
    prefillApplied.current = true;
  }, [prefill, messages.length]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (messages.length > lastReportedLength.current) {
      const last = messages[messages.length - 1];
      if (last?.role === "user" && messages.length === 1) {
        onNewMessage(last.content.slice(0, 60), mode.agentName ?? undefined);
      }
      lastReportedLength.current = messages.length;
    }
  }, [messages, mode.agentName, onNewMessage]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    await sendMessage(text);
  }, [input, isStreaming, sendMessage]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-1 overflow-y-auto" aria-live="polite">
        {messages.length === 0 ? (
          <WelcomeScreen mode={mode} onPrompt={setInput} />
        ) : (
          <div className="max-w-5xl mx-auto px-6 py-6 space-y-6">
            {messages.map((msg, i) => {
              const isLast = i === messages.length - 1;
              return msg.role === "user"
                ? <UserBubble key={msg.id} content={msg.content} />
                : <AssistantBubble key={msg.id} content={msg.content} agentName={msg.agentName} isStreaming={isStreaming} isLast={isLast} isThinking={msg.isThinking} />;
            })}
            <div ref={messagesEndRef} className="h-4" />
          </div>
        )}
      </div>

      {error ? (
        <div className="mx-auto w-full max-w-5xl px-6 pt-3" role="alert">
          <div className="flex items-center justify-between gap-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-200">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
              <span>Connection lost — your last message didn&apos;t get a response.</span>
            </div>
            <button
              type="button"
              onClick={() => void retry()}
              disabled={isStreaming}
              className="inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-900 transition-colors hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-100 dark:hover:bg-red-900/40"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              Retry
            </button>
          </div>
        </div>
      ) : null}

      <InputBar
        value={input}
        onChange={setInput}
        onSend={() => void handleSend()}
        isStreaming={isStreaming}
        activeMode={mode.agentName}
        onModeChange={onModeChange}
      />
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────
export default function ChatPage() {
  return (
    <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-muted-foreground">Loading…</div>}>
      <ChatPageInner />
    </Suspense>
  );
}

function ChatPageInner() {
  const searchParams = useSearchParams();
  const submissionId = searchParams.get("submission_id");
  const topic = searchParams.get("topic");

  const [activeMode, setActiveMode] = useState<ModeAgent>(null);
  const [conversations, setConversations] = useState<ConversationEntry[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const [prefill, setPrefill] = useState<string | undefined>(undefined);
  const conversationsHydrated = useRef(false);
  const prefillLoadedFor = useRef<string | null>(null);

  // DISC-38 — if arrived from a failing exercise submission, fetch the
  // submission, build a tutor-ready prompt, and switch to Tutor mode.
  useEffect(() => {
    if (!submissionId) return;
    if (prefillLoadedFor.current === submissionId) return;
    prefillLoadedFor.current = submissionId;
    let cancelled = false;
    (async () => {
      try {
        const sub = await exercisesApi.getSubmission(submissionId);
        if (cancelled) return;
        const intro = topic === "exercise_help"
          ? "I just submitted an exercise and it didn't pass. Can you help me understand what went wrong?"
          : "Can you help me with this submission?";
        const feedback = sub.feedback ? `\n\nFeedback I got:\n${sub.feedback}` : "";
        setPrefill(`${intro}${feedback}`);
        setActiveMode("socratic_tutor");
      } catch {
        setPrefill("I need help with an exercise I just submitted — it didn't pass. Can you walk me through what might have gone wrong?");
        setActiveMode("socratic_tutor");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [submissionId, topic]);

  // DISC-45 — hydrate the sidebar from localStorage after mount (client-only
  // to avoid an SSR/client markup mismatch).
  useEffect(() => {
    const stored = readStoredConversations();
    if (stored.length > 0) setConversations(stored);
    conversationsHydrated.current = true;
  }, []);

  useEffect(() => {
    if (!conversationsHydrated.current) return;
    if (typeof window === "undefined") return;
    try {
      const serialized: StoredConversation[] = conversations.map((c) => ({
        id: c.id,
        preview: c.preview,
        agentName: c.agentName,
        timestamp: c.timestamp.toISOString(),
      }));
      window.localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(serialized));
    } catch {
      /* quota or disabled storage — ignore */
    }
  }, [conversations]);

  const currentMode = MODES.find((m) => m.agentName === activeMode) ?? MODES[0];

  const handleModeChange = (m: ModeAgent) => {
    setActiveMode(m);
    setChatKey((k) => k + 1);
  };

  const handleNew = () => {
    setActiveMode(null);
    setChatKey((k) => k + 1);
    setActiveConvId(null);
  };

  const handleNewMessage = useCallback((preview: string, agent: string | undefined) => {
    const id = crypto.randomUUID();
    setActiveConvId(id);
    setConversations((prev) => [
      { id, preview, agentName: agent, timestamp: new Date() },
      ...prev.slice(0, 19),
    ]);
  }, []);

  return (
    <div className="flex h-full overflow-hidden bg-background">
      <Sidebar
        conversations={conversations}
        activeId={activeConvId}
        onSelect={setActiveConvId}
        onNew={handleNew}
      />

      <div className="flex flex-col flex-1 overflow-hidden min-w-0">
        {/* Mobile top bar */}
        <header className="lg:hidden flex items-center justify-between h-14 px-4 border-b bg-card/80 backdrop-blur shrink-0">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-primary to-primary/60 flex items-center justify-center">
              <Bot className="h-4 w-4 text-white" aria-hidden="true" />
            </div>
            <span className="font-semibold text-sm">AI Tutor</span>
          </div>
          <button onClick={handleNew} aria-label="New conversation" className="h-8 w-8 rounded-lg flex items-center justify-center hover:bg-muted transition-colors text-muted-foreground">
            <Plus className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        <div className="flex-1 overflow-hidden">
          <ChatArea
            key={chatKey}
            mode={currentMode}
            onNewMessage={handleNewMessage}
            onModeChange={handleModeChange}
            prefill={prefill}
          />
        </div>
      </div>
    </div>
  );
}
