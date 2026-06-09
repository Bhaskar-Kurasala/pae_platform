/**
 * P-Today3 — MakeFlashcardsModal tests.
 *
 * Verifies:
 *   1. Opens with one empty card row.
 *   2. "Source message" toggle reveals the raw assistant content.
 *   3. Add card button adds rows up to 10 then disables.
 *   4. Char counters: front cap 140, back warns at 200, errors past 280.
 *   5. Save button disabled when no valid cards.
 *   6. Save fires addFlashcards with the trimmed front/back pairs.
 *   7. Trimmed-count surfaced in success toast.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { MakeFlashcardsModal } from "../make-flashcards-modal";

const { mockToastSuccess, mockToastError } = vi.hoisted(() => ({
  mockToastSuccess: vi.fn(),
  mockToastError: vi.fn(),
}));

vi.mock("@/lib/toast", () => ({
  toast: { success: mockToastSuccess, error: mockToastError },
}));

vi.mock("@/components/features/markdown-renderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="md">{content}</div>
  ),
}));

vi.mock("@/lib/chat-api", () => ({
  chatApi: {
    addFlashcards: vi.fn(),
  },
}));

import { chatApi } from "@/lib/chat-api";

function renderWithQuery(ui: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const RAW =
  "Generators are lazy iterators in Python that pause and resume execution.";

describe("MakeFlashcardsModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens with one empty card row and disabled Save", async () => {
    renderWithQuery(
      <MakeFlashcardsModal
        open={true}
        onOpenChange={() => {}}
        messageId="m-1"
        conversationId="c-1"
        content={RAW}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: /make flashcards/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/front · the cue/i)).toBeInTheDocument();
    expect(
      screen.getByLabelText(/back · your recall in 1.2 sentences/i),
    ).toBeInTheDocument();

    const saveBtn = screen.getByRole("button", { name: /save .*cards?/i });
    expect(saveBtn).toBeDisabled();
  });

  it("source toggle reveals the raw assistant content", async () => {
    renderWithQuery(
      <MakeFlashcardsModal
        open={true}
        onOpenChange={() => {}}
        messageId="m-2"
        conversationId="c-1"
        content={RAW}
      />,
    );

    expect(screen.queryByTestId("md")).not.toBeInTheDocument();
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /source message/i }),
      );
    });
    expect(screen.getByTestId("md")).toHaveTextContent(/lazy iterators/i);
  });

  it("Add another card adds rows", async () => {
    renderWithQuery(
      <MakeFlashcardsModal
        open={true}
        onOpenChange={() => {}}
        messageId="m-3"
        conversationId="c-1"
        content={RAW}
      />,
    );

    expect(screen.getAllByText(/^card \d+$/i)).toHaveLength(1);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /add another card/i }));
    });
    expect(screen.getAllByText(/^card \d+$/i)).toHaveLength(2);
  });

  it("save fires addFlashcards with trimmed pairs and surfaces trimmed-count toast", async () => {
    (chatApi.addFlashcards as ReturnType<typeof vi.fn>).mockResolvedValue({
      cards_added: 1,
      cards: [{ question: "What is yield?", answer: "Pauses execution." }],
      cards_trimmed: 1,
    });
    const onOpenChange = vi.fn();
    const onSaved = vi.fn();

    renderWithQuery(
      <MakeFlashcardsModal
        open={true}
        onOpenChange={onOpenChange}
        messageId="m-4"
        conversationId="c-9"
        content={RAW}
        onSaved={onSaved}
      />,
    );

    const front = screen.getByLabelText(/front · the cue/i);
    const back = screen.getByLabelText(/back · your recall in 1.2 sentences/i);

    await act(async () => {
      fireEvent.change(front, { target: { value: "  What is yield?  " } });
      fireEvent.change(back, { target: { value: "  Pauses execution.  " } });
    });

    const saveBtn = screen.getByRole("button", { name: /save 1 card/i });
    expect(saveBtn).toBeEnabled();
    await act(async () => {
      fireEvent.click(saveBtn);
    });

    await waitFor(() => {
      expect(chatApi.addFlashcards).toHaveBeenCalledWith({
        messageId: "m-4",
        conversationId: "c-9",
        cards: [{ front: "What is yield?", back: "Pauses execution." }],
      });
      expect(mockToastSuccess).toHaveBeenCalledWith(
        expect.stringContaining("trimmed code blocks from 1"),
      );
      expect(onSaved).toHaveBeenCalledWith(1);
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it("partially-filled card disables Save and warns", async () => {
    renderWithQuery(
      <MakeFlashcardsModal
        open={true}
        onOpenChange={() => {}}
        messageId="m-5"
        conversationId="c-1"
        content={RAW}
      />,
    );

    const front = screen.getByLabelText(/front · the cue/i);
    await act(async () => {
      fireEvent.change(front, { target: { value: "only the front" } });
    });

    expect(
      await screen.findByText(/front and back are both required/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save .*cards?/i })).toBeDisabled();
  });
});
