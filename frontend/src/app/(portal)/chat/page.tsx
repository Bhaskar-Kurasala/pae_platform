"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ChevronDown, Clock, PanelLeft, X } from "lucide-react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api-client";
import { useStream } from "@/hooks/use-stream";

// ── Types ────────────────────────────────────────────────────────
interface AgentListItem {
  name: string;
  description: string;
}

interface ConversationEntry {
  id: string;
  preview: string;
  agentName?: string;
  timestamp: Date;
}

// ── Agent selector dropdown ──────────────────────────────────────
function AgentSelector({
  agents,
  selected,
  onSelect,
}: {
  agents: AgentListItem[];
  selected: string | null;
  onSelect: (name: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const selectedLabel = selected
    ? selected
        .split("_")
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ")
    : "Auto-route";

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Select agent"
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-1.5 text-sm font-medium hover:bg-muted transition-colors"
      >
        <span>{selectedLabel}</span>
        <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label="Agent selection"
          className="absolute top-full mt-1 left-0 z-50 min-w-[220px] rounded-xl border bg-popover shadow-lg overflow-hidden py-1"
        >
          <button
            role="option"
            aria-selected={selected === null}
            onClick={() => {
              onSelect(null);
              setOpen(false);
            }}
            className={cn(
              "w-full text-left px-4 py-2.5 text-sm hover:bg-muted transition-colors",
              selected === null && "text-primary font-medium",
            )}
          >
            <span className="font-medium">Auto-route</span>
            <p className="text-xs text-muted-foreground mt-0.5">MOA picks the best agent</p>
          </button>
          <div className="border-t my-1" />
          {agents.map((agent) => (
            <button
              key={agent.name}
              role="option"
              aria-selected={selected === agent.name}
              onClick={() => {
                onSelect(agent.name);
                setOpen(false);
              }}
              className={cn(
                "w-full text-left px-4 py-2.5 text-sm hover:bg-muted transition-colors",
                selected === agent.name && "text-primary font-medium",
              )}
            >
              <span className="font-medium capitalize">
                {agent.name.split("_").join(" ")}
              </span>
              {agent.description && (
                <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                  {agent.description}
                </p>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── History Drawer ───────────────────────────────────────────────
function HistoryDrawer({
  open,
  onClose,
  conversations,
  activeId,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  conversations: ConversationEntry[];
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/40 md:bg-transparent"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Drawer panel */}
      <aside
        aria-label="Conversation history"
        className={cn(
          "fixed left-0 top-0 bottom-0 z-50 w-72 bg-card border-r shadow-xl",
          "flex flex-col transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between h-14 px-4 border-b shrink-0">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <span className="font-semibold text-sm">History</span>
          </div>
          <button
            onClick={onClose}
            aria-label="Close history"
            className="rounded p-1 hover:bg-muted transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto py-2">
          {conversations.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">
              No conversations yet. Start chatting!
            </div>
          ) : (
            conversations.map((conv) => (
              <button
                key={conv.id}
                onClick={() => {
                  onSelect(conv.id);
                  onClose();
                }}
                aria-label={`Open conversation: ${conv.preview}`}
                className={cn(
                  "w-full text-left px-4 py-3 hover:bg-muted transition-colors",
                  activeId === conv.id && "bg-primary/10",
                )}
              >
                <p className="text-sm font-medium truncate">{conv.preview}</p>
                <div className="flex items-center gap-1.5 mt-0.5">
                  {conv.agentName && (
                    <span className="text-xs text-primary capitalize">
                      {conv.agentName.split("_").join(" ")}
                    </span>
                  )}
                  <span className="text-xs text-muted-foreground">
                    {conv.timestamp.toLocaleDateString()}
                  </span>
                </div>
              </button>
            ))
          )}
        </div>
      </aside>
    </>
  );
}

// ── Chat wrapper that captures history entries ────────────────────
function ChatWithHistory({
  agentName,
  onNewMessage,
}: {
  agentName: string | undefined;
  onNewMessage: (preview: string, agent: string | undefined) => void;
}) {
  const { messages, isStreaming, sendMessage } = useStream({ agentName });
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastReportedLength = useRef(0);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
  }, [input]);

  // Report new assistant messages for history
  useEffect(() => {
    if (messages.length > lastReportedLength.current) {
      const last = messages[messages.length - 1];
      if (last?.role === "user" && messages.length === 1) {
        onNewMessage(last.content.slice(0, 60), agentName);
      }
      lastReportedLength.current = messages.length;
    }
  }, [messages, agentName, onNewMessage]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    await sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void handleSend();
    }
  };

  const SUGGESTED_PROMPTS = [
    "What is RAG and how does it work?",
    "Review my Python code for production readiness",
    "Quiz me on LangGraph concepts",
    "Help me build my AI engineering portfolio",
  ];

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-6 py-6" aria-live="polite">
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center h-full text-center gap-6 py-16">
            <div className="h-14 w-14 rounded-full bg-primary/10 flex items-center justify-center">
              <span className="text-2xl font-bold text-primary">AI</span>
            </div>
            <div className="max-w-sm">
              <h2 className="font-semibold text-xl">Ask your AI Coach</h2>
              <p className="text-muted-foreground text-sm mt-2">
                {agentName
                  ? `${agentName.split("_").join(" ")} — powered by Claude`
                  : "The right agent is automatically selected for your question."}
              </p>
            </div>
            <div className="flex flex-wrap gap-2 justify-center max-w-lg">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => setInput(prompt)}
                  aria-label={`Suggested prompt: ${prompt}`}
                  className="rounded-full border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg, i) => {
              const isLast = i === messages.length - 1;
              if (msg.role === "user") {
                return (
                  <div key={msg.id} className="flex justify-end mb-4">
                    <div className="max-w-[70%] rounded-2xl rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground leading-relaxed">
                      {msg.content}
                    </div>
                  </div>
                );
              }
              return (
                <div key={msg.id} className="mb-6 max-w-3xl">
                  {msg.agentName && msg.agentName !== "system" && (
                    <p className="text-xs font-medium text-muted-foreground mb-1.5 capitalize">
                      {msg.agentName.split("_").join(" ")}
                    </p>
                  )}
                  <div className="prose prose-sm dark:prose-invert max-w-none text-foreground leading-relaxed whitespace-pre-wrap">
                    {msg.content}
                    {isStreaming && isLast && (
                      <span
                        className="inline-block w-0.5 h-4 bg-primary animate-pulse rounded-full ml-0.5 align-middle"
                        aria-hidden="true"
                      />
                    )}
                  </div>
                </div>
              );
            })}
          </>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="shrink-0 border-t bg-card px-6 py-4">
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
              "max-h-[120px] overflow-y-auto disabled:opacity-60",
            )}
          />
          <button
            onClick={() => void handleSend()}
            disabled={isStreaming || !input.trim()}
            aria-label={isStreaming ? "Generating response" : "Send message"}
            className={cn(
              "shrink-0 h-11 w-11 rounded-xl flex items-center justify-center transition-colors",
              "bg-primary text-primary-foreground hover:bg-primary/90",
              "disabled:opacity-40 disabled:cursor-not-allowed",
            )}
          >
            {isStreaming ? (
              <span className="flex gap-0.5" aria-hidden="true">
                <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:0ms]" />
                <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:300ms]" />
              </span>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5" aria-hidden="true">
                <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
              </svg>
            )}
          </button>
        </div>
        <p className="text-center text-xs text-muted-foreground mt-2">
          {isStreaming ? "Generating…" : "Cmd+Enter to send · Powered by Claude"}
        </p>
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────
export default function ChatPage() {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [conversations, setConversations] = useState<ConversationEntry[]>([]);
  const [activeConvId] = useState<string | null>(null);
  // Key to force remount ChatWithHistory when agent changes
  const [chatKey, setChatKey] = useState(0);

  const { data: agents = [] } = useQuery<AgentListItem[]>({
    queryKey: ["agents", "list"],
    queryFn: () => api.get<AgentListItem[]>("/api/v1/agents/list"),
    staleTime: 60_000,
  });

  const handleAgentSelect = (name: string | null) => {
    setSelectedAgent(name);
    setChatKey((k) => k + 1); // Reset chat when agent changes
  };

  const handleNewMessage = (preview: string, agent: string | undefined) => {
    setConversations((prev) => [
      {
        id: crypto.randomUUID(),
        preview,
        agentName: agent,
        timestamp: new Date(),
      },
      ...prev.slice(0, 19), // Keep last 20
    ]);
  };

  return (
    <div className="flex h-full overflow-hidden bg-background">
      {/* History drawer */}
      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        conversations={conversations}
        activeId={activeConvId}
        onSelect={() => setHistoryOpen(false)}
      />

      {/* Main chat column */}
      <div className="flex flex-col flex-1 overflow-hidden min-w-0">
        {/* Top bar */}
        <header className="flex items-center gap-3 h-14 px-4 border-b bg-card shrink-0">
          <Link
            href="/dashboard"
            aria-label="Back to dashboard"
            className="rounded p-1.5 hover:bg-muted transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>

          <div className="flex-1 min-w-0 flex items-center gap-3">
            <AgentSelector
              agents={agents}
              selected={selectedAgent}
              onSelect={handleAgentSelect}
            />
          </div>

          <button
            onClick={() => setHistoryOpen(true)}
            aria-label="Open conversation history"
            className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted transition-colors"
          >
            <PanelLeft className="h-4 w-4" aria-hidden="true" />
            <span className="hidden sm:inline">History</span>
          </button>
        </header>

        {/* Chat area */}
        <div className="flex-1 overflow-hidden">
          <ChatWithHistory
            key={chatKey}
            agentName={selectedAgent ?? undefined}
            onNewMessage={handleNewMessage}
          />
        </div>
      </div>
    </div>
  );
}
