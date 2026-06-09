"use client";

import { useQuery } from "@tanstack/react-query";
import {
  chatApi,
  type ChatMode,
  type WelcomePromptsResponse,
} from "@/lib/chat-api";
import { useAuthStore } from "@/stores/auth-store";

const FALLBACK: WelcomePromptsResponse = {
  mode: "auto",
  prompts: [
    {
      text: "What is RAG and how does it work?",
      icon: "🔍",
      kind: "tutor",
      rationale: "fallback",
    },
    {
      text: "Review my Python code for production readiness",
      icon: "🐍",
      kind: "code",
      rationale: "fallback",
    },
    {
      text: "Quiz me on async/await fundamentals",
      icon: "⚡",
      kind: "quiz",
      rationale: "fallback",
    },
    {
      text: "Help me build my AI engineering portfolio",
      icon: "🚀",
      kind: "career",
      rationale: "fallback",
    },
  ],
};

export function useWelcomePrompts(mode: ChatMode) {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  const q = useQuery<WelcomePromptsResponse>({
    queryKey: ["chat", "welcome-prompts", mode],
    queryFn: () => chatApi.welcomePrompts(mode),
    enabled: isAuthed,
    staleTime: 5 * 60_000,
  });
  return {
    ...q,
    data: q.data ?? FALLBACK,
  };
}
