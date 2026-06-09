/**
 * P-Today2 — SaveNoteModal tests.
 *
 * Verifies:
 *   1. Opens immediately with the raw content as a fallback (so it's never blank).
 *   2. Swaps the textarea to the LLM summary once summarization resolves.
 *   3. Suggested tag chips appear and clicking them adds the tag.
 *   4. Free-text tag input — Enter commits.
 *   5. "Use original" pastes raw content back.
 *   6. Save POSTs `{user_note, content, title, tags}` and fires `onSaved`.
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

import { SaveNoteModal } from "../save-note-modal";

const { mockToastSuccess, mockToastError } = vi.hoisted(() => ({
  mockToastSuccess: vi.fn(),
  mockToastError: vi.fn(),
}));

vi.mock("@/lib/toast", () => ({
  toast: { success: mockToastSuccess, error: mockToastError },
}));

vi.mock("@/lib/chat-api", () => ({
  chatApi: {
    summarizeForNotebook: vi.fn(),
    saveToNotebook: vi.fn(),
  },
}));

import { chatApi } from "@/lib/chat-api";

function renderWithQuery(ui: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const RAW_CONTENT =
  "Generators are lazy iterators in Python. They use the yield keyword to " +
  "produce a value and pause execution, resuming on the next next() call.";

describe("SaveNoteModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens with raw content as the immediate fallback", async () => {
    (chatApi.summarizeForNotebook as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise(() => {
        /* never resolves — verify fallback while loading */
      }),
    );

    renderWithQuery(
      <SaveNoteModal
        open={true}
        onOpenChange={() => {}}
        messageId="m-1"
        conversationId="c-1"
        content={RAW_CONTENT}
        userQuestion="What are generators?"
      />,
    );

    const ta = await screen.findByLabelText(/your note/i);
    expect((ta as HTMLTextAreaElement).value).toContain("Generators are lazy");
  });

  it("swaps to the LLM summary once summarization resolves", async () => {
    (chatApi.summarizeForNotebook as ReturnType<typeof vi.fn>).mockResolvedValue({
      summary: "- Generators are lazy iterators\n- yield pauses, next resumes",
      suggested_tags: ["python", "generators"],
      cached: false,
    });

    renderWithQuery(
      <SaveNoteModal
        open={true}
        onOpenChange={() => {}}
        messageId="m-2"
        conversationId="c-1"
        content={RAW_CONTENT}
      />,
    );

    const ta = (await screen.findByLabelText(
      /your note/i,
    )) as HTMLTextAreaElement;

    await waitFor(() => {
      expect(ta.value).toContain("Generators are lazy iterators");
    });

    // Suggested tags chips appear.
    expect(
      await screen.findByRole("button", { name: /add suggested tag python/i }),
    ).toBeInTheDocument();
  });

  it("clicking a suggested tag adds it as a chip", async () => {
    (chatApi.summarizeForNotebook as ReturnType<typeof vi.fn>).mockResolvedValue({
      summary: "- one bullet",
      suggested_tags: ["rag"],
      cached: false,
    });

    renderWithQuery(
      <SaveNoteModal
        open={true}
        onOpenChange={() => {}}
        messageId="m-3"
        conversationId="c-1"
        content={RAW_CONTENT}
      />,
    );

    const suggestionBtn = await screen.findByRole("button", {
      name: /add suggested tag rag/i,
    });
    await act(async () => {
      fireEvent.click(suggestionBtn);
    });

    // Once added, a "Remove tag rag" button appears in the chip row.
    expect(
      await screen.findByRole("button", { name: /remove tag rag/i }),
    ).toBeInTheDocument();
  });

  it("save fires saveToNotebook with the rewritten user_note + tags", async () => {
    (chatApi.summarizeForNotebook as ReturnType<typeof vi.fn>).mockResolvedValue({
      summary: "- summary bullet",
      suggested_tags: [],
      cached: false,
    });
    (chatApi.saveToNotebook as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "nb-1",
    });
    const onSaved = vi.fn();
    const onOpenChange = vi.fn();

    renderWithQuery(
      <SaveNoteModal
        open={true}
        onOpenChange={onOpenChange}
        messageId="m-4"
        conversationId="c-9"
        content={RAW_CONTENT}
        userQuestion="What are generators?"
        onSaved={onSaved}
      />,
    );

    const ta = (await screen.findByLabelText(
      /your note/i,
    )) as HTMLTextAreaElement;
    await waitFor(() => expect(ta.value).toContain("summary bullet"));

    // Edit the note to confirm user_edits override the AI text.
    await act(async () => {
      fireEvent.change(ta, { target: { value: "my own rewrite" } });
    });

    // Add a tag via the input — Enter commits.
    const tagInput = screen.getByLabelText(/tags \(press enter to add\)/i);
    await act(async () => {
      fireEvent.change(tagInput, { target: { value: "python" } });
      fireEvent.keyDown(tagInput, { key: "Enter" });
    });

    // Click Save.
    const saveBtn = screen.getByRole("button", { name: /save to notebook/i });
    await act(async () => {
      fireEvent.click(saveBtn);
    });

    await waitFor(() => {
      expect(chatApi.saveToNotebook).toHaveBeenCalledWith(
        expect.objectContaining({
          messageId: "m-4",
          conversationId: "c-9",
          content: RAW_CONTENT,
          userNote: "my own rewrite",
          tags: ["python"],
        }),
      );
    });

    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith("nb-1");
      expect(mockToastSuccess).toHaveBeenCalledWith("Saved to notebook");
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it("'Use original' pastes raw content back into the textarea", async () => {
    (chatApi.summarizeForNotebook as ReturnType<typeof vi.fn>).mockResolvedValue({
      summary: "- short summary",
      suggested_tags: [],
      cached: false,
    });

    renderWithQuery(
      <SaveNoteModal
        open={true}
        onOpenChange={() => {}}
        messageId="m-5"
        conversationId="c-1"
        content={RAW_CONTENT}
      />,
    );

    const ta = (await screen.findByLabelText(
      /your note/i,
    )) as HTMLTextAreaElement;
    await waitFor(() => expect(ta.value).toContain("short summary"));

    const useOriginalBtn = screen.getByRole("button", {
      name: /use original/i,
    });
    await act(async () => {
      fireEvent.click(useOriginalBtn);
    });

    expect(ta.value).toContain("Generators are lazy");
  });
});
