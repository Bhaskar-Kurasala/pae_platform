import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { ChatSuggestionPills } from "@/components/features/chat-suggestion-pills";

describe("ChatSuggestionPills", () => {
  const PILLS = [
    { key: "direct", label: "Just tell me" },
    { key: "hint", label: "Give me a hint" },
    { key: "challenge", label: "Challenge me" },
  ];

  it("renders a button per pill", () => {
    render(<ChatSuggestionPills pills={PILLS} onPick={() => {}} />);
    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(screen.getByText("Just tell me")).toBeInTheDocument();
  });

  it("renders nothing when pills list is empty", () => {
    const { container } = render(
      <ChatSuggestionPills pills={[]} onPick={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("fires onPick with the clicked pill and its index", () => {
    const onPick = vi.fn();
    render(<ChatSuggestionPills pills={PILLS} onPick={onPick} />);
    fireEvent.click(screen.getByText("Give me a hint"));
    expect(onPick).toHaveBeenCalledWith(PILLS[1], 1);
  });

  it("uses the clarify label by default and the followup label when specified", () => {
    const { rerender } = render(
      <ChatSuggestionPills pills={PILLS} onPick={() => {}} />,
    );
    expect(
      screen.getByRole("group", { name: /how should i answer/i }),
    ).toBeInTheDocument();

    rerender(
      <ChatSuggestionPills pills={PILLS} onPick={() => {}} variant="followup" />,
    );
    expect(
      screen.getByRole("group", { name: /keep going/i }),
    ).toBeInTheDocument();
  });

  it("does not call onPick when the button is disabled", () => {
    const onPick = vi.fn();
    render(<ChatSuggestionPills pills={PILLS} onPick={onPick} disabled />);
    fireEvent.click(screen.getByText("Just tell me"));
    expect(onPick).not.toHaveBeenCalled();
  });
});
