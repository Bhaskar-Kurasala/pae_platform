"use client";

import {
  type ChangeEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useState,
} from "react";

import { tailoredResumeCopy as copy } from "@/lib/copy/tailored-resume";
import {
  type IntakeQuestion,
  type IntakeStartResponse,
  type TailoredResumeResult,
  useGenerateTailoredResume,
  useStartIntake,
} from "@/lib/hooks/use-tailored-resume";

import { GenerationProgress } from "./generation-progress";
import { PdfPreview } from "./pdf-preview";

interface Props {
  open: boolean;
  onClose: () => void;
}

type Step = "jd" | "questions" | "review" | "generating" | "preview" | "error";

export function IntakeModal({ open, onClose }: Props) {
  const [step, setStep] = useState<Step>("jd");
  const [jdText, setJdText] = useState<string>("");
  const [intake, setIntake] = useState<IntakeStartResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<TailoredResumeResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [softGateOverridden, setSoftGateOverridden] = useState(false);

  const startIntake = useStartIntake();
  const generate = useGenerateTailoredResume();

  // Reset whenever the modal closes so the next open is clean.
  useEffect(() => {
    if (!open) {
      setStep("jd");
      setJdText("");
      setIntake(null);
      setAnswers({});
      setResult(null);
      setErrorMessage("");
      setSoftGateOverridden(false);
    }
  }, [open]);

  const handleJdSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (jdText.trim().length < 20) return;
      try {
        const data = await startIntake.mutateAsync({ jd_text: jdText });
        setIntake(data);
        setStep("questions");
      } catch (err) {
        setErrorMessage(err instanceof Error ? err.message : String(err));
        setStep("error");
      }
    },
    [jdText, startIntake],
  );

  const updateAnswer = useCallback(
    (id: string) =>
      (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
        setAnswers((prev) => ({ ...prev, [id]: event.target.value }));
      },
    [],
  );

  const allRequiredAnswered = (questions: IntakeQuestion[]): boolean =>
    questions
      .filter((q) => q.required === "true")
      .every((q) => (answers[q.id] || "").trim().length > 0);

  const handleQuestionsSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!intake) return;
      if (!allRequiredAnswered(intake.questions)) return;
      setStep("review");
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [intake, answers],
  );

  const handleGenerate = useCallback(async () => {
    setStep("generating");
    try {
      const out = await generate.mutateAsync({
        jd_text: jdText,
        intake_answers: answers,
      });
      setResult(out);
      setStep("preview");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : String(err));
      setStep("error");
    }
  }, [generate, jdText, answers]);

  if (!open) return null;

  const softGateActive =
    step === "questions" && intake?.soft_gate === true && !softGateOverridden;

  return (
    <div
      className="export-overlay show"
      role="dialog"
      aria-modal="true"
      aria-label="Tailored resume intake"
    >
      <div className="export-card" style={{ maxWidth: 720, width: "92vw" }}>
        {step === "jd" && (
          <form onSubmit={handleJdSubmit}>
            <div className="rd-section-k">{copy.intake.stepLabels[0]}</div>
            <div className="rd-section-t">{copy.intake.jdHeading}</div>
            <div className="rd-section-c">{copy.intake.jdHelper}</div>
            <textarea
              className="jd-paste"
              placeholder={copy.intake.jdPlaceholder}
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
              required
              minLength={20}
            />
            <div className="rd-footer">
              <button
                type="submit"
                className="btn primary"
                disabled={jdText.trim().length < 20 || startIntake.isPending}
              >
                {startIntake.isPending ? "Reading…" : copy.intake.nextButton}
              </button>
              <button type="button" className="btn ghost" onClick={onClose}>
                {copy.intake.cancelButton}
              </button>
            </div>
          </form>
        )}

        {step === "questions" && intake && softGateActive && (
          <div>
            <div className="rd-section-k">Heads up</div>
            <div className="rd-section-t">{copy.softGate.title}</div>
            <div className="rd-section-c">{copy.softGate.body}</div>
            <div className="rd-footer">
              <button
                type="button"
                className="btn primary"
                onClick={() => setSoftGateOverridden(true)}
              >
                {copy.softGate.overrideButton}
              </button>
              <button type="button" className="btn ghost" onClick={onClose}>
                {copy.softGate.rehearseButton}
              </button>
            </div>
          </div>
        )}

        {step === "questions" && intake && !softGateActive && (
          <form onSubmit={handleQuestionsSubmit}>
            <div className="rd-section-k">{copy.intake.stepLabels[1]}</div>
            <div className="rd-section-t">{copy.intake.questionsHeading}</div>
            <div className="rd-section-c">{copy.intake.questionsHelper}</div>
            <div className="rd-list" style={{ marginTop: 16 }}>
              {intake.questions.map((q) => (
                <label key={q.id} className="rd-li" style={{ display: "block" }}>
                  <b>
                    {q.label}
                    {q.required === "true" ? " *" : ""}
                  </b>
                  {q.kind === "textarea" ? (
                    <textarea
                      className="coach-answer"
                      onChange={updateAnswer(q.id)}
                      value={answers[q.id] || ""}
                    />
                  ) : (
                    <input
                      type="text"
                      className="jd-paste"
                      style={{ minHeight: 0, padding: "8px 12px" }}
                      onChange={updateAnswer(q.id)}
                      value={answers[q.id] || ""}
                    />
                  )}
                </label>
              ))}
            </div>
            <div className="rd-footer">
              <button
                type="submit"
                className="btn primary"
                disabled={!allRequiredAnswered(intake.questions)}
              >
                {copy.intake.nextButton}
              </button>
              <button
                type="button"
                className="btn ghost"
                onClick={() => setStep("jd")}
              >
                {copy.intake.backButton}
              </button>
            </div>
          </form>
        )}

        {step === "review" && (
          <div>
            <div className="rd-section-k">{copy.intake.stepLabels[2]}</div>
            <div className="rd-section-t">{copy.intake.reviewHeading}</div>
            <div className="rd-section-c">{copy.intake.reviewHelper}</div>
            <div className="rd-footer">
              <button
                type="button"
                className="btn primary"
                onClick={handleGenerate}
              >
                {copy.intake.generateButton}
              </button>
              <button
                type="button"
                className="btn ghost"
                onClick={() => setStep("questions")}
              >
                {copy.intake.backButton}
              </button>
            </div>
          </div>
        )}

        {step === "generating" && <GenerationProgress active />}

        {step === "preview" && result && (
          <PdfPreview result={result} onClose={onClose} />
        )}

        {step === "error" && (
          <div>
            <div className="rd-section-k">Something went wrong</div>
            <div className="rd-section-t">{copy.generation.failureTitle}</div>
            <div className="rd-section-c">
              {errorMessage || copy.generation.failureBody}
            </div>
            <div className="rd-footer">
              <button
                type="button"
                className="btn primary"
                onClick={() => setStep("jd")}
              >
                Try again
              </button>
              <button type="button" className="btn ghost" onClick={onClose}>
                Close
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
