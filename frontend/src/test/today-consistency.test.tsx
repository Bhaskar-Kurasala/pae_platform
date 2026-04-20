import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import { TodayConsistency } from "@/components/features/today-consistency";

const mockUseConsistency = vi.fn();

vi.mock("@/lib/hooks/use-today", () => ({
  useConsistency: () => mockUseConsistency(),
}));

describe("TodayConsistency", () => {
  beforeEach(() => {
    mockUseConsistency.mockReset();
  });

  it("renders X of Y days and the right percent", () => {
    mockUseConsistency.mockReturnValue({
      data: { days_this_week: 4, window_days: 7 },
      isLoading: false,
    });
    render(<TodayConsistency />);
    expect(screen.getByText(/4 of 7 days/i)).toBeInTheDocument();
    expect(screen.getByText("57%")).toBeInTheDocument();
  });

  it("renders an activity track with the right number of filled cells", () => {
    mockUseConsistency.mockReturnValue({
      data: { days_this_week: 3, window_days: 7 },
      isLoading: false,
    });
    render(<TodayConsistency />);
    const list = screen.getByRole("list", { name: /activity this week/i });
    const items = list.querySelectorAll('[role="listitem"]');
    expect(items).toHaveLength(7);
    const active = list.querySelectorAll(".bg-primary");
    expect(active).toHaveLength(3);
  });
});
