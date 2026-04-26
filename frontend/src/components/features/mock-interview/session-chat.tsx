"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type AnswerEvaluation,
  type MockMode,
  type MockQuestion,
  type StartMockResponse,
  useSubmitMockAnswer,
} from "@/lib/hooks/use-mock-interview";
import { COPY } from "./copy";
import { useVoiceLayer } from "./use-voice-layer";

interface SessionChatProps {
  session: StartMockResponse;
  voiceEnabled: boolean;
  onComplete: (sessionId: string) => void;
  onAbandon: (sessionId: string, questionsAnswered: number) => void;
}

interface ChatBubble {
  role: "interviewer" | "candidate";
  text: string;
  evaluation?: AnswerEvaluation;
  needsHumanReview?: boolean;
}

export function SessionChat({
  session,
  voiceEnabled,
  onComplete,
  onAbandon,
}: SessionChatProps) {
  const [bubbles, setBubbles] = useState<ChatBubble[]>(() => {
    const initial: ChatBubble[] = [];
    if (session.memory_recall) {
      initial.push({ role: "interviewer", text: session.memory_recall });
    }
    initial.push({ role: "interviewer", text: session.first_question.text });
    return initial;
  });
  const [currentQuestion, setCurrentQuestion] = useState<MockQuestion>(
    session.first_question,
  );
  const [draft, setDraft] = useState("");
  const [costInr, setCostInr] = useState(0);
  const [costCapHit, setCostCapHit] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [questionsAnswered, setQuestionsAnswered] = useState(0);
  const submitMutation = useSubmitMockAnswer();

  const voice = useVoiceLayer();
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const submitStartedAtRef = useRef<number>(Date.now());

  // Auto-scroll on new bubbles.
  useEffect(() => {
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [bubbles.length]);

  // When voice is on and the interviewer says something new, speak it.
  useEffect(() => {
    if (!voiceEnabled || !voice.supported) return;
    const last = bubbles[bubbles.length - 1];
    if (last && last.role === "interviewer") {
      voice.speak(last.text);
    }
    return () => {
      voice.cancelSpeech();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bubbles.length, voiceEnabled, voice.supported]);

  // Update the draft as voice transcript flows in.
  useEffect(() => {
    if (!voiceEnabled || !voice.supported) return;
    const combined =
      voice.finalTranscript +
      (voice.interimTranscript ? ` ${voice.interimTranscript}` : "");
    if (combined.trim()) setDraft(combined.trim());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voice.finalTranscript, voice.interimTranscript, voiceEnabled]);

  const handleStartListening = useCallback(() => {
    submitStartedAtRef.current = Date.now();
    voice.start();
  }, [voice]);

  const handleStopListening = useCallback(() => {
    voice.stop();
  }, [voice]);

  const submit = useCallback(async () => {
    const text = draft.trim();
    if (!text) return;
    setError(null);
    voice.cancelSpeech();
    voice.stop();

    const latency_ms = Math.max(0, Date.now() - submitStartedAtRef.current);
    const ttfw = voice.timeToFirstWordMs ?? undefined;

    setBubbles((prev) => [...prev, { role: "candidate", text }]);
    setDraft("");
    setQuestionsAnswered((n) => n + 1);

    try {
      const result = await submitMutation.mutateAsync({
        session_id: session.session_id,
        question_id: currentQuestion.id,
        text,
        latency_ms,
        time_to_first_word_ms: ttfw,
      });
      setCostInr(result.cost_inr_so_far);
      setCostCapHit(result.cost_cap_exceeded);

      // Reaction (probe / move-on) — show as next interviewer bubble if present.
      const evalBubble: ChatBubble = {
        role: "interviewer",
        text: result.interviewer_reaction || result.evaluation.feedback,
        evaluation: result.evaluation,
        needsHumanReview: result.evaluation.needs_human_review,
      };
      setBubbles((prev) => [...prev, evalBubble]);

      if (result.next_question) {
        setCurrentQuestion(result.next_question);
        setBubbles((prev) => [
          ...prev,
          { role: "interviewer", text: result.next_question!.text },
        ]);
      } else if (result.cost_cap_exceeded) {
        setBubbles((prev) => [
          ...prev,
          { role: "interviewer", text: COPY.session.costCapHit },
        ]);
      }
      voice.reset();
      submitStartedAtRef.current = Date.now();
    } catch (exc) {
      setError(
        exc instanceof Error ? exc.message : COPY.errors.answerFailed,
      );
    }
  }, [
    draft,
    currentQuestion.id,
    session.session_id,
    submitMutation,
    voice,
  ]);

  const handleEnd = useCallback(() => {
    if (!window.confirm(COPY.session.endConfirm)) return;
    voice.cancelSpeech();
    voice.stop();
    if (questionsAnswered === 0) {
      onAbandon(session.session_id, 0);
    } else {
      onComplete(session.session_id);
    }
  }, [onAbandon, onComplete, questionsAnswered, session.session_id, voice]);

  const costNotice = useMemo(() => COPY.session.costNotice(costInr), [costInr]);

  const showVoice = voiceEnabled && voice.supported;
  const voiceFallbackBanner =
    voiceEnabled && !voice.supported ? COPY.errors.sttUnsupported : null;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      {voiceFallbackBanner ? (
        <div
          style={{
            padding: "10px 14px",
            borderRadius: 10,
            background: "var(--gold-soft)",
            color: "#8d621b",
            fontSize: 13,
          }}
        >
          {voiceFallbackBanner}
        </div>
      ) : null}

      {costCapHit ? (
        <div
          style={{
            padding: "10px 14px",
            borderRadius: 10,
            background: "#f7e1d9",
            color: "var(--rose)",
            fontSize: 13,
          }}
        >
          {COPY.session.costCapHit}
        </div>
      ) : null}

      <div
        ref={transcriptRef}
        style={{
          maxHeight: 460,
          overflowY: "auto",
          display: "grid",
          gap: 10,
          padding: 14,
          borderRadius: 14,
          border: "1px solid var(--line)",
          background: "#fbfaf5",
        }}
      >
        {bubbles.map((b, i) => (
          <Bubble key={i} bubble={b} />
        ))}
      </div>

      <div className="match-card" style={{ padding: 16 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 10,
            gap: 12,
          }}
        >
          <div
            style={{
              fontSize: 11,
              letterSpacing: ".12em",
              textTransform: "uppercase",
              color: "var(--muted)",
              fontWeight: 700,
            }}
          >
            {COPY.session.youName}
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>{costNotice}</div>
        </div>

        <textarea
          className="coach-answer"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={
            showVoice ? COPY.session.voiceHint : COPY.session.typeHint
          }
          disabled={costCapHit}
          rows={4}
        />

        {showVoice ? (
          <div
            className={`rec-wave${voice.listening ? " live" : ""}`}
            style={{ marginTop: 10 }}
          >
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="rec-bar" />
            ))}
          </div>
        ) : null}

        <div className="rd-footer" style={{ marginTop: 12 }}>
          {showVoice ? (
            <button
              type="button"
              className={voice.listening ? "btn primary" : "btn secondary"}
              onClick={
                voice.listening ? handleStopListening : handleStartListening
              }
              disabled={costCapHit}
            >
              {voice.listening ? "Stop" : "Speak"}
            </button>
          ) : null}
          <button
            type="button"
            className="btn primary"
            onClick={submit}
            disabled={
              !draft.trim() || submitMutation.isPending || costCapHit
            }
          >
            {submitMutation.isPending ? "Scoring…" : "Submit answer"}
          </button>
          <button type="button" className="btn ghost" onClick={handleEnd}>
            {COPY.session.endButton}
          </button>
        </div>

        {error ? (
          <div
            style={{
              marginTop: 10,
              fontSize: 13,
              color: "var(--rose)",
            }}
          >
            {error}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Bubble({ bubble }: { bubble: ChatBubble }) {
  const isInterviewer = bubble.role === "interviewer";
  return (
    <div
      style={{
        alignSelf: isInterviewer ? "flex-start" : "flex-end",
        maxWidth: "92%",
        background: isInterviewer ? "#fff" : "var(--forest-soft)",
        border: "1px solid var(--line)",
        borderRadius: 12,
        padding: "10px 14px",
        fontSize: 14,
        lineHeight: 1.55,
        boxShadow: "0 1px 2px rgba(0,0,0,.03)",
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: ".12em",
          textTransform: "uppercase",
          color: "var(--muted)",
          fontWeight: 700,
          marginBottom: 6,
        }}
      >
        {isInterviewer ? COPY.session.interviewerName : COPY.session.youName}
      </div>
      <div>{bubble.text}</div>
      {bubble.evaluation ? (
        <EvaluationDetails evaluation={bubble.evaluation} />
      ) : null}
    </div>
  );
}

function EvaluationDetails({ evaluation }: { evaluation: AnswerEvaluation }) {
  if (evaluation.needs_human_review) {
    return (
      <div
        style={{
          marginTop: 10,
          padding: "8px 10px",
          borderRadius: 8,
          background: "var(--gold-soft)",
          color: "#8d621b",
          fontSize: 12.5,
          lineHeight: 1.5,
        }}
      >
        {COPY.session.needsHumanReview}
      </div>
    );
  }
  return (
    <details style={{ marginTop: 10 }}>
      <summary
        style={{
          fontSize: 11,
          letterSpacing: ".08em",
          textTransform: "uppercase",
          color: "var(--muted)",
          cursor: "pointer",
          fontWeight: 700,
        }}
      >
        Score: {evaluation.overall.toFixed(1)} ·{" "}
        {evaluation.would_pass ? "would pass" : "below bar"}
      </summary>
      <div
        style={{
          marginTop: 8,
          display: "grid",
          gap: 6,
          fontSize: 12.5,
        }}
      >
        {evaluation.criteria.map((c) => (
          <div
            key={c.name}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr auto",
              gap: 8,
              alignItems: "baseline",
            }}
          >
            <div>
              <b style={{ marginRight: 6 }}>{c.name}</b>
              <span style={{ color: "var(--muted)" }}>{c.rationale}</span>
            </div>
            <div style={{ fontWeight: 700 }}>{c.score}/10</div>
          </div>
        ))}
      </div>
    </details>
  );
}
