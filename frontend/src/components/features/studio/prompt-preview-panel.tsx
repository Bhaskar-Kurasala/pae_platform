"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { MarkdownRenderer } from "@/components/features/markdown-renderer";

interface PromptPreviewPanelProps {
  code: string;
}

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

export function PromptPreviewPanel({ code }: PromptPreviewPanelProps) {
  const [preview, setPreview] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runPreview = async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const token = getToken();
      const resp = await fetch("/api/v1/agents/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message: code,
          agent: "student_buddy",
        }),
      });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const data = (await resp.json()) as { response?: string };
      setPreview(data.response ?? "No response from agent.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error generating preview.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full flex-col gap-2 p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Prompt Preview
        </span>
        <button
          type="button"
          onClick={() => void runPreview()}
          disabled={loading}
          aria-label={loading ? "Generating preview" : "Run prompt preview"}
          className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? (
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
          ) : (
            "Run Preview"
          )}
        </button>
      </div>
      {error && (
        <p className="rounded border border-destructive/30 bg-destructive/10 px-2 py-1 text-xs text-destructive">
          {error}
        </p>
      )}
      {preview ? (
        <div className="flex-1 overflow-auto rounded border border-border p-2 text-sm">
          <MarkdownRenderer content={preview} />
        </div>
      ) : (
        !error && (
          <p className="text-xs text-muted-foreground">
            Click &ldquo;Run Preview&rdquo; to test your prompt against the student buddy agent.
          </p>
        )
      )}
    </div>
  );
}
