"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Briefcase,
  Check,
  Compass,
  Loader2,
  Rocket,
  Target,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Motivation } from "@/lib/api-client";

type MotivationChoice = {
  value: Motivation;
  label: string;
  helper: string;
  icon: React.ElementType;
};

const MOTIVATIONS: MotivationChoice[] = [
  {
    value: "career_switch",
    label: "Switch careers into AI engineering",
    helper: "I want a new role where I ship AI systems.",
    icon: Briefcase,
  },
  {
    value: "skill_up",
    label: "Level up in my current role",
    helper: "I want to own production GenAI at work.",
    icon: Rocket,
  },
  {
    value: "interview",
    label: "Prepare for interviews",
    helper: "I have a specific loop coming up.",
    icon: Target,
  },
  {
    value: "curiosity",
    label: "Learn deeply for curiosity",
    helper: "I want to understand this field end-to-end.",
    icon: Compass,
  },
];

const DEADLINE_PRESETS = [
  { value: 2, label: "2 months", helper: "Intense sprint" },
  { value: 4, label: "4 months", helper: "Steady pace" },
  { value: 6, label: "6 months", helper: "Deep mastery" },
  { value: 12, label: "12 months", helper: "Alongside full-time work" },
];

const STEPS = ["motivation", "deadline", "success"] as const;
type Step = (typeof STEPS)[number];

const DRAFT_KEY = "onboarding-draft-v1";

type DraftShape = {
  step?: Step;
  motivation?: Motivation | null;
  deadline?: number | null;
  successStatement?: string;
};

function readDraft(): DraftShape | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as DraftShape;
    if (typeof parsed !== "object" || parsed === null) return null;
    return parsed;
  } catch {
    return null;
  }
}

export interface GoalContractFormProps {
  /** Optional pre-filled values for editing an existing goal. */
  defaultValues?: {
    motivation?: Motivation;
    deadline_months?: number;
    success_statement?: string;
  };
  onSubmit: (values: {
    motivation: Motivation;
    deadline_months: number;
    success_statement: string;
  }) => Promise<void> | void;
  submitLabel?: string;
}

export function GoalContractForm({
  defaultValues,
  onSubmit,
  submitLabel = "Lock in my goal",
}: GoalContractFormProps) {
  const prefersReducedMotion = useReducedMotion();

  const [step, setStep] = useState<Step>("motivation");
  const [motivation, setMotivation] = useState<Motivation | null>(
    defaultValues?.motivation ?? null,
  );
  const [deadline, setDeadline] = useState<number | null>(
    defaultValues?.deadline_months ?? null,
  );
  const [successStatement, setSuccessStatement] = useState(
    defaultValues?.success_statement ?? "",
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hydrated = useRef(false);

  const stepIndex = STEPS.indexOf(step);

  // Restore draft after mount (client-only) to avoid hydration mismatch.
  useEffect(() => {
    if (defaultValues) {
      hydrated.current = true;
      return;
    }
    const draft = readDraft();
    if (draft) {
      if (draft.step && STEPS.includes(draft.step)) setStep(draft.step);
      if (draft.motivation !== undefined) setMotivation(draft.motivation);
      if (draft.deadline !== undefined) setDeadline(draft.deadline);
      if (typeof draft.successStatement === "string") {
        setSuccessStatement(draft.successStatement);
      }
    }
    hydrated.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (defaultValues) return;
    if (!hydrated.current) return;
    if (typeof window === "undefined") return;
    try {
      window.sessionStorage.setItem(
        DRAFT_KEY,
        JSON.stringify({ step, motivation, deadline, successStatement }),
      );
    } catch {
      /* quota or disabled storage — ignore */
    }
  }, [defaultValues, step, motivation, deadline, successStatement]);

  function canAdvance(): boolean {
    if (step === "motivation") return motivation !== null;
    if (step === "deadline") return deadline !== null;
    if (step === "success") return successStatement.trim().length >= 10;
    return false;
  }

  function next() {
    setError(null);
    if (!canAdvance()) return;
    if (step === "motivation") setStep("deadline");
    else if (step === "deadline") setStep("success");
  }

  function back() {
    setError(null);
    if (step === "deadline") setStep("motivation");
    else if (step === "success") setStep("deadline");
  }

  async function handleSubmit() {
    if (!motivation || !deadline || successStatement.trim().length < 10) {
      setError("Finish all three steps before submitting.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit({
        motivation,
        deadline_months: deadline,
        success_statement: successStatement.trim(),
      });
      if (typeof window !== "undefined") {
        try {
          window.sessionStorage.removeItem(DRAFT_KEY);
        } catch {
          /* ignore */
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setSubmitting(false);
    }
  }

  const direction = 0; // keeping enter/exit symmetric for now

  return (
    <div className="w-full max-w-xl mx-auto">
      {/* Stepper */}
      <div
        className="mb-10 flex items-center gap-2"
        role="progressbar"
        aria-valuenow={stepIndex + 1}
        aria-valuemin={1}
        aria-valuemax={STEPS.length}
        aria-label="Goal setup progress"
      >
        {STEPS.map((s, i) => {
          const isActive = i === stepIndex;
          const isDone = i < stepIndex;
          return (
            <div key={s} className="flex-1 flex items-center gap-2">
              <div
                className={cn(
                  "h-1 flex-1 rounded-full transition-colors duration-300",
                  isDone || isActive ? "bg-primary" : "bg-foreground/10",
                )}
              />
              <span
                className={cn(
                  "text-xs font-medium tabular-nums transition-colors",
                  isActive ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {String(i + 1).padStart(2, "0")}
              </span>
            </div>
          );
        })}
      </div>

      {/* Step content */}
      <div className="min-h-[360px]">
        <AnimatePresence mode="wait" custom={direction}>
          <motion.div
            key={step}
            initial={prefersReducedMotion ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={prefersReducedMotion ? undefined : { opacity: 0, y: -12 }}
            transition={{ duration: 0.28, ease: [0.25, 0.46, 0.45, 0.94] }}
          >
            {step === "motivation" && (
              <section aria-labelledby="motivation-heading">
                <h2
                  id="motivation-heading"
                  className="text-2xl font-semibold tracking-tight"
                >
                  Why are you here?
                </h2>
                <p className="mt-2 text-sm text-muted-foreground">
                  We tailor your path to your reason. You can change this later.
                </p>
                <div
                  className="mt-6 space-y-2"
                  role="radiogroup"
                  aria-labelledby="motivation-heading"
                >
                  {MOTIVATIONS.map((m) => {
                    const active = motivation === m.value;
                    const Icon = m.icon;
                    return (
                      <button
                        key={m.value}
                        type="button"
                        role="radio"
                        aria-checked={active}
                        onClick={() => setMotivation(m.value)}
                        className={cn(
                          "group w-full rounded-xl border text-left p-4 flex items-start gap-3 transition-all outline-none",
                          "focus-visible:ring-3 focus-visible:ring-ring/50",
                          active
                            ? "border-primary/60 bg-primary/[0.06] shadow-[0_0_0_1px_rgba(94,106,210,0.35)]"
                            : "border-foreground/10 hover:border-foreground/20 hover:bg-foreground/[0.02]",
                        )}
                      >
                        <div
                          className={cn(
                            "mt-0.5 rounded-lg p-2 transition-colors",
                            active
                              ? "bg-primary/15 text-primary"
                              : "bg-foreground/[0.04] text-muted-foreground group-hover:text-foreground",
                          )}
                        >
                          <Icon className="h-4 w-4" aria-hidden="true" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium leading-snug">
                            {m.label}
                          </p>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {m.helper}
                          </p>
                        </div>
                        {active && (
                          <Check
                            className="h-4 w-4 text-primary shrink-0 mt-0.5"
                            aria-hidden="true"
                          />
                        )}
                      </button>
                    );
                  })}
                </div>
              </section>
            )}

            {step === "deadline" && (
              <section aria-labelledby="deadline-heading">
                <h2
                  id="deadline-heading"
                  className="text-2xl font-semibold tracking-tight"
                >
                  When do you want to be there?
                </h2>
                <p className="mt-2 text-sm text-muted-foreground">
                  A deadline turns a wish into a plan. Pick a realistic window.
                </p>
                <div
                  className="mt-6 grid grid-cols-2 gap-3"
                  role="radiogroup"
                  aria-labelledby="deadline-heading"
                >
                  {DEADLINE_PRESETS.map((preset) => {
                    const active = deadline === preset.value;
                    return (
                      <button
                        key={preset.value}
                        type="button"
                        role="radio"
                        aria-checked={active}
                        onClick={() => setDeadline(preset.value)}
                        className={cn(
                          "rounded-xl border text-left p-4 transition-all outline-none",
                          "focus-visible:ring-3 focus-visible:ring-ring/50",
                          active
                            ? "border-primary/60 bg-primary/[0.06] shadow-[0_0_0_1px_rgba(94,106,210,0.35)]"
                            : "border-foreground/10 hover:border-foreground/20 hover:bg-foreground/[0.02]",
                        )}
                      >
                        <p className="text-lg font-semibold tabular-nums">
                          {preset.label}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {preset.helper}
                        </p>
                      </button>
                    );
                  })}
                </div>
                <div className="mt-6 flex items-center gap-3">
                  <label
                    htmlFor="custom-deadline"
                    className="text-xs text-muted-foreground"
                  >
                    Or custom
                  </label>
                  <input
                    id="custom-deadline"
                    type="number"
                    min={1}
                    max={60}
                    inputMode="numeric"
                    value={
                      deadline !== null &&
                      !DEADLINE_PRESETS.some((p) => p.value === deadline)
                        ? deadline
                        : ""
                    }
                    onChange={(e) => {
                      const v = parseInt(e.target.value, 10);
                      if (Number.isFinite(v) && v >= 1 && v <= 60) {
                        setDeadline(v);
                      } else if (e.target.value === "") {
                        setDeadline(null);
                      }
                    }}
                    placeholder="months"
                    className="h-8 w-28 rounded-lg border border-foreground/10 bg-transparent px-2.5 text-sm tabular-nums outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  />
                  <span className="text-xs text-muted-foreground">
                    months (1–60)
                  </span>
                </div>
              </section>
            )}

            {step === "success" && (
              <section aria-labelledby="success-heading">
                <h2
                  id="success-heading"
                  className="text-2xl font-semibold tracking-tight"
                >
                  Finish this sentence
                </h2>
                <p className="mt-2 text-sm text-muted-foreground">
                  &ldquo;In {deadline ?? "X"} months, I&rsquo;ll know I&rsquo;ve
                  succeeded when&hellip;&rdquo;
                </p>
                <textarea
                  id="success-statement"
                  value={successStatement}
                  onChange={(e) => setSuccessStatement(e.target.value)}
                  rows={5}
                  maxLength={500}
                  placeholder="…I can ship a production RAG system end-to-end, with retrieval quality I'd defend in a code review."
                  className="mt-6 w-full rounded-xl border border-foreground/10 bg-transparent p-4 text-sm leading-relaxed outline-none transition-colors resize-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 placeholder:text-muted-foreground/70"
                  aria-describedby="success-helper"
                />
                <div
                  id="success-helper"
                  className="mt-2 flex items-center justify-between text-xs text-muted-foreground"
                >
                  <span>
                    Specific beats ambitious. Concrete beats poetic.
                  </span>
                  <span className="tabular-nums">
                    {successStatement.length}/500
                  </span>
                </div>
              </section>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Error */}
      {error && (
        <p
          role="alert"
          className="mt-4 text-sm text-destructive"
        >
          {error}
        </p>
      )}

      {/* Controls */}
      <div className="mt-10 flex items-center justify-between">
        <Button
          variant="ghost"
          size="default"
          onClick={back}
          disabled={stepIndex === 0 || submitting}
          aria-label="Previous step"
        >
          <ArrowLeft className="h-3.5 w-3.5" data-icon="inline-start" />
          Back
        </Button>
        {step !== "success" ? (
          <Button
            variant="default"
            size="default"
            onClick={next}
            disabled={!canAdvance()}
            aria-label="Next step"
          >
            Next
            <ArrowRight className="h-3.5 w-3.5" data-icon="inline-end" />
          </Button>
        ) : (
          <Button
            variant="default"
            size="default"
            onClick={handleSubmit}
            disabled={!canAdvance() || submitting}
            aria-label={submitLabel}
          >
            {submitting ? (
              <Loader2
                className="h-3.5 w-3.5 animate-spin"
                data-icon="inline-start"
                aria-hidden="true"
              />
            ) : null}
            {submitLabel}
          </Button>
        )}
      </div>
    </div>
  );
}
