/**
 * Path screen — verifies the rewire to /api/v1/path/summary:
 *  - constellation renders all 6 stars from the aggregator
 *  - active level shows real lesson titles + duration_minutes
 *  - lab tray expands on the current lesson and lists real labs
 *  - upsell rung shows the price from `unlock_price_cents`
 *  - proof wall shows real submissions, not Priya/Marcus mocks
 *  - blank user (no levels with state="current") shows the "browse catalog"
 *    fallback instead of fake DEFAULT_LESSONS
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { PathScreen } from "@/components/v8/screens/path-screen";
import type { PathSummaryResponse } from "@/lib/api-client";

const mockPathSummary = vi.fn();

vi.mock("@/lib/hooks/use-path-summary", () => ({
  usePathSummary: () => mockPathSummary(),
}));

vi.mock("@/components/v8/v8-topbar-context", () => ({
  useSetV8Topbar: vi.fn(),
}));

vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) => {
    const state = { isAuthenticated: true };
    return selector ? selector(state) : state;
  },
}));

const mockRouterPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}));

function makeSummary(overrides: Partial<PathSummaryResponse> = {}): PathSummaryResponse {
  return {
    overall_progress: 33,
    active_course_id: "course-1",
    active_course_title: "Python Foundations",
    constellation: [
      { label: "Python\nDeveloper", sub: "Mastered", state: "done", badge: "1" },
      { label: "Data\nAnalyst", sub: "In progress", state: "current", badge: "2" },
      { label: "Data\nScientist", sub: "Upcoming", state: "upcoming", badge: "3" },
      { label: "ML\nEngineer", sub: "Upcoming", state: "upcoming", badge: "4" },
      { label: "GenAI\nEngineer", sub: "Upcoming", state: "upcoming", badge: "5" },
      { label: "Senior\nGenAI Eng.", sub: "Destination", state: "goal", badge: "★" },
    ],
    levels: [
      {
        badge: "1",
        title: "Python Foundations",
        blurb: "The role you are solidifying.",
        progress_percentage: 33,
        state: "current",
        unlock_course_id: null,
        unlock_price_cents: null,
        unlock_currency: null,
        unlock_lesson_count: null,
        unlock_lab_count: null,
        lessons: [
          {
            id: "l1",
            title: "Python fundamentals",
            meta: "Required · complete · 2 labs finished",
            duration_minutes: 45,
            status: "done",
            labs: [],
            labs_completed: 2,
          },
          {
            id: "l2",
            title: "APIs and async programming",
            meta: "Required · today · 2 labs · tap to expand",
            duration_minutes: 50,
            status: "current",
            labs: [
              {
                id: "lab-a",
                title: "Lab A · Retry with backoff",
                description: "Retry a flaky API.",
                duration_minutes: 25,
                status: "done",
              },
              {
                id: "lab-b",
                title: "Lab B · Rate-limit queue",
                description: "Throttle requests.",
                duration_minutes: 40,
                status: "current",
              },
            ],
            labs_completed: 1,
          },
        ],
      },
      {
        badge: "2",
        title: "Data Analyst Path",
        blurb: "SQL + pandas.",
        progress_percentage: 0,
        state: "upcoming",
        unlock_course_id: "course-2",
        unlock_price_cents: 8900,
        unlock_currency: "USD",
        unlock_lesson_count: 8,
        unlock_lab_count: 22,
        lessons: [],
      },
      {
        badge: "★",
        title: "Senior GenAI Engineer",
        blurb: "Agentic systems, production RAG.",
        progress_percentage: 0,
        state: "goal",
        unlock_course_id: null,
        unlock_price_cents: null,
        unlock_currency: null,
        unlock_lesson_count: null,
        unlock_lab_count: null,
        lessons: [],
      },
    ],
    proof_wall: [
      {
        submission_id: "sub-1",
        code_snippet: "async def ask():\n    return 1",
        author_name: "Ada Lovelace",
        score: 91,
        promoted: true,
      },
    ],
    ...overrides,
  };
}

describe("PathScreen", () => {
  it("renders the constellation from the aggregator (no DEFAULT_STARS)", () => {
    mockPathSummary.mockReturnValue({
      data: makeSummary(),
      isLoading: false,
    });
    render(<PathScreen />);
    // Goal star copy comes from `target_role` — appears in both the
    // constellation tile and the level title.
    expect(screen.getAllByText(/Senior/).length).toBeGreaterThanOrEqual(1);
    // 6 stars total — 5 ordered + 1 goal.
    expect(screen.getAllByText(/Mastered|In progress|Upcoming|Destination/i)).toHaveLength(6);
  });

  it("renders real lesson titles + durations from the payload", () => {
    mockPathSummary.mockReturnValue({
      data: makeSummary(),
      isLoading: false,
    });
    render(<PathScreen />);
    expect(screen.getByText("Python fundamentals")).toBeInTheDocument();
    expect(screen.getByText("APIs and async programming")).toBeInTheDocument();
    // Duration text "50m" — derived from duration_minutes.
    expect(screen.getByText("50m")).toBeInTheDocument();
  });

  it("expands the lab tray on the current lesson and lists real labs", () => {
    mockPathSummary.mockReturnValue({
      data: makeSummary(),
      isLoading: false,
    });
    render(<PathScreen />);
    const currentLesson = screen.getByText("APIs and async programming");
    fireEvent.click(currentLesson);
    expect(screen.getByText("Lab A · Retry with backoff")).toBeInTheDocument();
    expect(screen.getByText("Lab B · Rate-limit queue")).toBeInTheDocument();
    // Real labs only — Lab C is no longer hardcoded.
    expect(
      screen.queryByText(/Concurrent batch processor/),
    ).not.toBeInTheDocument();
  });

  it("renders the upsell price from unlock_price_cents (no $89 lie)", () => {
    mockPathSummary.mockReturnValue({
      data: makeSummary(),
      isLoading: false,
    });
    render(<PathScreen />);
    expect(screen.getByText("Data Analyst Path")).toBeInTheDocument();
    // Price is split across spans (cur + amt) — match the numeric portion.
    expect(
      screen.getByText((_, node) => node?.textContent === "$89one time"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/8 lessons · 22 labs/),
    ).toBeInTheDocument();
  });

  it("renders proof wall from peer submissions (not Priya/Marcus)", () => {
    mockPathSummary.mockReturnValue({
      data: makeSummary(),
      isLoading: false,
    });
    render(<PathScreen />);
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("91/100 · promoted")).toBeInTheDocument();
    expect(screen.queryByText(/Priya V/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Marcus K/)).not.toBeInTheDocument();
  });

  it("shows browse-catalog fallback when no current level exists", () => {
    mockPathSummary.mockReturnValue({
      data: makeSummary({ levels: [makeSummary().levels[2]] }),
      isLoading: false,
    });
    render(<PathScreen />);
    expect(screen.getByText("Pick a starting course")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /browse the catalog/i }))
      .toBeInTheDocument();
  });

  it("shows empty proof-wall message when no peer submissions exist", () => {
    mockPathSummary.mockReturnValue({
      data: makeSummary({ proof_wall: [] }),
      isLoading: false,
    });
    render(<PathScreen />);
    expect(
      screen.getByText(/No peer-shared submissions yet/),
    ).toBeInTheDocument();
  });
});
