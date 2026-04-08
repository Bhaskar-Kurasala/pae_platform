import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CourseCard } from "@/components/features/course-card";
import { ProgressBar } from "@/components/features/progress-bar";
import { ChatMessageBubble, type ChatMessage } from "@/components/features/chat-message";
import { LessonItem } from "@/components/features/lesson-item";

// ── CourseCard ────────────────────────────────────────────────────────────────

describe("CourseCard", () => {
  const baseProps = {
    id: "course-123",
    title: "LangGraph in Production",
    difficulty: "intermediate",
    estimatedHours: 10,
  };

  it("renders course title", () => {
    render(<CourseCard {...baseProps} />);
    expect(screen.getByText("LangGraph in Production")).toBeInTheDocument();
  });

  it("renders difficulty badge", () => {
    render(<CourseCard {...baseProps} />);
    expect(screen.getByText("intermediate")).toBeInTheDocument();
  });

  it("shows Free badge when price is 0", () => {
    render(<CourseCard {...baseProps} priceCents={0} />);
    expect(screen.getByText("Free")).toBeInTheDocument();
  });

  it("shows price badge when paid", () => {
    render(<CourseCard {...baseProps} priceCents={9900} />);
    expect(screen.getByText("$99")).toBeInTheDocument();
  });

  it("shows estimated hours", () => {
    render(<CourseCard {...baseProps} />);
    expect(screen.getByText(/10h/)).toBeInTheDocument();
  });

  it("shows lesson count when provided", () => {
    render(<CourseCard {...baseProps} lessonCount={12} />);
    expect(screen.getByText(/12 lessons/)).toBeInTheDocument();
  });

  it("shows progress bar when progressPct > 0", () => {
    render(<CourseCard {...baseProps} progressPct={60} />);
    const progressBar = screen.getByRole("progressbar");
    expect(progressBar).toBeInTheDocument();
    expect(progressBar).toHaveAttribute("aria-valuenow", "60");
  });

  it("links to course detail page", () => {
    render(<CourseCard {...baseProps} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/courses/course-123");
  });
});

// ── ProgressBar ───────────────────────────────────────────────────────────────

describe("ProgressBar", () => {
  it("renders with correct aria attributes", () => {
    render(<ProgressBar value={75} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "75");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
  });

  it("displays percentage label", () => {
    render(<ProgressBar value={42} />);
    expect(screen.getByText("42%")).toBeInTheDocument();
  });

  it("clamps value to 0-100", () => {
    render(<ProgressBar value={150} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });

  it("clamps negative value to 0", () => {
    render(<ProgressBar value={-10} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });

  it("renders optional label", () => {
    render(<ProgressBar value={50} label="Course Progress" />);
    expect(screen.getByText("Course Progress")).toBeInTheDocument();
  });
});

// ── ChatMessageBubble ─────────────────────────────────────────────────────────

describe("ChatMessageBubble", () => {
  const userMsg: ChatMessage = {
    id: "msg-1",
    role: "user",
    content: "What is RAG?",
    timestamp: new Date("2026-01-01T12:00:00Z"),
  };

  const agentMsg: ChatMessage = {
    id: "msg-2",
    role: "assistant",
    content: "Great question! What do you think retrieval means in this context?",
    agentName: "socratic_tutor",
    evaluationScore: 0.9,
    timestamp: new Date("2026-01-01T12:00:05Z"),
  };

  it("renders user message content", () => {
    render(<ChatMessageBubble message={userMsg} />);
    expect(screen.getByText("What is RAG?")).toBeInTheDocument();
  });

  it("renders agent message content", () => {
    render(<ChatMessageBubble message={agentMsg} />);
    expect(screen.getByText(/Great question/)).toBeInTheDocument();
  });

  it("shows agent label for assistant messages", () => {
    render(<ChatMessageBubble message={agentMsg} />);
    expect(screen.getByText("Socratic Tutor")).toBeInTheDocument();
  });

  it("shows quality score for assistant messages", () => {
    render(<ChatMessageBubble message={agentMsg} />);
    expect(screen.getByText(/Quality: 90%/)).toBeInTheDocument();
  });

  it("does not show agent label for user messages", () => {
    render(<ChatMessageBubble message={userMsg} />);
    expect(screen.queryByText("Socratic Tutor")).not.toBeInTheDocument();
  });
});

// ── LessonItem ────────────────────────────────────────────────────────────────

describe("LessonItem", () => {
  const baseProps = {
    id: "lesson-1",
    title: "Intro to LangGraph",
    durationSeconds: 900,
    order: 1,
  };

  it("renders lesson title", () => {
    render(<LessonItem {...baseProps} />);
    expect(screen.getByText("Intro to LangGraph")).toBeInTheDocument();
  });

  it("renders duration", () => {
    render(<LessonItem {...baseProps} />);
    expect(screen.getByText(/15m/)).toBeInTheDocument();
  });

  it("shows order number", () => {
    render(<LessonItem {...baseProps} />);
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("shows completed checkmark when done", () => {
    render(<LessonItem {...baseProps} isCompleted />);
    expect(screen.getByLabelText("Completed")).toBeInTheDocument();
  });

  it("shows free preview label", () => {
    render(<LessonItem {...baseProps} isFreePreview />);
    expect(screen.getByText("Free preview")).toBeInTheDocument();
  });

  it("wraps in link when isPortal", () => {
    render(<LessonItem {...baseProps} isPortal />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/lessons/lesson-1");
  });

  it("does not wrap in link when not portal", () => {
    render(<LessonItem {...baseProps} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
