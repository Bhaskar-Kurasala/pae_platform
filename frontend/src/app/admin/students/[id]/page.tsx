"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  Clock,
  FileCode2,
  LogIn,
  NotebookPen,
  Play,
  Sparkles,
} from "lucide-react";
import {
  useAdminStudents,
  useCreateStudentNote,
  useStudentNotes,
  useStudentTimeline,
  useTriggerAgent,
} from "@/lib/hooks/use-admin";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

// DISC-55 — student drilldown with merged timeline + admin agent-trigger (DISC-57).
// The admin lands here from /admin/students row click or from the Top Students
// table on the overview page.

const TRIGGERABLE_AGENTS = [
  { name: "disrupt_prevention", label: "Re-engage (disrupt_prevention)" },
  { name: "progress_report", label: "Weekly progress report" },
  { name: "adaptive_path", label: "Suggest learning path" },
  { name: "community_celebrator", label: "Celebrate milestone" },
] as const;

function TimelineIcon({ kind }: { kind: string }) {
  const base = "h-4 w-4 shrink-0";
  switch (kind) {
    case "login":
      return <LogIn className={base} aria-hidden="true" />;
    case "lesson_completed":
      return <CheckCircle2 className={base} aria-hidden="true" />;
    case "submission":
      return <FileCode2 className={base} aria-hidden="true" />;
    default:
      return <Bot className={base} aria-hidden="true" />;
  }
}

export default function StudentDrilldownPage() {
  const params = useParams<{ id: string }>();
  const studentId = params?.id ?? null;

  const { data: students } = useAdminStudents();
  const student = useMemo(
    () => students?.find((s) => s.id === studentId) ?? null,
    [students, studentId],
  );

  const { data: timeline = [], isLoading: timelineLoading } = useStudentTimeline(studentId);
  const { data: notes = [], isLoading: notesLoading } = useStudentNotes(studentId);
  const createNote = useCreateStudentNote(studentId);
  const trigger = useTriggerAgent();

  const [selectedAgent, setSelectedAgent] = useState<string>(TRIGGERABLE_AGENTS[0].name);
  const [triggerResult, setTriggerResult] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState<string>("");

  async function handleAddNote() {
    const trimmed = noteDraft.trim();
    if (!trimmed || !studentId) return;
    try {
      await createNote.mutateAsync(trimmed);
      setNoteDraft("");
    } catch {
      // The global mutation onError toast (PR2/B1.1) shows the failure;
      // we just keep the draft in the textarea so the operator can retry.
    }
  }

  async function handleTrigger() {
    if (!studentId) return;
    setTriggerResult(null);
    try {
      const res = await trigger.mutateAsync({ agentName: selectedAgent, studentId });
      setTriggerResult(`✓ ${res.agent_name} · ${res.duration_ms}ms — ${res.response_preview || "(no response)"}`);
    } catch (err) {
      setTriggerResult(`✗ ${(err as Error).message}`);
    }
  }

  return (
    <div className="p-6 md:p-8 max-w-5xl mx-auto space-y-6">
      <Link
        href="/admin/students"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        Back to students
      </Link>

      <div>
        <h1 className="text-2xl font-bold">
          {student?.full_name ?? "Student"}
        </h1>
        <p className="text-muted-foreground text-sm">
          {student?.email ?? studentId}
        </p>
        {student && (
          <div className="flex flex-wrap gap-2 mt-3 text-xs text-muted-foreground">
            <Badge className={student.is_active ? "bg-green-100 text-green-700 hover:bg-green-100" : "bg-muted"}>
              {student.is_active ? "Active" : "Inactive"}
            </Badge>
            <span>{student.lessons_completed} lessons completed</span>
            <span>·</span>
            <span>{student.agent_interactions} agent interactions</span>
            <span>·</span>
            <span>Joined {new Date(student.created_at).toLocaleDateString()}</span>
          </div>
        )}
      </div>

      {/* DISC-57 — admin agent trigger panel */}
      <Card>
        <CardHeader className="pb-2">
          <h2 className="font-semibold text-sm flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
            Trigger agent
          </h2>
          <p className="text-xs text-muted-foreground">
            Runs on behalf of this student. Logged with your admin identity in the audit log.
          </p>
        </CardHeader>
        <CardContent className="flex flex-col md:flex-row gap-3">
          <select
            aria-label="Agent to trigger"
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="h-9 rounded-lg border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-primary/50"
          >
            {TRIGGERABLE_AGENTS.map((a) => (
              <option key={a.name} value={a.name}>{a.label}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void handleTrigger()}
            disabled={trigger.isPending || !studentId}
            className="inline-flex items-center gap-1.5 h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            <Play className="h-3.5 w-3.5" aria-hidden="true" />
            {trigger.isPending ? "Running…" : "Run"}
          </button>
          {triggerResult && (
            <p className="text-xs text-muted-foreground self-center break-words max-w-xl">
              {triggerResult}
            </p>
          )}
        </CardContent>
      </Card>

      {/* F2 — Admin notes per student.
          Append-only, plain text. The first thing an operator types
          here is usually "called Mon, said busy this week" — that
          context survives across rotations and reminders.
          The backend route (POST /admin/students/{id}/notes) was
          already shipped in Phase 3; F2 wires the UI. */}
      <Card>
        <CardHeader className="pb-2">
          <h2 className="font-semibold text-sm flex items-center gap-2">
            <NotebookPen className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            Admin notes
          </h2>
          <p className="text-xs text-muted-foreground">
            Private. Used to remember what was said to whom across rotations.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <textarea
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              placeholder="e.g. Called Mon — said busy this week, will follow up Fri."
              maxLength={2000}
              rows={3}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              aria-label="New admin note"
              disabled={createNote.isPending}
            />
            <div className="mt-2 flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">
                {noteDraft.length}/2000
              </span>
              <button
                type="button"
                onClick={() => void handleAddNote()}
                disabled={!noteDraft.trim() || createNote.isPending || !studentId}
                className="rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
              >
                {createNote.isPending ? "Saving…" : "Add note"}
              </button>
            </div>
          </div>

          {notesLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="h-12 animate-pulse rounded bg-muted" />
              ))}
            </div>
          ) : notes.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              No notes yet. The first one is usually the most useful.
            </p>
          ) : (
            <ol className="space-y-2">
              {notes.map((n) => (
                <li
                  key={n.id}
                  className="rounded-lg border border-border bg-background/50 px-3 py-2"
                >
                  <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                    {n.body_md}
                  </pre>
                  <p className="mt-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                    {new Date(n.created_at).toLocaleString()}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      {/* DISC-55 — merged activity timeline */}
      <Card>
        <CardHeader className="pb-2">
          <h2 className="font-semibold text-sm flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            Activity timeline
          </h2>
          <p className="text-xs text-muted-foreground">
            Lessons, submissions, agent runs, and last login — newest first.
          </p>
        </CardHeader>
        <CardContent>
          {timelineLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-10 animate-pulse rounded bg-muted" />
              ))}
            </div>
          ) : timeline.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-6">
              No activity yet.
            </p>
          ) : (
            <ol className="space-y-2.5">
              {timeline.map((ev, i) => (
                <li key={`${ev.kind}-${ev.at}-${i}`} className="flex items-start gap-3 text-sm">
                  <span className="mt-0.5 text-muted-foreground">
                    <TimelineIcon kind={ev.kind} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm leading-tight">{ev.summary}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {new Date(ev.at).toLocaleString()}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
