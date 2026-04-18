import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { TodayIntention } from "@/components/features/today-intention";

const mockUseMyIntention = vi.fn();
const mockMutate = vi.fn();

vi.mock("@/lib/hooks/use-today", () => ({
  useMyIntention: () => mockUseMyIntention(),
  useSetIntention: () => ({
    mutate: mockMutate,
    isPending: false,
  }),
}));

vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("TodayIntention", () => {
  beforeEach(() => {
    mockUseMyIntention.mockReset();
    mockMutate.mockReset();
  });

  it("shows the empty-state prompt when no intention is saved", () => {
    mockUseMyIntention.mockReturnValue({ data: null, isLoading: false });
    render(<TodayIntention />);
    expect(
      screen.getByRole("heading", { name: /what do you want from today/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/daily intention/i)).toBeInTheDocument();
  });

  it("disables the save button until text is entered, then calls mutate", () => {
    mockUseMyIntention.mockReturnValue({ data: null, isLoading: false });
    render(<TodayIntention />);

    const saveBtn = screen.getByRole("button", { name: /set intention/i });
    expect(saveBtn).toBeDisabled();

    const textarea = screen.getByLabelText(/daily intention/i);
    fireEvent.change(textarea, { target: { value: "Ship the intention card" } });

    expect(saveBtn).not.toBeDisabled();
    fireEvent.click(saveBtn);

    expect(mockMutate).toHaveBeenCalledWith(
      "Ship the intention card",
      expect.any(Object),
    );
  });

  it("renders the stored intention and an edit button", () => {
    mockUseMyIntention.mockReturnValue({
      data: {
        id: "i1",
        user_id: "u1",
        intention_date: "2026-04-18",
        text: "Finish the 3A batch",
        created_at: "2026-04-18T08:00:00Z",
        updated_at: "2026-04-18T08:00:00Z",
      },
      isLoading: false,
    });
    render(<TodayIntention />);

    expect(screen.getByText("Finish the 3A batch")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument();
  });
});
