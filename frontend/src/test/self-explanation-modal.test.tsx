import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { SelfExplanationModal } from "@/components/features/self-explanation-modal";

describe("SelfExplanationModal", () => {
  it("does not render when closed", () => {
    render(
      <SelfExplanationModal open={false} onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(screen.queryByText(/Before I show the grade/i)).not.toBeInTheDocument();
  });

  it("disables the submit button until the minimum length is met", () => {
    const onConfirm = vi.fn();
    render(<SelfExplanationModal open onConfirm={onConfirm} />);

    const submitBtn = screen.getByRole("button", { name: /submit with explanation/i });
    expect(submitBtn).toBeDisabled();

    const textarea = screen.getByLabelText(/your self-explanation/i);
    fireEvent.change(textarea, { target: { value: "short" } });
    expect(submitBtn).toBeDisabled();

    fireEvent.change(textarea, {
      target: { value: "because it handles the empty case first." },
    });
    expect(submitBtn).not.toBeDisabled();

    fireEvent.click(submitBtn);
    expect(onConfirm).toHaveBeenCalledWith(
      "because it handles the empty case first.",
    );
  });

  it("skip & submit fires onConfirm with empty string", () => {
    const onConfirm = vi.fn();
    render(<SelfExplanationModal open onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: /skip & submit/i }));
    expect(onConfirm).toHaveBeenCalledWith("");
  });

  it("shows submitting state on both buttons when submitting", () => {
    render(
      <SelfExplanationModal
        open
        submitting
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /skip & submit/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /submitting/i })).toBeDisabled();
  });
});
