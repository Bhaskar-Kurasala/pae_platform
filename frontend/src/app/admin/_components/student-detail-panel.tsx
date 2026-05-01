"use client";

/**
 * <StudentDetailPanel> — the canonical 5-card admin operator surface
 * for a single student. Used in two places:
 *
 *   1. /admin/students/[id]/page.tsx   — the full-page route view
 *      (good for direct links, sharing, bookmarking)
 *   2. <StudentDetailDrawer>           — the side-panel triage view
 *      from the /admin overview (the operator's daily workflow)
 *
 * Same business logic, same five operator cards, same hooks, same
 * tone & layout — guaranteed by the single shared component.
 *
 * Cards (top → bottom):
 *   • Trigger agent + Schedule call (DISC-57 + F10)
 *   • Refund offer (F11, only when student is in paid_silent panel)
 *   • Admin notes (F2)
 *   • Direct message (F8)
 *   • Activity timeline (DISC-55 + F14 paginated)
 */

import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bot,
  CalendarPlus,
  CheckCircle2,
  Clock,
  FileCode2,
  LogIn,
  MessageSquare,
  NotebookPen,
  Play,
  Sparkles,
} from "lucide-react";
import {
  useAdminStudents,
  useCreateStudentNote,
  useRefundOffers,
  useRiskPanels,
  useSendRefundOffer,
  useStudentNotes,
  useStudentTimeline,
  useStudentTimelineOlder,
  useTriggerAgent,
  type StudentTimelineEvent,
} from "@/lib/hooks/use-admin";
import {
  useAdminMessagesForStudent,
  useSendAdminMessage,
} from "@/lib/hooks/use-messages";
import { buildCallInviteMailto } from "@/lib/calendar-mailto";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Two-tier labels — the primary is human prose (renders in Inter),
// the key is the technical agent name (renders in JetBrains Mono as a
// caption). Keeps the dropdown readable while admins still see the
// canonical key that lands in the audit log.
const TRIGGERABLE_AGENTS = [
  { name: "disrupt_prevention", label: "Re-engage" },
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

/**
 * Card header in cockpit tone — small uppercase mono eyebrow, then a
 * Fraunces serif title with the icon inline. Used by every operator
 * card so the panel reads as part of the cockpit's typographic system
 * (Fraunces hero · JetBrains eyebrow · Inter prose) instead of a
 * generic shadcn card.
 *
 * Body text below the title stays Inter — Fraunces would be wrong for
 * a paragraph of helper copy. Numerics elsewhere in the panel pick up
 * mono via the modal's `.tabular-nums` style override.
 */
/**
 * Card header in v8/cockpit tone — eyebrow with leading dot, Fraunces
 * serif title at 22px with -0.03em tracking, generous body text. The
 * full set of typographic variables matches the /path screen so the
 * modal feels made of the same parts as the rest of the app.
 *
 *   ┌─────────────────────────────────────────────
 *   │ ● AGENT         (10px, 0.2em, weight 700, mint dot ::before)
 *   │ Trigger agent   (Fraunces 22px, weight 500, -0.03em)
 *   │ Runs on behalf… (14px, line-height 1.65, muted)
 *   └─────────────────────────────────────────────
 *
 * Body description uses 14px (not 12px) — at 12px Fraunces titles tower
 * over the prose and the rhythm breaks. The /path screen runs body at
 * 13-15px next to 22px serifs and that's what reads premium.
 */
function CardEyebrowHeader({
  eyebrow,
  title,
  icon,
  description,
  iconClassName,
}: {
  eyebrow: string;
  title: string;
  icon: React.ReactNode;
  description?: string;
  iconClassName?: string;
}) {
  return (
    <>
      <div
        className="cf-card-eyebrow"
        style={{
          fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
        }}
      >
        {eyebrow}
      </div>
      <h2
        className="cf-card-title flex items-center gap-3"
        style={{
          fontFamily: "var(--font-fraunces), Georgia, serif",
        }}
      >
        <span
          className={`cf-card-title-icon ${iconClassName ?? ""}`}
          aria-hidden="true"
        >
          {icon}
        </span>
        {title}
      </h2>
      {description ? (
        <p className="cf-card-prose">{description}</p>
      ) : null}
    </>
  );
}

interface StudentDetailPanelProps {
  studentId: string | null;
  /**
   * When `true` the component renders without the header (caller is
   * already showing student name/email in a wrapping chrome — e.g.
   * the side-drawer header). When `false` (default) the header is
   * rendered inline like the route page does.
   */
  hideHeader?: boolean;
  /**
   * Tightens spacing for the drawer rendering (cards stack with less
   * padding so more content fits in the viewport).
   */
  compact?: boolean;
}

export function StudentDetailPanel({
  studentId,
  hideHeader = false,
  compact = false,
}: StudentDetailPanelProps) {
  const { data: students } = useAdminStudents();
  const student = useMemo(
    () => students?.find((s) => s.id === studentId) ?? null,
    [students, studentId],
  );

  const { data: timeline = [], isLoading: timelineLoading } =
    useStudentTimeline(studentId);
  const { data: notes = [], isLoading: notesLoading } =
    useStudentNotes(studentId);
  const createNote = useCreateStudentNote(studentId);
  const trigger = useTriggerAgent();

  // F11 — Refund offer card surfaces only when the student is in
  // the paid_silent risk panel (Slip 4). useRiskPanels hits the same
  // endpoint as /admin so it'll usually be cached by the time we
  // land here, making the conditional render free.
  const { data: riskPanels } = useRiskPanels();
  const paidSilentMatch = useMemo(() => {
    if (!studentId || !riskPanels) return null;
    return (
      riskPanels.paid_silent.students.find((s) => s.user_id === studentId) ??
      null
    );
  }, [riskPanels, studentId]);
  const { data: refundOffers = [] } = useRefundOffers(studentId);
  const sendRefundOffer = useSendRefundOffer(studentId);

  // F8 — admin↔student in-app DM thread.
  const { data: dmMessages = [], isLoading: dmLoading } =
    useAdminMessagesForStudent(studentId);
  const sendDm = useSendAdminMessage(studentId);
  const dmThreadId = dmMessages[0]?.thread_id;

  const [selectedAgent, setSelectedAgent] = useState<string>(
    TRIGGERABLE_AGENTS[0].name,
  );
  const [triggerResult, setTriggerResult] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState<string>("");
  const [refundReason, setRefundReason] = useState<string>("");
  const [refundFlash, setRefundFlash] = useState<string | null>(null);
  const [dmDraft, setDmDraft] = useState<string>("");

  // F14 — pagination state for older timeline events.
  const PAGE_SIZE = 50;
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const activeCursor = cursorStack[cursorStack.length - 1] ?? null;
  const olderQuery = useStudentTimelineOlder(studentId, activeCursor);
  const queryClient = useQueryClient();

  const olderQueryData = olderQuery.data;
  const olderPages: StudentTimelineEvent[][] = useMemo(() => {
    if (!studentId) return [];
    void olderQueryData;
    return cursorStack
      .map((c) =>
        queryClient.getQueryData<StudentTimelineEvent[]>([
          "admin",
          "students",
          studentId,
          "timeline",
          "before",
          c,
        ]),
      )
      .filter((p): p is StudentTimelineEvent[] => Array.isArray(p));
  }, [cursorStack, studentId, queryClient, olderQueryData]);

  const endReached =
    cursorStack.length > 0 &&
    olderQuery.isSuccess &&
    (olderQuery.data?.length ?? 0) < PAGE_SIZE;

  const allEvents: StudentTimelineEvent[] = useMemo(
    () => [...timeline, ...olderPages.flat()],
    [timeline, olderPages],
  );

  function handleLoadOlder() {
    if (allEvents.length === 0) return;
    const oldest = allEvents[allEvents.length - 1];
    if (oldest.at === activeCursor) return;
    setCursorStack((prev) => [...prev, oldest.at]);
  }

  async function handleSendRefundOffer() {
    if (!studentId) return;
    setRefundFlash(null);
    try {
      const offer = await sendRefundOffer.mutateAsync({
        reason: refundReason.trim() || null,
      });
      setRefundReason("");
      setRefundFlash(
        offer.status === "sent"
          ? "Offer sent — outreach_log row written."
          : `Offer status: ${offer.status}. Retry available if needed.`,
      );
    } catch (err) {
      setRefundFlash(`Failed: ${(err as Error).message}`);
    }
  }

  async function handleAddNote() {
    const trimmed = noteDraft.trim();
    if (!trimmed || !studentId) return;
    try {
      await createNote.mutateAsync(trimmed);
      setNoteDraft("");
    } catch {
      // global toast handles failure
    }
  }

  async function handleSendDm() {
    const trimmed = dmDraft.trim();
    if (!trimmed || !studentId) return;
    try {
      await sendDm.mutateAsync({ body: trimmed, thread_id: dmThreadId });
      setDmDraft("");
    } catch {
      // global toast handles failure
    }
  }

  async function handleTrigger() {
    if (!studentId) return;
    setTriggerResult(null);
    try {
      const res = await trigger.mutateAsync({
        agentName: selectedAgent,
        studentId,
      });
      setTriggerResult(
        `✓ ${res.agent_name} · ${res.duration_ms}ms — ${res.response_preview || "(no response)"}`,
      );
    } catch (err) {
      setTriggerResult(`✗ ${(err as Error).message}`);
    }
  }

  const spacing = compact ? "space-y-4" : "space-y-6";

  return (
    <div className={spacing}>
      {!hideHeader && (
        <div>
          <div
            className="text-[11px] font-medium tracking-[0.22em] uppercase mb-2 text-primary"
            style={{
              fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
            }}
          >
            Student profile
          </div>
          <h1
            className="font-medium leading-[1.1]"
            style={{
              fontFamily: "var(--font-fraunces), Georgia, serif",
              fontSize: "30px",
              letterSpacing: "-0.015em",
            }}
          >
            {student?.full_name ?? "Student"}
          </h1>
          <p
            className="text-muted-foreground mt-1.5"
            style={{
              fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
              fontSize: "13px",
              letterSpacing: "0.005em",
            }}
          >
            {student?.email ?? studentId}
          </p>
          {student && (
            <div
              className="flex flex-wrap items-center gap-2.5 mt-3 text-xs text-muted-foreground"
              style={{
                fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
                fontFeatureSettings: '"tnum"',
                letterSpacing: "0.01em",
              }}
            >
              <Badge
                className={
                  student.is_active
                    ? "bg-green-100 text-green-700 hover:bg-green-100 uppercase tracking-[0.12em] text-[10px] font-medium"
                    : "bg-muted uppercase tracking-[0.12em] text-[10px] font-medium"
                }
                style={{
                  fontFamily:
                    "var(--font-jetbrains-mono), ui-monospace, monospace",
                }}
              >
                {student.is_active ? "Active" : "Inactive"}
              </Badge>
              <span>
                <span className="font-semibold text-foreground">
                  {student.lessons_completed}
                </span>{" "}
                lessons completed
              </span>
              <span>·</span>
              <span>
                <span className="font-semibold text-foreground">
                  {student.agent_interactions}
                </span>{" "}
                agent interactions
              </span>
              <span>·</span>
              <span>
                Joined {new Date(student.created_at).toLocaleDateString()}
              </span>
            </div>
          )}
        </div>
      )}

      {/* DISC-57 — admin agent trigger panel */}
      <Card>
        <CardHeader className="pb-2">
          <CardEyebrowHeader
            eyebrow="Agent"
            title="Trigger agent"
            icon={<Sparkles className="h-4 w-4" aria-hidden="true" />}
            iconClassName="text-primary"
            description="Runs on behalf of this student. Logged with your admin identity in the audit log."
          />
        </CardHeader>
        <CardContent className="flex flex-col md:flex-row gap-3">
          {/* shadcn Select (base-ui combobox) — fully styled, portal-rendered.
              Replaces the native <select> which had a white-flash on
              open in dark mode (OS popup briefly painted in default
              scheme before color-scheme: dark could apply). */}
          <Select
            value={selectedAgent}
            onValueChange={(v) => v !== null && setSelectedAgent(v)}
          >
            <SelectTrigger
              aria-label="Agent to trigger"
              className="cf-agent-trigger min-w-[260px]"
            >
              {/* Pure prose label — the technical agent key still lands
                  in the audit log on submit, but admins only see the
                  human verb in the UI. Single typeface (Inter), no
                  underscores anywhere. */}
              <SelectValue>
                {(value) =>
                  TRIGGERABLE_AGENTS.find((a) => a.name === value)?.label ??
                  value
                }
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {TRIGGERABLE_AGENTS.map((a) => (
                <SelectItem key={a.name} value={a.name}>
                  {a.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
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
          {/* F10 — Schedule call mailto-shim. */}
          {student?.email && (
            <a
              href={buildCallInviteMailto({
                studentEmail: student.email,
                studentName: student.full_name,
                slipType: paidSilentMatch ? "paid_silent" : null,
                riskReason: paidSilentMatch?.risk_reason ?? null,
              })}
              className="inline-flex items-center gap-1.5 h-9 rounded-lg border border-border px-3 text-sm font-medium hover:bg-muted/50"
            >
              <CalendarPlus className="h-3.5 w-3.5" aria-hidden="true" />
              Schedule call
            </a>
          )}
        </CardContent>
      </Card>

      {/* F11 — Refund offer card */}
      {paidSilentMatch && (
        <Card className="border-red-200 bg-red-50/40 dark:border-red-900/40 dark:bg-red-950/20">
          <CardHeader className="pb-2">
            <CardEyebrowHeader
              eyebrow="Refund · Slip 4 · day 14"
              title="Refund offer"
              icon={<AlertTriangle className="h-4 w-4" aria-hidden="true" />}
              iconClassName="text-red-600"
              description="Paid + silent crosses day 14 — refund risk territory. Sending the offer now beats waiting for them to ask."
            />
          </CardHeader>
          <CardContent className="space-y-3">
            <textarea
              value={refundReason}
              onChange={(e) => setRefundReason(e.target.value)}
              placeholder={
                paidSilentMatch.risk_reason ??
                "Quick context the operator can read on the email — e.g. 'no submissions in 14 days, day-3 nudge unread.'"
              }
              maxLength={500}
              rows={3}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-400"
              aria-label="Refund offer reason"
              disabled={sendRefundOffer.isPending}
            />
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">
                Optional. Echoes into the email body and the audit row.
              </span>
              <button
                type="button"
                onClick={() => void handleSendRefundOffer()}
                disabled={sendRefundOffer.isPending || !studentId}
                className="rounded-lg bg-red-600 px-4 py-1.5 text-sm font-medium text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                {sendRefundOffer.isPending ? "Sending…" : "Send refund offer"}
              </button>
            </div>
            {refundFlash && (
              <p className="text-xs text-muted-foreground" role="status">
                {refundFlash}
              </p>
            )}

            {refundOffers.length > 0 && (
              <div className="pt-2">
                <p className="mb-1 text-xs font-medium text-muted-foreground">
                  Prior offers
                </p>
                <ol className="space-y-1.5">
                  {refundOffers.map((o) => (
                    <li
                      key={o.id}
                      className="rounded-md border border-border bg-background/60 px-3 py-2 text-xs"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium uppercase tracking-wide">
                          {o.status}
                        </span>
                        <span className="text-muted-foreground">
                          {new Date(o.proposed_at).toLocaleString()}
                        </span>
                      </div>
                      {o.reason && (
                        <p className="mt-1 whitespace-pre-wrap text-muted-foreground">
                          {o.reason}
                        </p>
                      )}
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* F2 — Admin notes */}
      <Card>
        <CardHeader className="pb-2">
          <CardEyebrowHeader
            eyebrow="Notes · private"
            title="Admin notes"
            icon={<NotebookPen className="h-4 w-4" aria-hidden="true" />}
            iconClassName="text-muted-foreground"
            description="Private. Used to remember what was said to whom across rotations."
          />
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
              <span className="text-xs text-muted-foreground font-mono tabular-nums">
                {noteDraft.length}/2000
              </span>
              <button
                type="button"
                onClick={() => void handleAddNote()}
                disabled={
                  !noteDraft.trim() || createNote.isPending || !studentId
                }
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

      {/* F8 — Direct message */}
      <Card>
        <CardHeader className="pb-2">
          <CardEyebrowHeader
            eyebrow="Outreach"
            title="Direct message"
            icon={<MessageSquare className="h-4 w-4" aria-hidden="true" />}
            iconClassName="text-primary"
            description={
              "Visible to the student in their inbox. Replies flip the most recent outreach to “responded.”"
            }
          />
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <textarea
              value={dmDraft}
              onChange={(e) => setDmDraft(e.target.value)}
              placeholder="e.g. Hey — saw you haven't been on this week. Anything blocking? Reply here anytime."
              maxLength={5000}
              rows={3}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              aria-label="New direct message to student"
              disabled={sendDm.isPending}
            />
            <div className="mt-2 flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground font-mono tabular-nums">
                {dmDraft.length}/5000
              </span>
              <button
                type="button"
                onClick={() => void handleSendDm()}
                disabled={!dmDraft.trim() || sendDm.isPending || !studentId}
                className="rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
              >
                {sendDm.isPending ? "Sending…" : "Send message"}
              </button>
            </div>
          </div>

          {dmLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 2 }).map((_, i) => (
                <div key={i} className="h-12 animate-pulse rounded bg-muted" />
              ))}
            </div>
          ) : dmMessages.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              No messages yet. The first one usually opens the door.
            </p>
          ) : (
            <ol className="space-y-2">
              {dmMessages.map((m) => (
                <li
                  key={m.id}
                  className={
                    m.sender_role === "admin"
                      ? "rounded-lg border border-primary/30 bg-primary/5 px-3 py-2"
                      : "rounded-lg border border-border bg-background/50 px-3 py-2"
                  }
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      {m.sender_role === "admin" ? "You" : "Student"}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {new Date(m.created_at).toLocaleString()}
                    </span>
                  </div>
                  <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                    {m.body}
                  </pre>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      {/* DISC-55 — Activity timeline */}
      <Card>
        <CardHeader className="pb-2">
          <CardEyebrowHeader
            eyebrow="Activity"
            title="Activity timeline"
            icon={<Clock className="h-4 w-4" aria-hidden="true" />}
            iconClassName="text-muted-foreground"
            description="Lessons, submissions, agent runs, and last login — newest first."
          />
        </CardHeader>
        <CardContent>
          {timelineLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-10 animate-pulse rounded bg-muted" />
              ))}
            </div>
          ) : allEvents.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-6">
              No activity yet.
            </p>
          ) : (
            <>
              <ol className="space-y-2.5">
                {allEvents.map((ev, i) => (
                  <li
                    key={`${ev.kind}-${ev.at}-${i}`}
                    className="flex items-start gap-3 text-sm"
                  >
                    <span className="mt-0.5 text-muted-foreground">
                      <TimelineIcon kind={ev.kind} />
                    </span>
                    <div className="min-w-0 flex-1">
                      {/* Activity primary line — promoted to the
                          serif/narrative register. The cockpit treats
                          activity as a "diary" of the student's
                          journey, so Fraunces reads truer than Inter.
                          The modal CSS picks up `.cf-activity-summary`
                          and renders it in Fraunces 16px medium. */}
                      <p className="cf-activity-summary">{ev.summary}</p>
                      <p className="cf-activity-time">
                        {new Date(ev.at).toLocaleString()}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
              {!endReached && (
                <div className="mt-4 flex justify-center">
                  <button
                    type="button"
                    onClick={handleLoadOlder}
                    disabled={olderQuery.isFetching}
                    className="rounded-lg border border-border px-4 py-1.5 text-xs font-medium text-muted-foreground transition hover:bg-muted/50 disabled:opacity-50"
                  >
                    {olderQuery.isFetching ? "Loading…" : "Load older"}
                  </button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
