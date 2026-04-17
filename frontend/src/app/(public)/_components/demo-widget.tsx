"use client";

import { Brain } from "lucide-react";

const USER_MESSAGE = "How does RAG actually work?";

const AGENT_REPLY =
  "RAG — Retrieval-Augmented Generation — works by first converting your query into a vector embedding, then searching a vector database (like Pinecone) for the most semantically similar document chunks. Those retrieved chunks are injected into the prompt as context, so the language model generates an answer grounded in your actual data rather than its training weights alone.";

/**
 * Static chat-like demo widget showing a sample Socratic Tutor exchange.
 * No API call — purely presentational. Uses a CSS blink animation to
 * simulate a streaming cursor on the agent reply.
 */
export function DemoWidget() {
  return (
    <div className="rounded-2xl border border-border bg-card shadow-sm overflow-hidden">
      {/* Agent identity bar */}
      <div className="flex items-center gap-3 border-b border-border px-5 py-3 bg-muted/30">
        <span
          className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 shrink-0"
          aria-hidden="true"
        >
          <Brain className="h-4 w-4 text-primary" aria-hidden="true" />
        </span>
        <div>
          <div className="text-sm font-semibold text-foreground">Socratic Tutor</div>
          <div className="text-xs text-muted-foreground">Guides understanding through questions</div>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-primary animate-pulse" aria-hidden="true" />
          <span className="text-xs text-muted-foreground">Live</span>
        </div>
      </div>

      {/* Messages */}
      <div className="p-5 space-y-5" role="log" aria-label="Demo conversation">
        {/* User message */}
        <div className="flex justify-end">
          <div
            className="max-w-xs rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5"
            role="article"
            aria-label="Student message"
          >
            <p className="text-sm text-primary-foreground">{USER_MESSAGE}</p>
          </div>
        </div>

        {/* Agent message */}
        <div className="flex items-start gap-3">
          <span
            className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 shrink-0 mt-0.5"
            aria-hidden="true"
          >
            <Brain className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          </span>
          <div
            className="flex-1 rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5"
            role="article"
            aria-label="Agent response"
          >
            <p className="text-sm text-foreground leading-relaxed">
              {AGENT_REPLY}
              {/* Streaming cursor */}
              <span
                aria-hidden="true"
                className="inline-block w-0.5 h-3.5 bg-primary ml-0.5 align-middle animate-[blink_1s_step-end_infinite]"
              />
            </p>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="border-t border-border px-5 py-3 flex items-center justify-between bg-muted/20">
        <span className="text-xs text-muted-foreground">
          Powered by <span className="text-foreground font-medium">claude-sonnet-4-6</span>
        </span>
        <span className="text-xs text-muted-foreground">Sample response · not a live call</span>
      </div>

      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
      `}</style>
    </div>
  );
}
