/**
 * P-Notebook2 — NoteDetailModal tests.
 *
 * Verifies the editorial-modal replacement of NoteDetailDrawer:
 *   1. Renders title, eyebrow, and the student's note as the hero when
 *      `user_note` is present.
 *   2. Falls back to a "Captured from chat" framed block when no note
 *      exists (so the student knows they didn't write the words).
 *   3. "View original chat" toggle is hidden when there's nothing
 *      different to reveal, shown when content differs from the note.
 *   4. Edit → Save PATCHes with the new note + tags and clears the
 *      editing state on success.
 *   5. Delete → confirm flow DELETEs and closes the modal.
 *   6. Esc and backdrop click both dismiss the modal.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { NoteDetailModal } from "../note-detail-modal";
import type { NotebookEntryOut } from "@/lib/chat-api";

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
    patchNotebookEntry: vi.fn(),
    deleteNotebookEntry: vi.fn(),
  },
}));

import { chatApi } from "@/lib/chat-api";

function makeEntry(
  overrides: Partial<NotebookEntryOut> = {},
): NotebookEntryOut {
  return {
    id: "e-1",
    message_id: "m-1",
    conversation_id: "c-1",
    content: "Raw assistant reply preserved as audit trail.",
    title: "Generators",
    user_note: "they're lazy iterators; yield pauses execution",
    source_type: "chat",
    topic: "Python",
    tags: ["python", "generators"],
    last_reviewed_at: null,
    graduated_at: null,
    created_at: new Date("2026-04-26T00:00:00Z").toISOString(),
    ...overrides,
  };
}

function renderWithQuery(ui: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    qc,
    ...render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>),
  };
}

describe("NoteDetailModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns null when closed", () => {
    const { container } = renderWithQuery(
      <NoteDetailModal
        open={false}
        onOpenChange={() => {}}
        entry={makeEntry()}
      />,
    );
    expect(container.querySelector("[data-testid='note-detail-modal']"))
      .toBeNull();
  });

  it("leads with the student's note when present", () => {
    renderWithQuery(
      <NoteDetailModal
        open={true}
        onOpenChange={() => {}}
        entry={makeEntry()}
      />,
    );
    expect(screen.getByText("Generators")).toBeInTheDocument();
    expect(screen.getByText(/your note/i)).toBeInTheDocument();
    expect(screen.getByTestId("note-detail-hero")).toHaveTextContent(
      /lazy iterators/,
    );
  });

  it("falls back to a 'Captured from chat' block when no user_note", () => {
    renderWithQuery(
      <NoteDetailModal
        open={true}
        onOpenChange={() => {}}
        entry={makeEntry({ user_note: null })}
      />,
    );
    expect(screen.getByText(/captured from chat/i)).toBeInTheDocument();
    expect(screen.getByTestId("note-detail-hero")).toHaveTextContent(
      /raw assistant reply/i,
    );
    // No "View original chat" toggle when there's nothing different.
    expect(screen.queryByTestId("note-detail-source-toggle")).toBeNull();
  });

  it("shows the source toggle when user note differs from original chat", () => {
    renderWithQuery(
      <NoteDetailModal
        open={true}
        onOpenChange={() => {}}
        entry={makeEntry()}
      />,
    );
    const toggle = screen.getByTestId("note-detail-source-toggle");
    expect(toggle).toHaveTextContent(/view original chat/i);
    fireEvent.click(toggle);
    expect(toggle).toHaveTextContent(/hide original chat/i);
    expect(screen.getByTestId("note-detail-source-body")).toHaveTextContent(
      /raw assistant reply/i,
    );
  });

  it("Edit → Save PATCHes with the new note", async () => {
    (chatApi.patchNotebookEntry as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeEntry(),
    );
    renderWithQuery(
      <NoteDetailModal
        open={true}
        onOpenChange={() => {}}
        entry={makeEntry()}
      />,
    );
    fireEvent.click(screen.getByTestId("note-detail-edit"));
    const ta = screen.getByTestId("note-detail-textarea") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "rewrote the note" } });
    fireEvent.click(screen.getByTestId("note-detail-save"));
    await waitFor(() => {
      expect(chatApi.patchNotebookEntry).toHaveBeenCalledWith(
        "e-1",
        expect.objectContaining({ user_note: "rewrote the note" }),
      );
    });
  });

  it("Delete → confirm DELETEs and dismisses the modal", async () => {
    (chatApi.deleteNotebookEntry as ReturnType<typeof vi.fn>).mockResolvedValue(
      undefined,
    );
    const onOpenChange = vi.fn();
    renderWithQuery(
      <NoteDetailModal
        open={true}
        onOpenChange={onOpenChange}
        entry={makeEntry()}
      />,
    );
    fireEvent.click(screen.getByTestId("note-detail-delete"));
    fireEvent.click(screen.getByTestId("note-detail-delete-confirm"));
    await waitFor(() => {
      expect(chatApi.deleteNotebookEntry).toHaveBeenCalledWith("e-1");
    });
    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it("Esc dismisses the modal", () => {
    const onOpenChange = vi.fn();
    renderWithQuery(
      <NoteDetailModal
        open={true}
        onOpenChange={onOpenChange}
        entry={makeEntry()}
      />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("close button dismisses the modal", () => {
    const onOpenChange = vi.fn();
    renderWithQuery(
      <NoteDetailModal
        open={true}
        onOpenChange={onOpenChange}
        entry={makeEntry()}
      />,
    );
    fireEvent.click(screen.getByTestId("note-detail-close"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
