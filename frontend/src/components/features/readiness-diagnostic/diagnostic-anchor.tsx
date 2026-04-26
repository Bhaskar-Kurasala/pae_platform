"use client";

import { useEffect, useRef, useState } from "react";

import { DecoderCard } from "@/components/features/jd-decoder";
import { readinessCopy } from "@/lib/copy/readiness";
import {
  type FinalizeResponse,
  type StartDiagnosticResponse,
  useCheckCompletion,
  useFinalizeDiagnostic,
  usePastDiagnoses,
  useRecordNextActionClick,
  useStartDiagnostic,
  useSubmitDiagnosticTurn,
} from "@/lib/hooks/use-readiness";

import { diagnosticAnalytics } from "./analytics";
import {
  Conversation,
  type ConversationMessage,
} from "./conversation";
import { MemoryBanner } from "./memory-banner";
import { PastDiagnosesDrawer } from "./past-diagnoses-drawer";
import { VerdictCard } from "./verdict-card";

/**
 * Top-level diagnostic experience.
 *
 * Three states: idle (CTA to start) → conversation → verdict. The state
 * machine is driven by:
 *
 *   - sessionData (start_session result)
 *   - messages (transcript built from start + each turn response)
 *   - verdict (finalize response)
 *
 * Auto-finalize when the orchestrator signals is_final on a turn.
 * Loading states are deliberate: the agent's "Reading your work…"
 * during turn-fetch, the verdict's "Pulling the picture together…"
 * during finalize.
 */
export function DiagnosticAnchor() {
  const c = readinessCopy.diagnostic;

  const [sessionData, setSessionData] =
    useState<StartDiagnosticResponse | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [verdict, setVerdict] = useState<FinalizeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // When the interviewer flags invoke_jd_decoder=true, we surface the
  // decoder inline. Cleared after a successful decode.
  const [decoderActive, setDecoderActive] = useState(false);

  const startMut = useStartDiagnostic();
  const turnMut = useSubmitDiagnosticTurn(sessionData?.session_id ?? null);
  const finalizeMut = useFinalizeDiagnostic(
    sessionData?.session_id ?? null,
  );
  const clickMut = useRecordNextActionClick();
  const completionCheckMut = useCheckCompletion();
  // Page-load completion check — for any prior session where the
  // student clicked the CTA but completion hasn't been stamped yet,
  // re-evaluate now. This is the natural moment because students who
  // acted on the verdict typically return to Job Readiness next.
  const pastDiagnoses = usePastDiagnoses(true);
  const completionCheckedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const items = pastDiagnoses.data?.items ?? [];
    for (const d of items) {
      if (
        d.next_action_clicked_at &&
        !d.next_action_completed_at &&
        !completionCheckedRef.current.has(d.session_id)
      ) {
        completionCheckedRef.current.add(d.session_id);
        completionCheckMut.mutate(d.session_id);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pastDiagnoses.data?.items?.length]);

  // Track whether finalize has already been kicked off so the auto-
  // finalize effect can't double-fire.
  const finalizingRef = useRef(false);

  const startSession = async () => {
    setError(null);
    setVerdict(null);
    setMessages([]);
    finalizingRef.current = false;
    try {
      const data = await startMut.mutateAsync();
      setSessionData(data);
      setMessages([{ role: "agent", content: data.opening_message }]);
      diagnosticAnalytics.sessionStarted({
        session_id: data.session_id,
        has_prior_session: !!data.prior_session_hint,
      });
    } catch {
      setError(c.errorGeneric);
    }
  };

  const sendTurn = async (content: string) => {
    if (!sessionData) return;
    setError(null);
    // Optimistically render the student message.
    setMessages((prev) => [...prev, { role: "student", content }]);
    try {
      const result = await turnMut.mutateAsync({ content });
      setMessages((prev) => [
        ...prev,
        { role: "agent", content: result.agent_message },
      ]);
      diagnosticAnalytics.turnSent({
        session_id: sessionData.session_id,
        turn_number: result.turn,
      });
      if (result.invoke_jd_decoder) {
        diagnosticAnalytics.invokedDecoder({
          session_id: sessionData.session_id,
        });
        setDecoderActive(true);
      }
      if (result.is_final) {
        // Trigger finalize on the next tick so the UI flips into
        // the finalizing state cleanly.
        await finalize();
      }
    } catch {
      setError(c.errorGeneric);
    }
  };

  const onDecoderResult = (summary: string) => {
    setDecoderActive(false);
    // Synthesize a transcript line so the verdict generator (and the
    // student rereading the conversation) sees the decode as part of
    // the flow. The agent's voice; the orchestrator on the backend
    // also sees it via _load_session_jd_match_score.
    setMessages((prev) => [...prev, { role: "agent", content: summary }]);
  };

  const finalize = async () => {
    if (!sessionData || finalizingRef.current) return;
    finalizingRef.current = true;
    try {
      const result = await finalizeMut.mutateAsync({});
      setVerdict(result);
      diagnosticAnalytics.verdictDelivered({
        session_id: sessionData.session_id,
        next_action_intent: result.verdict.next_action.intent,
        sycophancy_flag_count: result.sycophancy_flags.length,
      });
    } catch {
      setError(c.errorGeneric);
      finalizingRef.current = false;
    }
  };

  // Cleanup: if the user navigates away mid-session, mark abandoned.
  // Best-effort; failures are silent.
  useEffect(() => {
    const sid = sessionData?.session_id;
    if (!sid || verdict) return;
    return () => {
      // Fire-and-forget; we don't need the response.
      void fetch(`/api/v1/readiness/diagnostic/sessions/${sid}/abandon`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        keepalive: true,
      }).catch(() => {
        /* swallow */
      });
      diagnosticAnalytics.sessionAbandoned({
        session_id: sid,
        turn_count: messages.length,
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionData?.session_id, !!verdict]);

  // ── render ──────────────────────────────────────────────

  // State 1: idle — opening invitation + past diagnoses drawer.
  if (!sessionData) {
    return (
      <Idle
        onStart={startSession}
        starting={startMut.isPending}
        error={error}
      />
    );
  }

  // State 3: verdict delivered.
  if (verdict) {
    return (
      <div
        className="diagnostic-anchor"
        style={{ display: "flex", flexDirection: "column", gap: 16 }}
      >
        <MemoryBanner hint={sessionData.prior_session_hint} />
        <VerdictCard
          sessionId={sessionData.session_id}
          verdict={verdict.verdict}
          onNextActionClick={(sid) => {
            // Fire the north-star beacon. Best-effort — Link
            // navigation should not block on this.
            clickMut.mutate(sid);
          }}
        />
        <PastDiagnosesDrawer />
      </div>
    );
  }

  // State 2: conversation in flight.
  const isAgentThinking = turnMut.isPending;
  const isFinalizing = finalizeMut.isPending;
  const inlineEmbed = decoderActive ? (
    <InlineDecoderEmbed onResult={onDecoderResult} />
  ) : null;
  return (
    <div
      className="diagnostic-anchor"
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      <MemoryBanner hint={sessionData.prior_session_hint} />
      <Conversation
        messages={messages}
        isAgentThinking={isAgentThinking}
        isFinalizing={isFinalizing}
        // While the inline decoder is open, the chat input goes calm
        // — the student is doing the JD task; we don't want them
        // typing into both surfaces simultaneously.
        inputDisabled={isAgentThinking || isFinalizing || decoderActive}
        onSend={sendTurn}
        inlineEmbed={inlineEmbed}
      />
      {error && (
        <div role="alert" style={{ color: "#c14a3f", fontSize: 13 }}>
          {error}
        </div>
      )}
      <PastDiagnosesDrawer />
    </div>
  );
}

/**
 * Wraps the standalone JD DecoderCard in embedded mode and bridges
 * its onSuccess into the conversation. Renders a small intro line
 * above so the embed feels like an agent affordance, not a sidebar
 * tool.
 */
function InlineDecoderEmbed({
  onResult,
}: {
  onResult: (summary: string) => void;
}) {
  const c = readinessCopy.diagnostic;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <header style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <div
          style={{
            fontSize: 11,
            color: "var(--forest)",
            textTransform: "uppercase",
            letterSpacing: 1.4,
            fontWeight: 600,
          }}
        >
          {c.decoderEmbedHeader}
        </div>
        <div style={{ color: "var(--ink-2)", fontSize: 13 }}>
          {c.decoderEmbedBlurb}
        </div>
      </header>
      <DecoderCard embedded onDecoded={onResult} />
    </div>
  );
}

function Idle({
  onStart,
  starting,
  error,
}: {
  onStart: () => void;
  starting: boolean;
  error: string | null;
}) {
  const c = readinessCopy.diagnostic;
  return (
    <div
      className="diagnostic-anchor diagnostic-anchor-idle"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        padding: 24,
        borderRadius: 14,
        background: "var(--forest-soft)",
        border: "1px solid var(--forest-soft)",
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div
          style={{
            fontSize: 11,
            color: "var(--forest)",
            textTransform: "uppercase",
            letterSpacing: 1.4,
            fontWeight: 600,
          }}
        >
          Diagnostic
        </div>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--serif, 'Fraunces', Georgia, serif)",
            fontSize: 26,
            lineHeight: 1.25,
            color: "var(--ink)",
            fontWeight: 500,
          }}
        >
          {c.opener}
        </h2>
      </header>
      <button
        type="button"
        className="btn primary"
        onClick={onStart}
        disabled={starting}
        style={{
          alignSelf: "flex-start",
          padding: "12px 20px",
          borderRadius: 10,
          background: "var(--forest)",
          color: "var(--forest-soft)",
          border: "none",
          fontWeight: 600,
          fontSize: 15,
          cursor: starting ? "wait" : "pointer",
          opacity: starting ? 0.7 : 1,
        }}
      >
        {starting ? "Starting…" : "Start the diagnostic"}
      </button>
      {error && (
        <div role="alert" style={{ color: "#c14a3f", fontSize: 13 }}>
          {error}
        </div>
      )}
      <PastDiagnosesDrawer />
    </div>
  );
}
