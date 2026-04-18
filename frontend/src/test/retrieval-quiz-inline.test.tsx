import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { RetrievalQuizInline } from "@/components/features/retrieval-quiz-inline";

const mockGet = vi.fn();
const mockSubmit = vi.fn();

vi.mock("@/lib/api-client", async (orig) => {
  const actual = (await orig()) as Record<string, unknown>;
  return {
    ...actual,
    retrievalQuizApi: {
      get: (...args: unknown[]) => mockGet(...args),
      submit: (...args: unknown[]) => mockSubmit(...args),
    },
  };
});

describe("RetrievalQuizInline", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockSubmit.mockReset();
  });

  const QUESTIONS = [
    {
      id: "q1",
      question: "What is 2+2?",
      options: { A: "3", B: "4", C: "5" },
    },
    {
      id: "q2",
      question: "First letter?",
      options: { A: "A", B: "Z" },
    },
  ];

  it("renders the reflection fallback when no questions are returned", async () => {
    mockGet.mockResolvedValueOnce({ questions: [] });
    render(<RetrievalQuizInline lessonId="lesson-1" />);
    expect(await screen.findByText(/quick reflection/i)).toBeInTheDocument();
  });

  it("disables the grade button until every question is answered, then submits", async () => {
    mockGet.mockResolvedValueOnce({ questions: QUESTIONS });
    mockSubmit.mockResolvedValueOnce({
      correct: 2,
      total: 2,
      graded: [
        { mcq_id: "q1", correct: true, correct_answer: "B", explanation: null },
        { mcq_id: "q2", correct: true, correct_answer: "A", explanation: null },
      ],
    });

    render(<RetrievalQuizInline lessonId="lesson-1" />);
    const checkBtn = await screen.findByRole("button", { name: /check answers/i });
    expect(checkBtn).toBeDisabled();

    // Answer q1 (first radiogroup, first radio)
    const q1Group = screen.getByRole("radiogroup", { name: /question 1 options/i });
    const q1Radios = q1Group.querySelectorAll('[role="radio"]');
    fireEvent.click(q1Radios[0]);
    expect(checkBtn).toBeDisabled();

    // Answer q2 (second radiogroup, first radio)
    const q2Group = screen.getByRole("radiogroup", { name: /question 2 options/i });
    const q2Radios = q2Group.querySelectorAll('[role="radio"]');
    fireEvent.click(q2Radios[0]);

    expect(checkBtn).not.toBeDisabled();
    fireEvent.click(checkBtn);

    await waitFor(() =>
      expect(screen.getByText(/2 \/ 2 correct/i)).toBeInTheDocument(),
    );
    expect(mockSubmit).toHaveBeenCalled();
  });
});
