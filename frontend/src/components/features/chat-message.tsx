import { Bot, User } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  agentName?: string;
  evaluationScore?: number;
  timestamp: Date;
}

const AGENT_LABELS: Record<string, string> = {
  socratic_tutor: "Socratic Tutor",
  code_review: "Code Review",
  adaptive_quiz: "Adaptive Quiz",
  system: "System",
};

interface ChatMessageProps {
  message: ChatMessage;
}

export function ChatMessageBubble({ message }: ChatMessageProps) {
  const isUser = message.role === "user";
  const agentLabel = message.agentName ? (AGENT_LABELS[message.agentName] ?? message.agentName) : "AI Tutor";

  return (
    <div
      className={cn(
        "flex gap-3 items-start max-w-3xl",
        isUser ? "ml-auto flex-row-reverse" : "mr-auto",
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "shrink-0 h-8 w-8 rounded-full flex items-center justify-center text-white",
          isUser ? "bg-primary" : "bg-[#7C3AED]",
        )}
        aria-hidden="true"
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      {/* Bubble */}
      <div className="space-y-1">
        {!isUser && (
          <p className="text-xs text-muted-foreground font-medium pl-1">{agentLabel}</p>
        )}
        <div
          className={cn(
            "rounded-2xl px-4 py-3 text-sm leading-relaxed max-w-[42rem]",
            isUser
              ? "bg-primary text-primary-foreground rounded-tr-sm"
              : "bg-card border rounded-tl-sm",
          )}
        >
          <pre className="whitespace-pre-wrap font-sans break-words">{message.content}</pre>
        </div>
        <div className={cn("flex items-center gap-2 text-xs text-muted-foreground px-1", isUser && "flex-row-reverse")}>
          <span>{message.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
          {!isUser && message.evaluationScore !== undefined && (
            <span className="text-primary font-medium">
              Quality: {Math.round(message.evaluationScore * 100)}%
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
