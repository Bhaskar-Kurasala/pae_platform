"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Award,
  Clock,
  Gauge,
  Loader2,
  Send,
  Square,
  Target,
} from "lucide-react";
import {
  API_BASE,
  interviewApi,
  type InterviewDebrief,
  type InterviewProblemSummary,
  type InterviewStartResponse,
} from "@/lib/api-client";

interface Turn {
  id: string;
  role: "user" | "interviewer";
  content: string;
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

function formatElapsed(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function VerdictBadge({ verdict }: { verdict: InterviewDebrief["overall_verdict"] }) {
  const map: Record<InterviewDebrief["overall_verdict"], { label: string; tone: string }> = {
    strong_hire: { label: "Strong hire", tone: "bg-emerald-500/15 text-emerald-500" },
    lean_hire: { label: "Lean hire", tone: "bg-sky-500/15 text-sky-500" },
    on_the_fence: { label: "On the fence", tone: "bg-amber-500/15 text-amber-500" },
    no_hire: { label: "No hire (yet)", tone: "bg-rose-500/15 text-rose-500" },
  };
  const meta = map[verdict];
  return (
    <span className={`rounded px-2 py-1 text-xs font-semibold ${meta.tone}`}>
      {meta.label}
    </span>
  );
}

export default function InterviewPage() {
  const [problems, setProblems] = useState<InterviewProblemSummary[]>([]);
  const [pickedSlug, setPickedSlug] = useState<string | undefined>(undefined);
  const [starting, setStarting] = useState(false);
  const [session, setSession] = useState<InterviewStartResponse | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [debriefing, setDebriefing] = useState(false);
  const [debrief, setDebrief] = useState<InterviewDebrief | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    interviewApi
      .problems()
      .then((p) => {
        if (!cancelled) setProblems(p);
      })
      .catch(() => {
        /* non-fatal; auto-pick will still work */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!session) return;
    const start = new Date(session.started_at).getTime();
    const id = setInterval(() => setElapsedMs(Date.now() - start), 1000);
    return () => clearInterval(id);
  }, [session]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, streaming]);

  const handleStart = useCallback(async () => {
    setStarting(true);
    setError(null);
    try {
      const res = await interviewApi.start(pickedSlug);
      setSession(res);
      setTurns([{ id: crypto.randomUUID(), role: "interviewer", content: res.prompt }]);
      setDebrief(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't start interview");
    } finally {
      setStarting(false);
    }
  }, [pickedSlug]);

  const handleSend = useCallback(async () => {
    if (!session || !draft.trim() || streaming) return;
    const userTurn: Turn = { id: crypto.randomUUID(), role: "user", content: draft.trim() };
    const assistantId = crypto.randomUUID();
    setTurns((t) => [
      ...t,
      userTurn,
      { id: assistantId, role: "interviewer", content: "" },
    ]);
    const message = draft.trim();
    setDraft("");
    setStreaming(true);
    setError(null);

    abortRef.current = new AbortController();
    try {
      const token = getToken();
      const res = await fetch(`${API_BASE}/api/v1/interview/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ session_id: session.session_id, message }),
        signal: abortRef.current.signal,
      });

      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          const t = line.trim();
          if (!t.startsWith("data: ")) continue;
          try {
            const parsed = JSON.parse(t.slice(6)) as {
              chunk?: string;
              done?: boolean;
              error?: string;
            };
            if (parsed.error) throw new Error(parsed.error);
            if (parsed.chunk) {
              setTurns((prev) =>
                prev.map((turn) =>
                  turn.id === assistantId
                    ? { ...turn, content: turn.content + parsed.chunk }
                    : turn,
                ),
              );
            }
            if (parsed.done) break;
          } catch {
            /* skip malformed */
          }
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "Stream failed");
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [draft, session, streaming]);

  const handleEnd = useCallback(async () => {
    if (!session) return;
    setDebriefing(true);
    setError(null);
    try {
      const d = await interviewApi.debrief(session.session_id);
      setDebrief(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Debrief failed");
    } finally {
      setDebriefing(false);
    }
  }, [session]);

  const handleReset = useCallback(() => {
    setSession(null);
    setTurns([]);
    setDebrief(null);
    setElapsedMs(0);
    setError(null);
  }, []);

  const canEnd = useMemo(
    () => session !== null && turns.some((t) => t.role === "user") && !streaming,
    [session, turns, streaming],
  );

  // ── Pre-session: problem picker ──
  if (!session) {
    return (
      <div className="mx-auto max-w-3xl p-6 md:p-8 space-y-6">
        <div>
          <h1 className="text-2xl font-bold">Mock interview</h1>
          <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
            FAANG-style AI engineering interview with a senior interviewer persona. No hints,
            no hand-holding. You&apos;ll get a structured debrief at the end with specific
            observations — not a vanity score.
          </p>
        </div>

        <div className="rounded-xl border bg-card p-5 space-y-4">
          <div>
            <label className="text-sm font-medium">Pick a problem (or leave to auto-pick)</label>
            <div className="mt-2 grid gap-2">
              <button
                type="button"
                onClick={() => setPickedSlug(undefined)}
                className={`rounded-lg border px-3 py-2 text-left text-sm transition ${
                  !pickedSlug
                    ? "border-primary bg-primary/5"
                    : "border-border hover:bg-muted/50"
                }`}
              >
                <span className="font-medium">Auto-pick</span>
                <span className="block text-xs text-muted-foreground">
                  Rotates through the bank so you see a new problem each session.
                </span>
              </button>
              {problems.map((p) => (
                <button
                  key={p.slug}
                  type="button"
                  onClick={() => setPickedSlug(p.slug)}
                  className={`rounded-lg border px-3 py-2 text-left text-sm transition ${
                    pickedSlug === p.slug
                      ? "border-primary bg-primary/5"
                      : "border-border hover:bg-muted/50"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{p.title}</span>
                    <span className="rounded bg-foreground/5 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                      {p.category}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}

          <button
            type="button"
            onClick={handleStart}
            disabled={starting}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-60"
          >
            {starting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Target className="h-4 w-4" aria-hidden="true" />
            )}
            {starting ? "Starting…" : "Start interview"}
          </button>
        </div>
      </div>
    );
  }

  // ── Post-interview: debrief view ──
  if (debrief) {
    const axisEntries = Object.entries(debrief.axes) as [
      keyof InterviewDebrief["axes"],
      { score: number; observation: string },
    ][];

    return (
      <div className="mx-auto max-w-3xl p-6 md:p-8 space-y-6">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-2xl font-bold">Debrief</h1>
          <VerdictBadge verdict={debrief.overall_verdict} />
        </div>

        <div className="rounded-xl border bg-card p-5">
          <p className="text-sm leading-relaxed">{debrief.headline}</p>
        </div>

        <div className="rounded-xl border bg-card p-5 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Gauge className="h-4 w-4 text-primary" aria-hidden="true" />
            Axes
          </div>
          <ul className="space-y-3">
            {axisEntries.map(([axis, data]) => (
              <li key={axis} className="rounded-lg border border-border/60 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium capitalize">
                    {axis.replace(/_/g, " ")}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {data.score}/5
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground leading-snug">
                  {data.observation}
                </p>
              </li>
            ))}
          </ul>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border bg-card p-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Award className="h-4 w-4 text-emerald-500" aria-hidden="true" />
              Strongest moment
            </div>
            <p className="mt-1.5 text-xs leading-relaxed">{debrief.strongest_moment}</p>
          </div>
          <div className="rounded-xl border bg-card p-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Target className="h-4 w-4 text-amber-500" aria-hidden="true" />
              Biggest gap
            </div>
            <p className="mt-1.5 text-xs leading-relaxed">{debrief.biggest_gap}</p>
          </div>
        </div>

        <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
          <div className="text-sm font-semibold text-primary">Next focus</div>
          <p className="mt-1 text-sm leading-relaxed">{debrief.next_focus}</p>
        </div>

        <button
          type="button"
          onClick={handleReset}
          className="rounded-lg border px-4 py-2 text-sm font-medium transition hover:bg-muted"
        >
          Start another
        </button>
      </div>
    );
  }

  // ── Active interview: chat UI ──
  return (
    <div className="mx-auto max-w-3xl p-4 md:p-6 h-[calc(100vh-4rem)] flex flex-col gap-4">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold">{session.problem.title}</h1>
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
            {session.problem.category}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 font-mono text-xs tabular-nums">
            <Clock className="h-3 w-3" aria-hidden="true" />
            {formatElapsed(elapsedMs)}
          </span>
          <button
            type="button"
            onClick={handleEnd}
            disabled={!canEnd || debriefing}
            aria-label="End interview and get debrief"
            className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
          >
            {debriefing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Square className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            End & debrief
          </button>
        </div>
      </header>

      <div
        ref={scrollRef}
        className="flex-1 overflow-auto rounded-xl border bg-card p-4 space-y-3"
      >
        {turns.map((t) => (
          <div
            key={t.id}
            className={`flex ${t.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap ${
                t.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-foreground"
              }`}
            >
              {t.content || (streaming && t.role === "interviewer" ? "…" : "")}
            </div>
          </div>
        ))}
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void handleSend();
        }}
        className="flex items-end gap-2"
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void handleSend();
            }
          }}
          rows={3}
          placeholder="Your answer… (⌘/Ctrl+Enter to send)"
          className="flex-1 resize-y rounded-lg border border-border bg-background p-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
          disabled={streaming}
          aria-label="Your answer"
        />
        <button
          type="submit"
          disabled={streaming || !draft.trim()}
          className="inline-flex h-10 items-center gap-1 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
        >
          {streaming ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Send className="h-4 w-4" aria-hidden="true" />
          )}
          Send
        </button>
      </form>
    </div>
  );
}
