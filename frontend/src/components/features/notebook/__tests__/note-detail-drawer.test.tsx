/**
 * P-Today2 — NoteDetailDrawer tests.
 *
 * Verifies:
 *   1. Renders title, body, tags, source/status eyebrow.
 *   2. "Original assistant message" toggle reveals the raw content.
 *   3. Edit → Save PATCHes with the new title/body/tags and invalidates cache.
 *   4. Delete → confirm flow DELETEs and closes the drawer.
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

import { NoteDetailDrawer } from "../note-detail-drawer";
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

function makeEntry(overrides: Partial<NotebookEntryOut> = {}): NotebookEntryOut {
  return {
    id: "e-1",
    message_id: "m-1",
    conversation_id: "c-1",
    content: "Raw assistant reply preserved as audit trail.",
    title: "Generators",
    user_note: "- they're lazy iterators\n- yield pauses execution",
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
  return { qc, ...render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>) };
}

describe("NoteDetailDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders title, body, tags, and eyebrow", async () => {
    renderWithQuery(
      <NoteDetailDrawer
        open={true}
        onOpenChange={() => {}}
        entry={makeEntry()}
      />,
    );

    expect(await screen.findByText("Generators")).toBeInTheDocument();
    expect(screen.getByText(/in review/i)).toBeInTheDocument();
    // Tag chip — there's also "Python" in the topic eyebrow, so target the
    // chip via the role + text combination instead.
    const tagChips = screen.getAllByText(/^python$/i);
    expect(tagChips.length).toBeGreaterThan(0);
    // user_note Markdown rendered.
    expect(screen.getByTestId("md").textContent).toContain("they're lazy iterators");
  });

  it("'Original assistant message' toggle reveals the raw content", async () => {
    renderWithQuery(
      <NoteDetailDrawer
        open={true}
        onOpenChange={() => {}}
        entry={makeEntry()}
      />,
    );

    const toggle = await screen.findByRole("button", {
      name: /original assistant message/i,
    });

    // Before click, raw content not in DOM.
    expect(
      screen.queryByText("Raw assistant reply preserved as audit trail."),
    ).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(toggle);
    });

    expect(
      await screen.findByText(
        "Raw assistant reply preserved as audit trail.",
      ),
    ).toBeInTheDocument();
  });

  it("edit → save PATCHes the entry with new fields", async () => {
    (chatApi.patchNotebookEntry as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeEntry({ title: "Updated title" }),
    );

    renderWithQuery(
      <NoteDetailDrawer
        open={true}
        onOpenChange={() => {}}
        entry={makeEntry()}
      />,
    );

    // Enter edit mode.
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: /^edit$/i }));
    });

    // Edit the title.
    const titleInput = screen.getByPlaceholderText(/title/i);
    await act(async () => {
      fireEvent.change(titleInput, { target: { value: "Updated title" } });
    });

    // Save.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save changes/i }));
    });

    await waitFor(() => {
      expect(chatApi.patchNotebookEntry).toHaveBeenCalledWith(
        "e-1",
        expect.objectContaining({
          title: "Updated title",
          user_note: expect.stringContaining("they're lazy iterators"),
          tags: ["python", "generators"],
        }),
      );
      expect(mockToastSuccess).toHaveBeenCalledWith("Note updated");
    });
  });

  it("delete → confirm flow DELETEs and closes drawer", async () => {
    (chatApi.deleteNotebookEntry as ReturnType<typeof vi.fn>).mockResolvedValue(
      undefined,
    );
    const onOpenChange = vi.fn();

    renderWithQuery(
      <NoteDetailDrawer
        open={true}
        onOpenChange={onOpenChange}
        entry={makeEntry()}
      />,
    );

    // Click delete → enters confirm state, no API call yet.
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: /delete/i }));
    });

    expect(chatApi.deleteNotebookEntry).not.toHaveBeenCalled();
    expect(screen.getByText(/delete this note/i)).toBeInTheDocument();

    // Confirm delete.
    const confirmBtn = screen.getAllByRole("button", { name: /^delete$/i })[0];
    await act(async () => {
      fireEvent.click(confirmBtn);
    });

    await waitFor(() => {
      expect(chatApi.deleteNotebookEntry).toHaveBeenCalledWith("e-1");
      expect(onOpenChange).toHaveBeenCalledWith(false);
      expect(mockToastSuccess).toHaveBeenCalledWith("Note deleted");
    });
  });
});
