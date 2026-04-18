import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import { TodayMicroWins } from "@/components/features/today-micro-wins";

const mockUseMicroWins = vi.fn();

vi.mock("@/lib/hooks/use-today", () => ({
  useMicroWins: () => mockUseMicroWins(),
}));

describe("TodayMicroWins", () => {
  beforeEach(() => {
    mockUseMicroWins.mockReset();
  });

  it("renders the empty-state copy when there are no wins yet", () => {
    mockUseMicroWins.mockReturnValue({
      data: { wins: [] },
      isLoading: false,
    });
    render(<TodayMicroWins />);
    expect(screen.getByText(/your wins will show up here/i)).toBeInTheDocument();
  });

  it("lists wins with labels when they exist", () => {
    const now = new Date().toISOString();
    mockUseMicroWins.mockReturnValue({
      data: {
        wins: [
          { kind: "lesson_completed", label: "Finished: Async Python", occurred_at: now },
          { kind: "quiz_perfect", label: "Perfect quiz: Promises", occurred_at: now },
        ],
      },
      isLoading: false,
    });
    render(<TodayMicroWins />);
    expect(screen.getByText(/2 small wins this week/i)).toBeInTheDocument();
    expect(screen.getByText(/finished: async python/i)).toBeInTheDocument();
    expect(screen.getByText(/perfect quiz: promises/i)).toBeInTheDocument();
  });
});
