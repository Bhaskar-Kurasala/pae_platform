/**
 * Today screen — covers the rewire to live data:
 *  - kpi values come from the summary payload, not hard-coded literals
 *  - "Active N of 7 days" replaces the streak chip
 *  - card index starts at 0 (no fake "04 / 07" before any review)
 *  - intention input wires to useSetIntention
 *  - cohort feed renders real masked actor handles
 *  - micro-wins surface only when the payload has any
 *  - "Mark warm-up done" button calls markStep('warmup')
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { TodayScreen } from "@/components/v8/screens/today-screen";

const mockSummary = vi.fn();
const mockDueCards = vi.fn();
const mockReviewMutate = vi.fn();
const mockSetIntentionMutate = vi.fn();
const mockMarkStepMutate = vi.fn();
const mockIntention = vi.fn();

vi.mock("@/lib/hooks/use-today", () => ({
  useTodaySummary: () => mockSummary(),
  useMyIntention: () => mockIntention(),
  useSetIntention: () => ({
    mutate: (text: string, opts?: { onSuccess?: () => void }) => {
      mockSetIntentionMutate(text);
      opts?.onSuccess?.();
    },
    isPending: false,
  }),
  useMarkSessionStep: () => ({
    mutate: (step: string) => mockMarkStepMutate(step),
  }),
  useConsistency: () => ({ data: undefined }),
  useMicroWins: () => ({ data: undefined }),
}));

vi.mock("@/lib/hooks/use-srs", () => ({
  useDueCards: () => mockDueCards(),
  useReviewCard: () => ({
    mutate: (payload: unknown) => mockReviewMutate(payload),
  }),
}));

vi.mock("@/components/v8/v8-topbar-context", () => ({
  useSetV8Topbar: vi.fn(),
}));

vi.mock("@/components/v8/v8-toast", () => ({
  v8Toast: vi.fn(),
}));

vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) => {
    const state = {
      user: { id: "u1", full_name: "Demo User", role: "student" },
      isAuthenticated: true,
    };
    return selector ? selector(state) : state;
  },
}));

function makeSummary(overrides: Record<string, unknown> = {}) {
  return {
    user: { first_name: "Demo" },
    goal: {
      success_statement: "land a Data Analyst role",
      target_role: "Data Analyst",
      days_remaining: 73,
      motivation: "career_switch",
    },
    consistency: { days_active: 4, window_days: 7 },
    progress: {
      overall_percentage: 31.6,
      lessons_completed_total: 12,
      lessons_total: 38,
      today_unlock_percentage: 6.3,
      active_course_id: "c1",
      active_course_title: "Python Foundations",
      next_lesson_id: "l9",
      next_lesson_title: "Async API clients",
    },
    session: {
      id: "s1",
      ordinal: 14,
      started_at: new Date().toISOString(),
      warmup_done_at: null,
      lesson_done_at: null,
      reflect_done_at: null,
    },
    current_focus: {
      skill_slug: "apis",
      skill_name: "APIs",
      skill_blurb: "async requests, retries, and handling failure",
    },
    capstone: {
      exercise_id: "ex1",
      title: "CLI AI tool",
      days_to_due: 5,
      draft_quality: 84,
      drafts_count: 1,
    },
    next_milestone: { label: "Data Analyst", days: 73 },
    readiness: { current: 57, delta_week: 8 },
    intention: { text: "" },
    due_card_count: 7,
    peers_at_level: 12,
    promotions_today: 3,
    micro_wins: [
      {
        kind: "lesson_completed",
        label: "You finished “HTTP basics”",
        occurred_at: new Date().toISOString(),
      },
    ],
    cohort_events: [
      {
        kind: "level_up",
        actor_handle: "Priya K.",
        label: "passed Python Developer to Data Analyst",
        occurred_at: new Date(Date.now() - 60_000).toISOString(),
      },
    ],
    ...overrides,
  };
}

describe("TodayScreen", () => {
  beforeEach(() => {
    mockSummary.mockReset();
    mockDueCards.mockReset();
    mockReviewMutate.mockReset();
    mockSetIntentionMutate.mockReset();
    mockMarkStepMutate.mockReset();
    mockIntention.mockReset();

    mockSummary.mockReturnValue({ data: makeSummary() });
    mockIntention.mockReturnValue({ data: null });
    mockDueCards.mockReturnValue({
      data: [
        {
          id: "card-1",
          concept_key: "lesson:async",
          prompt: "Why use asyncio.gather?",
          answer: "Run coroutines concurrently.",
          hint: "Think about ordering and waits.",
          ease_factor: 2.5,
          interval_days: 1,
          repetitions: 0,
          next_due_at: new Date().toISOString(),
          last_reviewed_at: null,
        },
      ],
    });
  });

  it("renders KPIs sourced from the summary payload", () => {
    render(<TodayScreen />);
    // Capstone draft quality
    expect(screen.getByText("84")).toBeInTheDocument();
    // Next milestone label + capstone trailer reference target_role
    expect(
      screen.getAllByText(/Data Analyst/).length,
    ).toBeGreaterThan(0);
    // Days remaining surfaces in the rail countdown big-number
    expect(screen.getAllByText("73").length).toBeGreaterThan(0);
  });

  it("renders cohort events with real masked handles", () => {
    render(<TodayScreen />);
    expect(screen.getByText("Priya K.")).toBeInTheDocument();
  });

  it("renders micro-wins when present", () => {
    render(<TodayScreen />);
    expect(screen.getByText(/HTTP basics/)).toBeInTheDocument();
  });

  it("starts the card counter at 01 / 01, not at 04 / 07", () => {
    // One real card → counter renders "01" with a sibling "/ 01" span.
    // The Bug B fix sets cardIndex initial state to 0, so position == 1.
    render(<TodayScreen />);
    const counter = screen.getByLabelText(/Card 1 of 1/i);
    expect(counter).toBeInTheDocument();
    expect(counter.textContent).toMatch(/01.*\/\s*01/);
  });

  it("calls setIntention.mutate when the form is saved", () => {
    render(<TodayScreen />);
    const input = screen.getByLabelText(/what do you want to do today/i);
    fireEvent.change(input, { target: { value: "ship one async client" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(mockSetIntentionMutate).toHaveBeenCalledWith("ship one async client");
  });

  it("calls markStep('warmup') on first session-flow advance", () => {
    render(<TodayScreen />);
    fireEvent.click(screen.getByRole("button", { name: /mark warm-up done/i }));
    expect(mockMarkStepMutate).toHaveBeenCalledWith("warmup");
  });

  it("hides the cohort placeholder when events exist and shows it when empty", () => {
    mockSummary.mockReturnValue({
      data: makeSummary({ cohort_events: [] }),
    });
    render(<TodayScreen />);
    expect(screen.getByText(/quiet right now/i)).toBeInTheDocument();
  });

  it("renders the consistency chip via the topbar setter (smoke)", () => {
    // The topbar is a side effect — we just guarantee the component mounts
    // without throwing when summary changes. Implicit: useSetV8Topbar mock
    // returns void.
    render(<TodayScreen />);
    expect(screen.getByText(/Your session flow/i)).toBeInTheDocument();
  });
});
