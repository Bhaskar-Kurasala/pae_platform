"use client";

import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

export interface SendMessageArgs {
  message: string;
  agentName?: string;
  conversationId?: string;
  context?: Record<string, unknown>;
}

export interface ChatApiResponse {
  response: string;
  agent_name: string;
  evaluation_score: number;
  conversation_id: string;
}

export function useAgentChat() {
  return useMutation({
    mutationFn: (args: SendMessageArgs) =>
      api.post<ChatApiResponse>("/api/v1/agents/chat", {
        message: args.message,
        agent_name: args.agentName ?? null,
        conversation_id: args.conversationId ?? null,
        context: args.context ?? null,
      }),
  });
}
