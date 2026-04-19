import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

import { MarkdownRenderer } from "@/components/features/markdown-renderer";

const SAMPLE_CODE = "const x = 42;\nconsole.log(x);";
const SAMPLE_MD = `Here is some code:\n\n\`\`\`ts\n${SAMPLE_CODE}\n\`\`\`\n`;

describe("MarkdownRenderer — per-code-block copy", () => {
  let writeText: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      writable: true,
      configurable: true,
    });
  });

  it("renders markdown and exposes a copy button inside the fenced code block", () => {
    render(<MarkdownRenderer content={SAMPLE_MD} />);

    const copyBtn = screen.getByRole("button", { name: /copy code/i });
    expect(copyBtn).toBeInTheDocument();
  });

  it("copies the raw code text when the copy button is clicked", async () => {
    render(<MarkdownRenderer content={SAMPLE_MD} />);
    const copyBtn = screen.getByRole("button", { name: /copy code/i });

    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(SAMPLE_CODE);
  });

  it("swaps the button label to 'Copied' then reverts after ~1.5s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<MarkdownRenderer content={SAMPLE_MD} />);
      const copyBtn = screen.getByRole("button", { name: /copy code/i });

      await act(async () => {
        fireEvent.click(copyBtn);
      });

      // After click, label has flipped to "Copied".
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /copied/i })).toBeInTheDocument();
      });

      // aria-live region announces "Copied".
      const live = screen
        .getAllByRole("status")
        .find((el) => el.textContent === "Copied");
      expect(live).toBeDefined();

      // Advance past the 1.5s reset timeout.
      await act(async () => {
        vi.advanceTimersByTime(1600);
      });

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /copy code/i })).toBeInTheDocument();
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("no-ops (with a warning) when navigator.clipboard is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      writable: true,
      configurable: true,
    });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    render(<MarkdownRenderer content={SAMPLE_MD} />);
    const copyBtn = screen.getByRole("button", { name: /copy code/i });

    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(warn).toHaveBeenCalled();
    // Label must not flip since the copy was a no-op.
    expect(screen.getByRole("button", { name: /copy code/i })).toBeInTheDocument();

    warn.mockRestore();
  });
});
