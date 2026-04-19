"use client";

import { useCallback, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("auth-storage");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { state?: { token?: string } };
    return parsed.state?.token ?? null;
  } catch {
    return null;
  }
}

export interface StreamMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  agentName?: string;
  isThinking?: boolean;
  timestamp: Date;
}

interface UseStreamOptions {
  agentName?: string;
  initialContext?: Record<string, unknown>;
  /**
   * Called on every sendMessage; lets callers attach up-to-date data
   * (e.g. the Studio's current code). Merged over initialContext.
   */
  contextProvider?: () => Record<string, unknown> | undefined;
}

interface UseStreamReturn {
  messages: StreamMessage[];
  isStreaming: boolean;
  error: string | null;
  sendMessage: (text: string) => Promise<void>;
  retry: () => Promise<void>;
  clearMessages: () => void;
}

export function useStream(options: UseStreamOptions = {}): UseStreamReturn {
  const { agentName, initialContext, contextProvider } = options;
  const contextProviderRef = useRef(contextProvider);
  contextProviderRef.current = contextProvider;
  const [messages, setMessages] = useState<StreamMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const lastUserMessageRef = useRef<string | null>(null);

  const sendMessage = useCallback(
    async (text: string): Promise<void> => {
      if (isStreaming) return;

      const token = getToken();
      setError(null);

      // Add user message immediately
      const userMessage: StreamMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: text,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMessage]);
      lastUserMessageRef.current = text;

      // Placeholder assistant message — shown as typing indicator until first token
      const assistantId = crypto.randomUUID();
      const assistantMessage: StreamMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        agentName: agentName,
        isThinking: true,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
      setIsStreaming(true);

      abortControllerRef.current = new AbortController();

      try {
        const res = await fetch(`${API_BASE}/api/v1/agents/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            message: text,
            agent_name: agentName ?? null,
            context: {
              ...(initialContext ?? {}),
              ...(contextProviderRef.current?.() ?? {}),
            },
          }),
          signal: abortControllerRef.current.signal,
        });

        if (!res.ok) {
          const detail = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(
            (detail as { detail?: string }).detail ?? `HTTP ${res.status}`,
          );
        }

        const reader = res.body?.getReader();
        if (!reader) throw new Error("No response body");

        const decoder = new TextDecoder();
        let buffer = "";
        let detectedAgentName: string | undefined = agentName;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // SSE format: each event is separated by double newline
          // Lines are "data: <json>\n"
          const lines = buffer.split("\n");
          // Keep the last incomplete line in buffer
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith("data: ")) continue;
            const jsonStr = trimmed.slice(6); // Remove "data: " prefix
            if (jsonStr === "[DONE]") continue;

            try {
              const parsed = JSON.parse(jsonStr) as {
                chunk?: string;
                done?: boolean;
                agent_name?: string;
                error?: string;
              };

              if (parsed.error) {
                throw new Error(parsed.error);
              }

              if (parsed.agent_name) {
                detectedAgentName = parsed.agent_name;
              }

              if (parsed.chunk !== undefined && parsed.chunk !== "") {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantId
                      ? {
                          ...msg,
                          content: msg.content + parsed.chunk,
                          agentName: detectedAgentName,
                          isThinking: false,
                        }
                      : msg,
                  ),
                );
              } else if (parsed.agent_name) {
                // Agent name arrived before first token — update without clearing thinking
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantId ? { ...msg, agentName: detectedAgentName } : msg,
                  ),
                );
              }

              if (parsed.done === true) {
                // Final agent name update if provided
                if (parsed.agent_name) {
                  setMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === assistantId
                        ? { ...msg, agentName: parsed.agent_name }
                        : msg,
                    ),
                  );
                }
                break;
              }
            } catch (parseErr) {
              // Skip malformed SSE lines — streaming is best-effort
              if (parseErr instanceof Error && parseErr.message !== "Malformed JSON") {
                // Only throw if it's a real error from server, not parse failure
                continue;
              }
            }
          }
        }
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") {
          // User cancelled — that's fine
          return;
        }

        const errorMessage =
          err instanceof Error ? err.message : "Failed to reach the AI agents.";
        setError(errorMessage);

        // DISC-44 — drop the developer-string placeholder so the UI shows a
        // user-friendly "Connection lost — Retry" banner sourced from `error`.
        setMessages((prev) => prev.filter((msg) => msg.id !== assistantId));
      } finally {
        setIsStreaming(false);
        abortControllerRef.current = null;
      }
    },
    [isStreaming, agentName, initialContext],
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
    lastUserMessageRef.current = null;
  }, []);

  const retry = useCallback(async (): Promise<void> => {
    const last = lastUserMessageRef.current;
    if (!last || isStreaming) return;
    // Strip the previously-sent user message so sendMessage doesn't duplicate
    // it — the user's intent is to re-send the same prompt, not double it.
    setMessages((prev) => {
      // Remove the last user message (the one we're about to re-send).
      let removed = false;
      const copy = [...prev].reverse();
      const filtered = copy.filter((m) => {
        if (!removed && m.role === "user" && m.content === last) {
          removed = true;
          return false;
        }
        return true;
      });
      return filtered.reverse();
    });
    await sendMessage(last);
  }, [isStreaming, sendMessage]);

  return { messages, isStreaming, error, sendMessage, retry, clearMessages };
}
