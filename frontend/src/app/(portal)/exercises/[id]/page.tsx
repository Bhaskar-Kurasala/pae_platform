"use client";

import { use, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, Send, Star } from "lucide-react";
import { exercisesApi } from "@/lib/api-client";
import { ApiError } from "@/lib/api-client";
import { PeerGallery } from "@/components/features/peer-gallery";

export default function ExerciseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [code, setCode] = useState(
    `# Write your solution here\n\n`,
  );
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ score?: number; feedback?: string } | null>(null);
  const [error, setError] = useState("");
  const [share, setShare] = useState(false);
  const [shareNote, setShareNote] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const sub = await exercisesApi.submit(id, {
        code,
        shared_with_peers: share,
        share_note: share ? shareNote.trim() || undefined : undefined,
      });
      setResult({ score: sub.score ?? undefined, feedback: sub.feedback ?? undefined });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Submission failed. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="p-6 md:p-8 max-w-3xl mx-auto space-y-6">
      <Link
        href="/exercises"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back to exercises
      </Link>

      <div>
        <h1 className="text-2xl font-bold">Exercise</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Submit your solution below. The AI Code Review agent will evaluate and score it.
        </p>
      </div>

      {/* Instructions */}
      <div className="rounded-xl border bg-card p-5">
        <h2 className="font-semibold mb-2">Instructions</h2>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Complete the coding task as described in your course lesson. Your submission will be
          reviewed by our AI Code Review agent, which evaluates correctness, style, and production
          readiness. You can submit multiple times — only the best score counts.
        </p>
      </div>

      {/* Code editor */}
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="code-editor" className="block text-sm font-medium mb-2">
            Your solution
          </label>
          <textarea
            id="code-editor"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            rows={18}
            spellCheck={false}
            className="w-full rounded-xl border bg-[#111827] text-green-300 font-mono text-sm p-4 outline-none focus:ring-2 focus:ring-primary/50 resize-y"
            aria-label="Code editor"
          />
        </div>

        <div className="rounded-lg border border-foreground/10 bg-card p-3">
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={share}
              onChange={(e) => setShare(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-foreground/20"
              aria-label="Share this submission with peers"
            />
            <span>
              <span className="font-medium">Share with peers (anonymous)</span>
              <span className="block text-xs text-muted-foreground">
                Others see your code under a handle like{" "}
                <code className="font-mono">peer_3fa7</code> — no name or email.
              </span>
            </span>
          </label>
          {share ? (
            <input
              type="text"
              value={shareNote}
              onChange={(e) => setShareNote(e.target.value)}
              placeholder="Optional — what should peers notice about your approach?"
              maxLength={500}
              className="mt-2 w-full rounded-md border border-foreground/10 bg-background px-3 py-1.5 text-sm"
              aria-label="Share note"
            />
          ) : null}
        </div>

        {error && (
          <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center gap-2 h-10 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60 transition-colors"
        >
          {submitting ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Send className="h-4 w-4" aria-hidden="true" />
          )}
          {submitting ? "Submitting…" : "Submit for review"}
        </button>
      </form>

      {/* Graded result */}
      {result && (
        <div className="rounded-xl border bg-card p-5 space-y-3">
          <div className="flex items-center gap-2">
            <Star className="h-5 w-5 text-yellow-500" aria-hidden="true" />
            <h2 className="font-semibold">Submission received</h2>
          </div>
          {result.score !== undefined && (
            <p className="text-sm">
              Score:{" "}
              <span className="font-bold text-primary">{result.score} pts</span>
            </p>
          )}
          {result.feedback && (
            <div>
              <p className="text-sm font-medium mb-1">AI Feedback</p>
              <p className="text-sm text-muted-foreground leading-relaxed">{result.feedback}</p>
            </div>
          )}
          {!result.score && !result.feedback && (
            <p className="text-sm text-muted-foreground">
              Your submission is queued for AI review. Check back shortly.
            </p>
          )}
        </div>
      )}

      <PeerGallery exerciseId={id} />
    </div>
  );
}
