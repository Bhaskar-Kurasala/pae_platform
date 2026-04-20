"use client";

import { useState } from "react";
import { useInterviewQuestions } from "@/lib/hooks/use-career";
import {
  useStartSession,
  useSubmitAnswer,
  useCompleteSession,
  useStories,
  useCreateStory,
  useDeleteStory,
  type InterviewMode,
  type RubricScores,
  type AnswerResponse,
  type SessionStartResponse,
  type StoryInput,
} from "@/lib/hooks/use-interview";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import { PageShell } from "@/components/layouts/page-shell";
import { PageHeader } from "@/components/layouts/page-header";

// ── Types ────────────────────────────────────────────────────────

type SessionPhase = "start" | "active" | "reviewing" | "done";

interface ActiveSession {
  id: string;
  mode: InterviewMode;
  currentQuestion: string;
  questionCount: number;
  lastEval: AnswerResponse | null;
  finalScore: number | null;
}

// ── Mode Selector ────────────────────────────────────────────────

const MODES: { value: InterviewMode; label: string; description: string }[] = [
  {
    value: "behavioral",
    label: "Behavioral",
    description: "STAR-format questions about past experience and soft skills.",
  },
  {
    value: "technical",
    label: "Technical",
    description: "Coding concepts, algorithms, and system fundamentals.",
  },
  {
    value: "system_design",
    label: "System Design",
    description: "Architecture, scalability, and trade-off discussions.",
  },
];

// ── Rubric Score Panel ───────────────────────────────────────────

const RUBRIC_LABELS: Record<keyof RubricScores, string> = {
  clarity: "Clarity",
  structure: "Structure",
  depth: "Depth",
  evidence: "Evidence",
  confidence_language: "Confidence Language",
};

function RubricPanel({ eval: evalData }: { eval: AnswerResponse }) {
  const { scores, overall, feedback, tip } = evalData;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <span className="text-4xl font-bold tabular-nums">{overall.toFixed(1)}</span>
        <span className="text-muted-foreground text-lg">/ 10</span>
        <span className="ml-auto text-sm text-muted-foreground">Overall score</span>
      </div>

      <div className="space-y-2">
        {(Object.keys(scores) as Array<keyof RubricScores>).map((dim) => (
          <div key={dim} className="space-y-1">
            <div className="flex justify-between text-sm">
              <span>{RUBRIC_LABELS[dim]}</span>
              <span className="tabular-nums text-muted-foreground">
                {scores[dim]}/10
              </span>
            </div>
            <Progress
              value={scores[dim] * 10}
              aria-label={`${RUBRIC_LABELS[dim]} score: ${scores[dim]} out of 10`}
              className="h-2"
            />
          </div>
        ))}
      </div>

      {feedback && (
        <div className="rounded-md bg-muted p-3 text-sm">
          <p className="font-medium mb-1">Feedback</p>
          <p className="text-muted-foreground leading-relaxed">{feedback}</p>
        </div>
      )}

      {tip && (
        <div className="rounded-md bg-amber-50 border border-amber-200 p-3 text-sm dark:bg-amber-950/30 dark:border-amber-800">
          <p className="font-medium text-amber-800 dark:text-amber-300 mb-1">Tip</p>
          <p className="text-amber-700 dark:text-amber-400 leading-relaxed">{tip}</p>
        </div>
      )}
    </div>
  );
}

// ── Tab 1: Mock Interview ────────────────────────────────────────

function MockInterviewTab() {
  const [phase, setPhase] = useState<SessionPhase>("start");
  const [selectedMode, setSelectedMode] = useState<InterviewMode | null>(null);
  const [topic, setTopic] = useState("");
  const [session, setSession] = useState<ActiveSession | null>(null);
  const [answer, setAnswer] = useState("");

  const startSession = useStartSession();
  const submitAnswer = useSubmitAnswer();
  const completeSession = useCompleteSession();

  function handleStart() {
    if (!selectedMode) return;
    startSession.mutate(
      { mode: selectedMode, topic: topic.trim() || undefined },
      {
        onSuccess: (data: SessionStartResponse) => {
          setSession({
            id: data.id,
            mode: data.mode,
            currentQuestion: data.first_question,
            questionCount: 1,
            lastEval: null,
            finalScore: null,
          });
          setPhase("active");
          setAnswer("");
        },
      },
    );
  }

  function handleSubmitAnswer() {
    if (!session || !answer.trim()) return;
    submitAnswer.mutate(
      {
        session_id: session.id,
        question: session.currentQuestion,
        answer: answer.trim(),
      },
      {
        onSuccess: (data: AnswerResponse) => {
          setSession((prev) =>
            prev
              ? {
                  ...prev,
                  lastEval: data,
                  currentQuestion: data.next_question ?? prev.currentQuestion,
                  questionCount: data.next_question
                    ? prev.questionCount + 1
                    : prev.questionCount,
                }
              : prev,
          );
          setAnswer("");
          setPhase("reviewing");
        },
      },
    );
  }

  function handleNextQuestion() {
    setPhase("active");
  }

  function handleEndInterview() {
    if (!session) return;
    completeSession.mutate(session.id, {
      onSuccess: (data) => {
        setSession((prev) =>
          prev ? { ...prev, finalScore: data.overall_score } : prev,
        );
        setPhase("done");
      },
    });
  }

  function handleReset() {
    setPhase("start");
    setSession(null);
    setSelectedMode(null);
    setTopic("");
    setAnswer("");
  }

  // ── Start Screen ───────────────────────────────────────────────
  if (phase === "start") {
    return (
      <div className="space-y-6">
        <div>
          <p className="text-sm font-medium mb-3">Select interview mode</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {MODES.map((m) => (
              <button
                key={m.value}
                type="button"
                aria-label={`Select ${m.label} interview mode`}
                aria-pressed={selectedMode === m.value}
                onClick={() => setSelectedMode(m.value)}
                className={[
                  "rounded-lg border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  selectedMode === m.value
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-muted-foreground/50",
                ].join(" ")}
              >
                <p className="font-semibold text-sm mb-1">{m.label}</p>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {m.description}
                </p>
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="interview-topic" className="text-sm font-medium">
            Topic <span className="text-muted-foreground font-normal">(optional)</span>
          </label>
          <Input
            id="interview-topic"
            placeholder="e.g. distributed systems, LLM fine-tuning, leadership…"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            aria-label="Optional topic for the interview"
          />
        </div>

        <Button
          onClick={handleStart}
          disabled={!selectedMode || startSession.isPending}
          aria-label="Start mock interview"
          className="w-full sm:w-auto"
        >
          {startSession.isPending ? "Starting…" : "Start Interview"}
        </Button>

        {startSession.isError && (
          <p className="text-sm text-destructive" role="alert">
            {startSession.error?.message ?? "Failed to start session."}
          </p>
        )}
      </div>
    );
  }

  // ── Done Screen ────────────────────────────────────────────────
  if (phase === "done" && session) {
    return (
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Interview Complete</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-3">
              <span className="text-5xl font-bold tabular-nums">
                {session.finalScore !== null
                  ? session.finalScore.toFixed(1)
                  : "—"}
              </span>
              <span className="text-muted-foreground text-xl">/ 10</span>
            </div>
            <p className="text-sm text-muted-foreground">
              You answered {session.questionCount} question
              {session.questionCount !== 1 ? "s" : ""} in{" "}
              <span className="capitalize">{session.mode.replace("_", " ")}</span>{" "}
              mode.
            </p>
            <Button
              onClick={handleReset}
              aria-label="Start a new interview session"
              variant="outline"
            >
              Start New Interview
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ── Active + Reviewing ─────────────────────────────────────────
  if (!session) return null;

  return (
    <div className="space-y-5">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="capitalize">
            {session.mode.replace("_", " ")}
          </Badge>
          <span className="text-sm text-muted-foreground">
            Question {session.questionCount}
          </span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleEndInterview}
          disabled={completeSession.isPending}
          aria-label="End interview session and see final score"
        >
          {completeSession.isPending ? "Finishing…" : "End Interview"}
        </Button>
      </div>

      {/* Question bubble */}
      <div className="rounded-lg bg-muted/60 border p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">
          Question
        </p>
        <p className="text-sm leading-relaxed font-medium">
          {session.currentQuestion}
        </p>
      </div>

      {/* Rubric panel after answer submission */}
      {phase === "reviewing" && session.lastEval && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Evaluation</CardTitle>
          </CardHeader>
          <CardContent>
            <RubricPanel eval={session.lastEval} />
          </CardContent>
        </Card>
      )}

      {/* Answer area */}
      {phase === "active" && (
        <div className="space-y-3">
          <Textarea
            placeholder="Type your answer here…"
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            rows={5}
            aria-label="Your answer to the interview question"
            className="resize-y"
          />
          <div className="flex items-center gap-3">
            <Button
              onClick={handleSubmitAnswer}
              disabled={!answer.trim() || submitAnswer.isPending}
              aria-label="Submit your answer for evaluation"
            >
              {submitAnswer.isPending ? "Evaluating…" : "Submit Answer"}
            </Button>
          </div>
          {submitAnswer.isError && (
            <p className="text-sm text-destructive" role="alert">
              {submitAnswer.error?.message ?? "Failed to submit answer."}
            </p>
          )}
        </div>
      )}

      {/* Next question CTA */}
      {phase === "reviewing" && session.lastEval?.next_question && (
        <div className="flex gap-3">
          <Button
            onClick={handleNextQuestion}
            aria-label="Continue to next question"
          >
            Next Question
          </Button>
          <Button
            variant="outline"
            onClick={handleEndInterview}
            disabled={completeSession.isPending}
            aria-label="End interview session"
          >
            End Interview
          </Button>
        </div>
      )}

      {/* No next question — wrap up prompt */}
      {phase === "reviewing" && !session.lastEval?.next_question && (
        <Button
          onClick={handleEndInterview}
          disabled={completeSession.isPending}
          aria-label="Complete the interview and view your score"
        >
          {completeSession.isPending ? "Finishing…" : "Complete Interview"}
        </Button>
      )}

      {completeSession.isError && (
        <p className="text-sm text-destructive" role="alert">
          {completeSession.error?.message ?? "Failed to complete session."}
        </p>
      )}
    </div>
  );
}

// ── Tab 2: Question Bank ─────────────────────────────────────────

function QuestionBankTab() {
  const [query, setQuery] = useState("");
  const { data: questions = [], isLoading } = useInterviewQuestions(query);

  return (
    <div className="space-y-4">
      <Input
        placeholder="Search questions…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Search interview questions"
      />
      {isLoading && (
        <p className="text-sm text-muted-foreground">Searching…</p>
      )}
      {questions.length === 0 && !isLoading && (
        <p className="text-sm text-muted-foreground">
          No questions found. Questions are added as you progress through
          courses.
        </p>
      )}
      <ul className="space-y-3">
        {questions.map((q) => (
          <li key={q.id}>
            <Card>
              <CardContent className="p-4">
                <div className="mb-1 flex items-center gap-2">
                  <Badge variant="secondary" className="text-[10px] capitalize">
                    {q.difficulty}
                  </Badge>
                  <Badge variant="outline" className="text-[10px] capitalize">
                    {q.category}
                  </Badge>
                </div>
                <p className="text-sm font-medium">{q.question}</p>
                {q.answer_hint && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {q.answer_hint}
                  </p>
                )}
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Tab 3: Story Bank ────────────────────────────────────────────

const EMPTY_STORY_FORM: StoryInput = {
  title: "",
  situation: "",
  task: "",
  action: "",
  result: "",
  tags: [],
};

function StoryBankTab() {
  const { data: stories = [], isLoading } = useStories();
  const createStory = useCreateStory();
  const deleteStory = useDeleteStory();

  const [form, setForm] = useState<StoryInput>(EMPTY_STORY_FORM);
  const [tagsInput, setTagsInput] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  function setField(field: keyof StoryInput, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const tags = tagsInput
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    createStory.mutate(
      { ...form, tags },
      {
        onSuccess: () => {
          setForm(EMPTY_STORY_FORM);
          setTagsInput("");
          setShowForm(false);
        },
      },
    );
  }

  const isFormValid =
    form.title.trim() &&
    form.situation.trim() &&
    form.task.trim() &&
    form.action.trim() &&
    form.result.trim();

  return (
    <div className="space-y-5">
      {/* Add story toggle */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {stories.length} stor{stories.length === 1 ? "y" : "ies"} saved
        </p>
        <Button
          variant={showForm ? "outline" : "default"}
          size="sm"
          onClick={() => setShowForm((v) => !v)}
          aria-label={showForm ? "Cancel adding story" : "Add a new STAR story"}
        >
          {showForm ? "Cancel" : "Add Story"}
        </Button>
      </div>

      {/* Add story form */}
      {showForm && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">New STAR Story</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label htmlFor="story-title" className="text-sm font-medium">
                  Title
                </label>
                <Input
                  id="story-title"
                  placeholder="e.g. Led cross-team migration to microservices"
                  value={form.title}
                  onChange={(e) => setField("title", e.target.value)}
                  aria-label="Story title"
                  required
                />
              </div>

              {(
                [
                  ["situation", "Situation", "What was the context or background?"],
                  ["task", "Task", "What was your responsibility or challenge?"],
                  ["action", "Action", "What specific steps did you take?"],
                  ["result", "Result", "What was the outcome? Include metrics if possible."],
                ] as const
              ).map(([field, label, placeholder]) => (
                <div key={field} className="space-y-1.5">
                  <label
                    htmlFor={`story-${field}`}
                    className="text-sm font-medium"
                  >
                    {label}
                  </label>
                  <Textarea
                    id={`story-${field}`}
                    placeholder={placeholder}
                    value={form[field]}
                    onChange={(e) => setField(field, e.target.value)}
                    rows={3}
                    aria-label={`Story ${label.toLowerCase()}`}
                    required
                    className="resize-y"
                  />
                </div>
              ))}

              <div className="space-y-1.5">
                <label htmlFor="story-tags" className="text-sm font-medium">
                  Tags{" "}
                  <span className="text-muted-foreground font-normal">
                    (comma-separated)
                  </span>
                </label>
                <Input
                  id="story-tags"
                  placeholder="leadership, cross-functional, technical-debt"
                  value={tagsInput}
                  onChange={(e) => setTagsInput(e.target.value)}
                  aria-label="Story tags, comma-separated"
                />
              </div>

              {createStory.isError && (
                <p className="text-sm text-destructive" role="alert">
                  {createStory.error?.message ?? "Failed to save story."}
                </p>
              )}

              <Button
                type="submit"
                disabled={!isFormValid || createStory.isPending}
                aria-label="Save this STAR story"
              >
                {createStory.isPending ? "Saving…" : "Save Story"}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Stories list */}
      {isLoading && (
        <p className="text-sm text-muted-foreground">Loading stories…</p>
      )}

      {!isLoading && stories.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No stories yet. Add your first STAR story above.
        </p>
      )}

      <ul className="space-y-3">
        {stories.map((story) => {
          const isExpanded = expandedId === story.id;
          return (
            <li key={story.id}>
              <Card>
                <CardContent className="p-4">
                  {/* Collapsed header */}
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <button
                        type="button"
                        className="text-left w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
                        onClick={() =>
                          setExpandedId(isExpanded ? null : story.id)
                        }
                        aria-expanded={isExpanded}
                        aria-label={`${isExpanded ? "Collapse" : "Expand"} story: ${story.title}`}
                      >
                        <p className="font-medium text-sm">{story.title}</p>
                      </button>
                      {story.tags.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {story.tags.map((tag) => (
                            <Badge
                              key={tag}
                              variant="secondary"
                              className="text-[10px]"
                            >
                              {tag}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => deleteStory.mutate(story.id)}
                      disabled={deleteStory.isPending}
                      aria-label={`Delete story: ${story.title}`}
                      className="shrink-0 text-muted-foreground hover:text-destructive"
                    >
                      Delete
                    </Button>
                  </div>

                  {/* Expanded STAR content */}
                  {isExpanded && (
                    <div className="mt-4 space-y-3 border-t pt-4">
                      {(
                        [
                          ["Situation", story.situation],
                          ["Task", story.task],
                          ["Action", story.action],
                          ["Result", story.result],
                        ] as const
                      ).map(([label, text]) => (
                        <div key={label}>
                          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
                            {label}
                          </p>
                          <p className="text-sm leading-relaxed">{text}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────

export default function InterviewPrepPage() {
  return (
    <PageShell variant="default" density="comfortable" className="space-y-2">
      <PageHeader
        eyebrow="Career"
        title="Interview Prep"
        description="Practice live mock interviews, search the question bank, and build your STAR story library."
      />
      <Tabs defaultValue="mock" className="w-full">
        <TabsList aria-label="Interview prep sections" className="mb-6">
          <TabsTrigger value="mock" aria-label="Mock interview tab">
            Mock Interview
          </TabsTrigger>
          <TabsTrigger value="bank" aria-label="Question bank tab">
            Question Bank
          </TabsTrigger>
          <TabsTrigger value="stories" aria-label="Story bank tab">
            Story Bank
          </TabsTrigger>
        </TabsList>

        <TabsContent value="mock">
          <MockInterviewTab />
        </TabsContent>

        <TabsContent value="bank">
          <QuestionBankTab />
        </TabsContent>

        <TabsContent value="stories">
          <StoryBankTab />
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}
