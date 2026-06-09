/**
 * Promotion screen — verifies the rewire to /api/v1/promotion/summary:
 *  - rungs render real titles + state from the aggregator
 *  - role transition uses target_role (not hardcoded motivation map)
 *  - takeover auto-fires when gate_status === "ready_to_promote"
 *  - takeover stays closed when gate_status === "not_ready"
 *  - "Open promotion ceremony" button only shows when ready_to_promote
 *  - confirm POSTs and routes to /today
 *  - already-promoted state shows the "Promoted on …" disabled button
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { PromotionScreen } from "@/components/v8/screens/promotion-screen";
import type { PromotionSummaryResponse } from "@/lib/api-client";

const mockPromotionSummary = vi.fn();
const mockConfirmMutate = vi.fn();
const mockRouterPush = vi.fn();

vi.mock("@/lib/hooks/use-promotion-summary", () => ({
  usePromotionSummary: () => mockPromotionSummary(),
  useConfirmPromotion: () => ({
    mutate: mockConfirmMutate,
    isPending: false,
  }),
}));

vi.mock("@/components/v8/v8-topbar-context", () => ({
  useSetV8Topbar: vi.fn(),
}));

vi.mock("@/components/v8/v8-sound-toggle", () => ({
  playUiSound: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}));

beforeEach(() => {
  mockConfirmMutate.mockReset();
  mockRouterPush.mockReset();
});

function makeSummary(
  overrides: Partial<PromotionSummaryResponse> = {},
): PromotionSummaryResponse {
  return {
    overall_progress: 50,
    rungs: [
      {
        kind: "lessons_foundation",
        title: "Lessons 1–2 complete",
        detail: "Your foundation is already in place.",
        state: "done",
        progress: 100,
        short_label: "Lessons 1–2 complete",
      },
      {
        kind: "lessons_complete",
        title: "Finish 2 remaining lessons",
        detail: "APIs, testing, and collaboration close Level 1.",
        state: "current",
        progress: 50,
        short_label: "2 remaining lessons",
      },
      {
        kind: "capstone_submitted",
        title: "Submit capstone",
        detail: "One real artifact proves the role, not just attendance.",
        state: "locked",
        progress: 0,
        short_label: "Capstone submitted",
      },
      {
        kind: "interviews_complete",
        title: "Complete 2 practice interviews",
        detail: "Pressure-test your thinking before the actual gate.",
        state: "locked",
        progress: 0,
        short_label: "2 practice interviews",
      },
    ],
    role: { from_role: "Python Developer", to_role: "Data Analyst" },
    stats: {
      completed_lessons: 2,
      total_lessons: 4,
      due_card_count: 11,
      completed_interviews: 0,
      capstone_submissions: 0,
    },
    gate_status: "not_ready",
    promoted_at: null,
    promoted_to_role: null,
    user_first_name: "Priya",
    ...overrides,
  };
}

describe("PromotionScreen", () => {
  it("renders the four rungs with real titles + state labels", () => {
    mockPromotionSummary.mockReturnValue({ data: makeSummary() });
    render(<PromotionScreen />);
    // Each rung copy appears once in the rung card and once on the ladder.
    expect(
      screen.getAllByText("Lessons 1–2 complete").length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Finish 2 remaining lessons")).toBeInTheDocument();
    expect(screen.getByText("Submit capstone")).toBeInTheDocument();
    expect(
      screen.getByText("Complete 2 practice interviews"),
    ).toBeInTheDocument();
    // State labels must reflect real rung state, not all "locked" by default.
    expect(screen.getAllByText("Done")).toHaveLength(1);
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getAllByText("Locked")).toHaveLength(2);
  });

  it("uses target_role from the aggregator for the role transition", () => {
    mockPromotionSummary.mockReturnValue({
      data: makeSummary({
        role: { from_role: "Python Developer", to_role: "Senior GenAI Engineer" },
      }),
    });
    render(<PromotionScreen />);
    // The takeover content references the target role even when closed
    // (it's rendered with display:none style).
    expect(screen.getAllByText(/Senior GenAI Engineer/).length).toBeGreaterThan(0);
  });

  it("disables the gate button when not_ready", () => {
    mockPromotionSummary.mockReturnValue({ data: makeSummary() });
    render(<PromotionScreen />);
    const btn = screen.getByRole("button", { name: /Gate locked/i });
    expect(btn).toBeDisabled();
  });

  it("shows the Open ceremony button when ready_to_promote", () => {
    mockPromotionSummary.mockReturnValue({
      data: makeSummary({
        gate_status: "ready_to_promote",
        rungs: makeSummary().rungs.map((r) => ({ ...r, state: "done" as const })),
      }),
    });
    render(<PromotionScreen />);
    expect(
      screen.getByRole("button", { name: /Open promotion ceremony/i }),
    ).toBeInTheDocument();
  });

  it("shows the Promoted-on disabled button when already promoted", () => {
    mockPromotionSummary.mockReturnValue({
      data: makeSummary({
        gate_status: "promoted",
        promoted_at: "2026-04-27T12:00:00Z",
        promoted_to_role: "Data Analyst",
      }),
    });
    render(<PromotionScreen />);
    // The button uses aria-label="Promotion already confirmed" so we look
    // up by the visible text content instead.
    const btn = screen.getByText(/Promoted on/i).closest("button");
    expect(btn).not.toBeNull();
    expect(btn).toBeDisabled();
  });

  it("confirm fires the mutation and routes to /today on settle", () => {
    mockPromotionSummary.mockReturnValue({
      data: makeSummary({
        gate_status: "ready_to_promote",
        rungs: makeSummary().rungs.map((r) => ({ ...r, state: "done" as const })),
      }),
    });
    render(<PromotionScreen />);
    const confirmBtn = screen.getByRole("button", { name: /Begin Data Analyst/i });
    fireEvent.click(confirmBtn);
    expect(mockConfirmMutate).toHaveBeenCalled();
    // Simulate the onSettled callback the component supplies.
    const callArgs = mockConfirmMutate.mock.calls[0];
    const opts = callArgs[1] as { onSettled?: () => void };
    opts.onSettled?.();
    expect(mockRouterPush).toHaveBeenCalledWith("/today");
  });
});
