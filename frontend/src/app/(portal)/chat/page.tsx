"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, Loader2, Send } from "lucide-react";
import { useAgentChat } from "@/lib/hooks/use-agent-chat";
import { ChatMessageBubble, type ChatMessage } from "@/components/features/chat-message";

const AGENTS = [
  {
    id: "socratic_tutor",
    label: "Socratic Tutor",
    description: "Guides you to answers through questions",
    color: "border-primary bg-primary/5 text-primary",
  },
  {
    id: "code_review",
    label: "Code Review",
    description: "Reviews your code for production readiness",
    color: "border-[#7C3AED] bg-[#7C3AED]/5 text-[#7C3AED]",
  },
  {
    id: "adaptive_quiz",
    label: "Adaptive Quiz",
    description: "Tests your knowledge with adaptive MCQs",
    color: "border-yellow-500 bg-yellow-50 text-yellow-700",
  },
] as const;

type AgentId = (typeof AGENTS)[number]["id"] | null;

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [selectedAgent, setSelectedAgent] = useState<AgentId>(null);
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const endRef = useRef<HTMLDivElement>(null);
  const { mutateAsync: sendMessage, isPending } = useAgentChat();

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || isPending) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");

    try {
      const result = await sendMessage({
        message: text,
        agentName: selectedAgent ?? undefined,
        conversationId,
      });

      setConversationId(result.conversation_id);

      const agentMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: result.response,
        agentName: result.agent_name,
        evaluationScore: result.evaluation_score,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, agentMsg]);
    } catch {
      const errMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "Failed to reach the AI agents. Make sure the backend is running at http://localhost:8000.",
        agentName: "system",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errMsg]);
    }
  }

  return (
    <div className="flex flex-col h-full max-h-screen">
      {/* Header */}
      <div className="px-6 py-4 border-b bg-card shrink-0">
        <h1 className="font-bold text-lg">AI Tutor</h1>
        <p className="text-sm text-muted-foreground">
          {selectedAgent
            ? `Using: ${AGENTS.find((a) => a.id === selectedAgent)?.label}`
            : "Auto-routing to the best agent for your question"}
        </p>
      </div>

      {/* Agent selector */}
      <div className="flex gap-2 px-4 py-3 border-b bg-muted/30 shrink-0 overflow-x-auto">
        <button
          onClick={() => setSelectedAgent(null)}
          className={`shrink-0 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
            selectedAgent === null
              ? "border-foreground bg-foreground text-background"
              : "border-border text-muted-foreground hover:border-foreground"
          }`}
        >
          Auto
        </button>
        {AGENTS.map((agent) => (
          <button
            key={agent.id}
            onClick={() => setSelectedAgent(agent.id)}
            className={`shrink-0 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
              selectedAgent === agent.id
                ? agent.color
                : "border-border text-muted-foreground hover:border-foreground"
            }`}
            title={agent.description}
          >
            {agent.label}
          </button>
        ))}
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center gap-4 py-16">
            <div className="h-14 w-14 rounded-full bg-primary/10 flex items-center justify-center">
              <Bot className="h-7 w-7 text-primary" aria-hidden="true" />
            </div>
            <div>
              <h2 className="font-semibold text-lg">Ask your AI Tutor</h2>
              <p className="text-muted-foreground text-sm mt-1 max-w-sm">
                Ask a concept question, paste code for review, or request a quiz. The right agent will handle it.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 justify-center">
              {["What is RAG?", "Review my code", "Quiz me on LangGraph"].map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => setInput(prompt)}
                  className="rounded-full border px-3 py-1.5 text-sm hover:bg-muted transition-colors"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg) => (
          <ChatMessageBubble key={msg.id} message={msg} />
        ))}
        {isPending && (
          <div className="flex gap-3 items-center text-muted-foreground">
            <div className="h-8 w-8 rounded-full bg-[#7C3AED]/10 flex items-center justify-center">
              <Bot className="h-4 w-4 text-[#7C3AED]" aria-hidden="true" />
            </div>
            <div className="flex items-center gap-2 text-sm">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              AI is thinking…
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleSend}
        className="px-4 py-4 border-t bg-card shrink-0"
      >
        <div className="flex gap-2 max-w-3xl mx-auto">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSend(e);
              }
            }}
            placeholder="Ask a question, paste code, or request a quiz… (Shift+Enter for newline)"
            rows={1}
            aria-label="Message input"
            className="flex-1 resize-none rounded-xl border border-input bg-background px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 transition max-h-36 overflow-y-auto"
          />
          <button
            type="submit"
            disabled={isPending || !input.trim()}
            aria-label="Send message"
            className="h-12 w-12 shrink-0 rounded-xl bg-primary flex items-center justify-center text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {isPending ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Send className="h-5 w-5" />
            )}
          </button>
        </div>
        <p className="text-center text-xs text-muted-foreground mt-2">
          Powered by Claude {selectedAgent ? `→ ${selectedAgent}` : "via MOA auto-routing"}
        </p>
      </form>
    </div>
  );
}
