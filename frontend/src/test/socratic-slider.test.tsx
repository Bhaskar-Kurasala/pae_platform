import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import {
  SocraticSliderMenu,
  SocraticSlider,
} from "@/components/features/socratic-slider";

// Mock hooks for the wrapper test only. Menu tests below don't need mocks
// since the menu is a controlled pure component.
const mockUpdate = vi.fn();
let currentPrefs: { socratic_level: 0 | 1 | 2 | 3 } = { socratic_level: 2 };
vi.mock("@/lib/hooks/use-preferences", () => ({
  useMyPreferences: () => ({ data: currentPrefs }),
  useUpdatePreferences: () => ({ mutate: mockUpdate }),
}));

describe("SocraticSliderMenu", () => {
  it("renders four radios for levels 0-3", () => {
    render(<SocraticSliderMenu level={0} onChange={() => {}} />);
    expect(screen.getAllByRole("radio")).toHaveLength(4);
  });

  it("marks the current level as aria-checked", () => {
    render(<SocraticSliderMenu level={1} onChange={() => {}} />);
    const checked = screen
      .getAllByRole("radio")
      .filter((r) => r.getAttribute("aria-checked") === "true");
    expect(checked).toHaveLength(1);
    expect(checked[0]).toHaveTextContent(/gentle/i);
  });

  it("calls onChange when a different level is clicked", () => {
    const onChange = vi.fn();
    render(<SocraticSliderMenu level={0} onChange={onChange} />);
    const strictRadio = screen
      .getAllByRole("radio")
      .find((r) => /strict/i.test(r.textContent ?? ""))!;
    fireEvent.click(strictRadio);
    expect(onChange).toHaveBeenCalledWith(3);
  });

  it("ignores a click on the already-selected level", () => {
    const onChange = vi.fn();
    render(<SocraticSliderMenu level={2} onChange={onChange} />);
    const standardRadio = screen
      .getAllByRole("radio")
      .find((r) => r.getAttribute("aria-checked") === "true")!;
    fireEvent.click(standardRadio);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows per-level copy so students can tell the levels apart", () => {
    render(<SocraticSliderMenu level={0} onChange={() => {}} />);
    expect(screen.getByText(/Direct answers by default/i)).toBeInTheDocument();
    expect(screen.getByText(/Questions only/i)).toBeInTheDocument();
  });
});

describe("SocraticSlider trigger", () => {
  it("reflects the current level in the trigger aria-label", () => {
    currentPrefs = { socratic_level: 2 };
    render(<SocraticSlider />);
    expect(
      screen.getByRole("button", { name: /socratic intensity: standard/i }),
    ).toBeInTheDocument();
  });

  it("shows the 'off' label when the level is 0", () => {
    currentPrefs = { socratic_level: 0 };
    render(<SocraticSlider />);
    expect(
      screen.getByRole("button", { name: /socratic intensity: off/i }),
    ).toBeInTheDocument();
  });
});
