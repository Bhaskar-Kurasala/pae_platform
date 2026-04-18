import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";

import { StuckBanner } from "@/components/features/studio/stuck-banner";

const mockUseStudio = vi.fn();

vi.mock("@/components/features/studio/studio-context", () => ({
  useStudio: () => mockUseStudio(),
}));

describe("StuckBanner", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockUseStudio.mockReturnValue({
      code: "print(1)",
      hasRunOnce: false,
      running: false,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not render before the inactivity threshold", () => {
    render(<StuckBanner thresholdMs={600_000} />);
    act(() => {
      vi.advanceTimersByTime(599_000);
    });
    expect(screen.queryByText(/stuck for a while/i)).not.toBeInTheDocument();
  });

  it("renders after the threshold and dispatches ask-tutor on click", () => {
    const listener = vi.fn();
    window.addEventListener("studio.stuck_ask_tutor", listener);

    render(<StuckBanner thresholdMs={600_000} />);
    act(() => {
      vi.advanceTimersByTime(601_000);
    });

    expect(screen.getByText(/stuck for a while/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /ask the tutor/i }));
    expect(listener).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/stuck for a while/i)).not.toBeInTheDocument();

    window.removeEventListener("studio.stuck_ask_tutor", listener);
  });

  it("hides on dismiss and emits a dismissed event", () => {
    const listener = vi.fn();
    window.addEventListener("studio.stuck_dismissed", listener);

    render(<StuckBanner thresholdMs={600_000} />);
    act(() => {
      vi.advanceTimersByTime(601_000);
    });

    fireEvent.click(screen.getByRole("button", { name: /dismiss stuck banner/i }));
    expect(listener).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/stuck for a while/i)).not.toBeInTheDocument();

    window.removeEventListener("studio.stuck_dismissed", listener);
  });
});
