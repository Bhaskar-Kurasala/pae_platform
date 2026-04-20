"use client";

import { useState } from "react";
import { BookmarkPlus, Check, Loader2 } from "lucide-react";
import { chatApi } from "@/lib/chat-api";
import { useStudio } from "./studio-context";

type SaveState = "idle" | "saving" | "saved" | "error";

function firstLine(code: string): string {
  const line = code.split("\n")[0]?.trim() ?? "";
  return line.length > 0 ? line.slice(0, 60) : "Untitled";
}

export function SaveToNotebookButton() {
  const { code, result, hasRunOnce } = useStudio();
  const [saveState, setSaveState] = useState<SaveState>("idle");

  // Only show when there's a successful run result
  if (!hasRunOnce || result === null || result.error) {
    return null;
  }

  async function handleSave() {
    if (saveState === "saving" || saveState === "saved") return;

    const stdout = result?.stdout ?? "";
    const content = `Code:\n\`\`\`python\n${code}\n\`\`\`\n\nOutput:\n\`\`\`\n${stdout}\n\`\`\``;
    const title = `Studio: ${firstLine(code)}`;

    setSaveState("saving");
    try {
      await chatApi.saveToNotebook({
        messageId: "studio",
        conversationId: "studio",
        content,
        title,
        sourceType: "studio",
        topic: "code-practice",
      });
      setSaveState("saved");
      // P3-2 — notify badge system of notebook save
      window.dispatchEvent(new CustomEvent("studio:notebook-saved"));
      // Reset to idle after 2 s
      setTimeout(() => setSaveState("idle"), 2000);
    } catch {
      setSaveState("error");
      setTimeout(() => setSaveState("idle"), 2000);
    }
  }

  const isSaved = saveState === "saved";
  const isError = saveState === "error";

  return (
    <button
      type="button"
      onClick={() => { void handleSave(); }}
      disabled={saveState === "saving" || isSaved}
      aria-label="Save code and output to notebook"
      title="Save code and output as a notebook entry"
      className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium transition pointer-coarse:h-11 pointer-coarse:min-w-11 pointer-coarse:px-3 pointer-coarse:text-sm ${
        isSaved
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          : isError
            ? "border-destructive/40 bg-destructive/10 text-destructive"
            : "border-border bg-background text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
      }`}
    >
      {saveState === "saving" ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
      ) : isSaved ? (
        <Check className="h-3.5 w-3.5" aria-hidden="true" />
      ) : (
        <BookmarkPlus className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      <span>
        {saveState === "saving"
          ? "Saving…"
          : isSaved
            ? "Saved!"
            : isError
              ? "Failed"
              : "Save to Notebook"}
      </span>
    </button>
  );
}
