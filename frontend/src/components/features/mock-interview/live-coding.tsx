"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type AnswerEvaluation,
  type MockQuestion,
  type StartMockResponse,
  useSubmitMockAnswer,
} from "@/lib/hooks/use-mock-interview";
import { COPY } from "./copy";
import { usePyodide } from "./use-pyodide";

interface LiveCodingProps {
  session: StartMockResponse;
  onComplete: (sessionId: string) => void;
  onAbandon: (sessionId: string, questionsAnswered: number) => void;
}

interface ChatBubble {
  role: "interviewer" | "candidate";
  text: string;
  evaluation?: AnswerEvaluation;
}

const STARTER_TEMPLATE = `# Write your solution here.
# stdout from print(...) shows below.
# Hit "Run" to execute in your browser; "Submit" sends to the agent.

def solution():
    pass

print(solution())
`;

export function LiveCoding({
  session,
  onComplete,
  onAbandon,
}: LiveCodingProps) {
  const [bubbles, setBubbles] = useState<ChatBubble[]>(() => [
    { role: "interviewer", text: session.first_question.text },
  ]);
  const [currentQuestion, setCurrentQuestion] = useState<MockQuestion>(
    session.first_question,
  );
  const [code, setCode] = useState(STARTER_TEMPLATE);
  const [stdout, setStdout] = useState("");
  const [stderr, setStderr] = useState("");
  const [running, setRunning] = useState(false);
  const [costInr, setCostInr] = useState(0);
  const [costCapHit, setCostCapHit] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [questionsAnswered, setQuestionsAnswered] = useState(0);
  const submitMutation = useSubmitMockAnswer();
  const py = usePyodide({ eager: true });
  const submitStartedAtRef = useRef(Date.now());
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [bubbles.length]);

  const runCode = useCallback(async () => {
    setRunning(true);
    setStdout("");
    setStderr("");
    try {
      const result = await py.run(code);
      setStdout(result.stdout);
      setStderr(result.stderr);
    } catch (exc) {
      setStderr(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRunning(false);
    }
  }, [code, py]);

  const submit = useCallback(async () => {
    setError(null);
    const submission = `# Code:\n${code}\n\n# stdout:\n${stdout || "(none)"}\n\n# stderr:\n${stderr || "(none)"}`;
    setBubbles((prev) => [...prev, { role: "candidate", text: code }]);
    setQuestionsAnswered((n) => n + 1);
    const latency_ms = Math.max(0, Date.now() - submitStartedAtRef.current);
    try {
      const result = await submitMutation.mutateAsync({
        session_id: session.session_id,
        question_id: currentQuestion.id,
        text: submission,
        latency_ms,
      });
      setCostInr(result.cost_inr_so_far);
      setCostCapHit(result.cost_cap_exceeded);
      setBubbles((prev) => [
        ...prev,
        {
          role: "interviewer",
          text: result.interviewer_reaction || result.evaluation.feedback,
          evaluation: result.evaluation,
        },
      ]);
      if (result.next_question) {
        setCurrentQuestion(result.next_question);
        setCode(STARTER_TEMPLATE);
        setStdout("");
        setStderr("");
        setBubbles((prev) => [
          ...prev,
          { role: "interviewer", text: result.next_question!.text },
        ]);
      }
      submitStartedAtRef.current = Date.now();
    } catch (exc) {
      setError(
        exc instanceof Error ? exc.message : COPY.errors.answerFailed,
      );
    }
  }, [
    code,
    currentQuestion.id,
    session.session_id,
    stderr,
    stdout,
    submitMutation,
  ]);

  const handleEnd = useCallback(() => {
    if (!window.confirm(COPY.session.endConfirm)) return;
    if (questionsAnswered === 0) {
      onAbandon(session.session_id, 0);
    } else {
      onComplete(session.session_id);
    }
  }, [onAbandon, onComplete, questionsAnswered, session.session_id]);

  const costNotice = useMemo(() => COPY.session.costNotice(costInr), [costInr]);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)",
        gap: 14,
      }}
    >
      <div className="match-card" style={{ padding: 16, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
            marginBottom: 10,
          }}
        >
          <div className="k">Editor · Python (Pyodide)</div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>{costNotice}</div>
        </div>

        {!py.ready ? (
          <div
            style={{
              padding: "10px 14px",
              borderRadius: 10,
              background: "var(--gold-soft)",
              color: "#8d621b",
              fontSize: 13,
              marginBottom: 10,
            }}
          >
            {COPY.liveCoding.sandboxLoading}
            {py.error ? <> · {py.error}</> : null}
          </div>
        ) : null}

        <textarea
          value={code}
          onChange={(e) => setCode(e.target.value)}
          spellCheck={false}
          style={{
            width: "100%",
            minHeight: 280,
            fontFamily:
              "var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace)",
            fontSize: 13.5,
            padding: 12,
            borderRadius: 10,
            border: "1px solid var(--line)",
            background: "#fdfcf6",
            resize: "vertical",
          }}
        />

        <div className="rd-footer" style={{ marginTop: 10 }}>
          <button
            type="button"
            className="btn secondary"
            onClick={runCode}
            disabled={!py.ready || running}
          >
            {running ? "Running…" : COPY.liveCoding.runButton}
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={submit}
            disabled={
              submitMutation.isPending || costCapHit || !code.trim()
            }
          >
            {submitMutation.isPending ? "Sending…" : "Submit"}
          </button>
          <button type="button" className="btn ghost" onClick={handleEnd}>
            {COPY.session.endButton}
          </button>
        </div>

        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
          {COPY.liveCoding.runHint}
        </div>

        {(stdout || stderr) ? (
          <div
            style={{
              marginTop: 12,
              display: "grid",
              gap: 8,
              fontFamily:
                "var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace)",
              fontSize: 12.5,
            }}
          >
            {stdout ? (
              <pre
                style={{
                  padding: 10,
                  background: "#fbfaf5",
                  border: "1px solid var(--line)",
                  borderRadius: 8,
                  whiteSpace: "pre-wrap",
                }}
              >
                {stdout}
              </pre>
            ) : null}
            {stderr ? (
              <pre
                style={{
                  padding: 10,
                  background: "#f7e1d9",
                  color: "var(--rose)",
                  border: "1px solid var(--line)",
                  borderRadius: 8,
                  whiteSpace: "pre-wrap",
                }}
              >
                {stderr}
              </pre>
            ) : null}
          </div>
        ) : null}

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

      <div className="match-card" style={{ padding: 16, minWidth: 0 }}>
        <div className="k">Interviewer</div>
        <div
          ref={transcriptRef}
          style={{
            maxHeight: 480,
            overflowY: "auto",
            display: "grid",
            gap: 10,
            marginTop: 10,
          }}
        >
          {bubbles.map((b, i) => (
            <div
              key={i}
              style={{
                background:
                  b.role === "interviewer" ? "#fff" : "var(--forest-soft)",
                border: "1px solid var(--line)",
                borderRadius: 10,
                padding: "10px 12px",
                fontSize: 13.5,
                lineHeight: 1.55,
                whiteSpace: b.role === "candidate" ? "pre-wrap" : "normal",
                fontFamily:
                  b.role === "candidate"
                    ? "var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace)"
                    : undefined,
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
                {b.role === "interviewer" ? "Interviewer" : "Your code"}
              </div>
              <div>{b.text}</div>
              {b.evaluation && !b.evaluation.needs_human_review ? (
                <details style={{ marginTop: 8 }}>
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
                    Score: {b.evaluation.overall.toFixed(1)}
                  </summary>
                  <ul style={{ marginTop: 6, paddingLeft: 18 }}>
                    {b.evaluation.criteria.map((c) => (
                      <li key={c.name} style={{ fontSize: 12.5 }}>
                        <b>{c.name}</b>: {c.score}/10 — {c.rationale}
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
              {b.evaluation?.needs_human_review ? (
                <div
                  style={{
                    marginTop: 8,
                    padding: "6px 10px",
                    borderRadius: 8,
                    background: "var(--gold-soft)",
                    color: "#8d621b",
                    fontSize: 12.5,
                  }}
                >
                  {COPY.session.needsHumanReview}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
