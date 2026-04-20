"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Bot, Code2, Lock, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { useStream } from "@/hooks/use-stream";
import { MarkdownRenderer } from "@/components/features/markdown-renderer";
import { useMyPreferences } from "@/lib/hooks/use-preferences";
import { useStudio } from "./studio-context";

function UglyDraftLockout() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 py-8 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-500/10 text-amber-600 dark:text-amber-400">
        <Lock className="h-5 w-5" aria-hidden="true" />
      </div>
      <div className="max-w-xs">
        <p className="text-sm font-semibold">Ugly draft mode is on</p>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          Write your first attempt in the editor and hit{" "}
          <span className="font-medium text-foreground">Run</span> — it&apos;s
          fine if it&apos;s wrong, broken, or embarrassing. The tutor unlocks
          after your first run.
        </p>
        <p className="mt-3 text-[11px] uppercase tracking-wider text-muted-foreground/70">
          Productive struggle beats premature help
        </p>
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

const SUGGESTED = [
  "What's wrong with this code?",
  "Add type hints to the main function.",
  "Explain this line-by-line.",
  "How would you refactor this?",
];

// #40 — parse line references from tutor messages (e.g. "line 5:")
const LINE_REF_PATTERN = /line (\d+):/gi;

export function StudioChat() {
  const { code, hasRunOnce, exerciseTitle, addTutorPin } = useStudio();
  const { data: prefs } = useMyPreferences();
  const codeRef = useRef(code);
  codeRef.current = code;
  const exerciseTitleRef = useRef(exerciseTitle);
  exerciseTitleRef.current = exerciseTitle;

  const locked = prefs?.ugly_draft_mode === true && !hasRunOnce;

  // #50 — inject exercise context into every chat message
  const buildMessageWithContext = useCallback(
    (userMessage: string): string => {
      const title = exerciseTitleRef.current;
      const snippet = codeRef.current.slice(0, 500);
      if (!title) {
        // No exercise — still include code
        return `[Current code:\n\`\`\`python\n${snippet}\n\`\`\`]\n\nStudent question: ${userMessage}`;
      }
      return `[Context: Exercise "${title}". Current code:\n\`\`\`python\n${snippet}\n\`\`\`]\n\nStudent question: ${userMessage}`;
    },
    [],
  );

  const { messages, isStreaming, sendMessage } = useStream({
    agentName: "studio_tutor",
    contextProvider: () => ({ code: codeRef.current }),
  });

  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // P1-4 — listen for studio:ask custom events from ExecutionTrace "Why did this break?" button
  useEffect(() => {
    function handleStudioAsk(event: Event) {
      const e = event as CustomEvent<{ question: string }>;
      const question = e.detail?.question;
      if (!question || isStreaming) return;
      const contextualMessage = buildMessageWithContext(question);
      void sendMessage(contextualMessage);
    }
    window.addEventListener("studio:ask", handleStudioAsk);
    return () => {
      window.removeEventListener("studio:ask", handleStudioAsk);
    };
  }, [isStreaming, sendMessage, buildMessageWithContext]);

  // #40 — after a message is sent, parse tutor response for line pins
  const prevMessagesLength = useRef(messages.length);
  useEffect(() => {
    if (messages.length <= prevMessagesLength.current) {
      prevMessagesLength.current = messages.length;
      return;
    }
    prevMessagesLength.current = messages.length;
    const lastMsg = messages[messages.length - 1];
    if (!lastMsg || lastMsg.role !== "assistant") return;
    // Parse "line N:" patterns and add pins
    let match;
    LINE_REF_PATTERN.lastIndex = 0;
    while ((match = LINE_REF_PATTERN.exec(lastMsg.content)) !== null) {
      const lineNum = parseInt(match[1], 10);
      if (!isNaN(lineNum)) {
        addTutorPin(lineNum, lastMsg.content.slice(0, 120));
      }
    }
  }, [messages, addTutorPin]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    // #50 — inject exercise + code context
    const contextualMessage = buildMessageWithContext(text);
    await sendMessage(contextualMessage);
  }, [input, isStreaming, sendMessage, buildMessageWithContext]);

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void handleSend();
    }
  };

  const empty = messages.length === 0;

  if (locked) {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <UglyDraftLockout />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto" aria-live="polite">
        {empty ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 px-6 py-8 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <Code2 className="h-6 w-6" aria-hidden="true" />
            </div>
            <div>
              <p className="text-sm font-semibold">Ask your Studio tutor</p>
              <p className="mt-1 text-xs text-muted-foreground">
                I can see your editor. Ask about the code you&apos;re writing.
              </p>
            </div>
            <ul className="mt-2 w-full max-w-xs space-y-1.5">
              {SUGGESTED.map((prompt) => (
                <li key={prompt}>
                  <button
                    type="button"
                    onClick={() => setInput(prompt)}
                    className="w-full rounded-lg border border-border/60 bg-card px-3 py-2 text-left text-xs text-muted-foreground hover:border-primary/40 hover:text-foreground"
                  >
                    {prompt}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="space-y-4 px-4 py-4">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  "flex gap-2",
                  msg.role === "user" ? "justify-end" : "justify-start",
                )}
              >
                {msg.role === "assistant" && (
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                    <Bot className="h-3.5 w-3.5" aria-hidden="true" />
                  </div>
                )}
                <div
                  className={cn(
                    "max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed shadow-sm",
                    msg.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : "bg-card border border-border/50",
                  )}
                >
                  {msg.role === "assistant" && msg.isThinking ? (
                    <ThinkingDots />
                  ) : msg.role === "assistant" ? (
                    <MarkdownRenderer
                      content={msg.content}
                      isStreaming={isStreaming}
                    />
                  ) : (
                    msg.content
                  )}
                </div>
                {msg.role === "user" && (
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted">
                    <User className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                  </div>
                )}
              </div>
            ))}
            <div ref={scrollRef} />
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-border bg-card px-3 py-3">
        <div className="rounded-2xl border border-border/60 bg-background focus-within:border-primary/40">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKey}
            rows={2}
            disabled={isStreaming}
            placeholder="Ask about your code… (⌘/Ctrl + Enter)"
            aria-label="Studio tutor message"
            className="w-full resize-none bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted-foreground/50 disabled:opacity-60"
          />
          <div className="flex items-center justify-between px-3 pb-2">
            <span className="text-[10px] text-muted-foreground/60">
              Code auto-attached · {code.length} chars
            </span>
            <button
              type="button"
              onClick={() => void handleSend()}
              disabled={isStreaming || !input.trim()}
              aria-label={isStreaming ? "Generating" : "Send"}
              className={cn(
                "flex h-7 w-7 items-center justify-center rounded-xl bg-primary text-primary-foreground",
                "hover:bg-primary/90 disabled:opacity-40",
              )}
            >
              <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
