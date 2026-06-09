/**
 * P3-2 — Flashcard button on assistant chat bubbles.
 *
 * Verifies:
 *   1) The flashcard button is visible on a hydrated assistant bubble.
 *   2) Clicking it calls `chatApi.addFlashcards` with the right args.
 *   3) A success toast appears with "N cards added to review".
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Module mocks (hoisted) ───────────────────────────────────────

let currentSearchParams = new URLSearchParams();
const searchParamsSubscribers = new Set<() => void>();

function setSearchParamsFromPath(path: string): void {
  const q = path.includes("?") ? path.slice(path.indexOf("?") + 1) : "";
  currentSearchParams = new URLSearchParams(q);
  for (const cb of searchParamsSubscribers) cb();
}

const routerReplace = vi.fn((path: string) => {
  setSearchParamsFromPath(path);
});
const routerPush = vi.fn((path: string) => {
  setSearchParamsFromPath(path);
});

vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useRouter: () => ({
      replace: routerReplace,
      push: routerPush,
      refresh: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      prefetch: vi.fn(),
    }),
    useSearchParams: () =>
      useSyncExternalStore(
        (cb) => {
          searchParamsSubscribers.add(cb);
          return () => searchParamsSubscribers.delete(cb);
        },
        () => currentSearchParams,
        () => currentSearchParams,
      ),
    usePathname: () => "/chat",
  };
});

vi.mock("@/lib/chat-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/chat-api")>(
    "@/lib/chat-api",
  );
  return {
    ...actual,
    chatApi: {
      listConversations: vi.fn(),
      getConversation: vi.fn(),
      renameConversation: vi.fn(),
      archiveConversation: vi.fn(),
      pinConversation: vi.fn(),
      deleteConversation: vi.fn(),
      postFeedback: vi.fn(),
      getFeedback: vi.fn(),
      editMessage: vi.fn(),
      getMessage: vi.fn(),
      addFlashcards: vi.fn(),
      // P-Today2 — opening the SaveNoteModal triggers summarize on mount.
      // Not exercised here but the chat page's effect needs the symbol present.
      summarizeForNotebook: vi.fn(),
      saveToNotebook: vi.fn(),
      listNotebook: vi.fn(),
      deleteNotebookEntry: vi.fn(),
      getContextSuggestions: vi.fn(),
    },
    regenerateMessage: vi.fn(),
    uploadAttachment: vi.fn(),
    exportConversationMarkdown: vi.fn(),
  };
});

vi.mock("@/hooks/use-smart-auto-scroll", () => ({
  useSmartAutoScroll: () => ({ isAtBottom: true, jumpToBottom: vi.fn() }),
}));

vi.mock("@/components/features/markdown-renderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="md">{content}</div>
  ),
}));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>(
    "@/lib/api-client",
  );
  return {
    ...actual,
    exercisesApi: { getSubmission: vi.fn() },
  };
});

// Mock toast so we can assert on it without a real Sonner DOM.
// Use vi.hoisted so the variables are available in the hoisted vi.mock factory.
const { mockToastSuccess, mockToastError } = vi.hoisted(() => ({
  mockToastSuccess: vi.fn(),
  mockToastError: vi.fn(),
}));
vi.mock("@/lib/toast", () => ({
  toast: { success: mockToastSuccess, error: mockToastError },
}));

import ChatPage from "@/app/(portal)/chat/page";
import { chatApi } from "@/lib/chat-api";

type ChatApiMock = {
  listConversations: Mock;
  getConversation: Mock;
  addFlashcards: Mock;
};

const mockedChatApi = chatApi as unknown as ChatApiMock;

// ── Helpers ──────────────────────────────────────────────────────

function makeConversation(id: string) {
  return {
    id,
    title: "Test Conversation",
    agent_name: null,
    updated_at: new Date().toISOString(),
    archived_at: null,
    pinned_at: null,
    message_count: 2,
  };
}

function makeConversationDetail(id: string) {
  return {
    id,
    user_id: "u1",
    agent_name: null,
    title: "Test Conversation",
    archived_at: null,
    pinned_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    messages: [
      {
        id: "m-user-1",
        conversation_id: id,
        role: "user" as const,
        content: "Explain Python generators",
        agent_name: null,
        token_count: null,
        parent_id: null,
        created_at: new Date().toISOString(),
      },
      {
        id: "m-asst-1",
        conversation_id: id,
        role: "assistant" as const,
        content: "Generators are lazy iterators. Q: What is a generator? A: A lazy iterator.",
        agent_name: "socratic_tutor",
        token_count: null,
        parent_id: "m-user-1",
        created_at: new Date().toISOString(),
      },
    ],
  };
}

// ── Tests ─────────────────────────────────────────────────────────

describe("Chat page — P3-2 flashcard extraction", () => {
  beforeEach(() => {
    routerReplace.mockReset();
    routerPush.mockReset();
    routerReplace.mockImplementation((path: string) => {
      setSearchParamsFromPath(path);
    });
    routerPush.mockImplementation((path: string) => {
      setSearchParamsFromPath(path);
    });
    mockedChatApi.listConversations.mockReset();
    mockedChatApi.getConversation.mockReset();
    mockedChatApi.addFlashcards.mockReset();
    mockToastSuccess.mockReset();
    mockToastError.mockReset();
    currentSearchParams = new URLSearchParams();
    for (const cb of searchParamsSubscribers) cb();
    window.localStorage.clear();

    if (!("scrollIntoView" in HTMLElement.prototype)) {
      // @ts-expect-error patching jsdom prototype
      HTMLElement.prototype.scrollIntoView = () => {};
    }
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function renderHydrated(): Promise<void> {
    setSearchParamsFromPath("/chat?c=c1");
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1"),
    ]);
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c1"),
    );
    // ChatSidebar uses useDueCards; the modal uses useMutation.
    const qc = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    render(
      <QueryClientProvider client={qc}>
        <ChatPage />
      </QueryClientProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText("Explain Python generators")).toBeInTheDocument();
    });
  }

  // P-Today3 — bookmark click no longer fires `addFlashcards` directly;
  // it opens MakeFlashcardsModal where the student writes 1–10 cards.

  it("shows the flashcard button on a hydrated assistant bubble", async () => {
    await renderHydrated();

    const flashcardBtns = await screen.findAllByRole("button", {
      name: /make flashcards from this message/i,
    });
    expect(flashcardBtns.length).toBeGreaterThan(0);
  });

  it("opens MakeFlashcardsModal on bookmark click (no immediate POST)", async () => {
    await renderHydrated();

    const flashcardBtn = await screen.findByRole("button", {
      name: /make flashcards from this message/i,
    });
    await act(async () => {
      fireEvent.click(flashcardBtn);
    });

    // Modal title appears — bookmark didn't auto-POST.
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /make flashcards/i }),
      ).toBeInTheDocument();
    });
    expect(mockedChatApi.addFlashcards).not.toHaveBeenCalled();
  });

  it("clicking Save in modal posts the user-authored cards", async () => {
    mockedChatApi.addFlashcards.mockResolvedValue({
      cards_added: 1,
      cards: [{ question: "What is a generator?", answer: "A lazy iterator." }],
      cards_trimmed: 0,
    });
    await renderHydrated();

    await act(async () => {
      fireEvent.click(
        await screen.findByRole("button", {
          name: /make flashcards from this message/i,
        }),
      );
    });

    const front = await screen.findByLabelText(/front · the cue/i);
    const back = screen.getByLabelText(/back · your recall in 1.2 sentences/i);
    await act(async () => {
      fireEvent.change(front, { target: { value: "What is a generator?" } });
      fireEvent.change(back, { target: { value: "A lazy iterator." } });
    });

    const saveBtn = await screen.findByRole("button", { name: /save 1 card/i });
    await act(async () => {
      fireEvent.click(saveBtn);
    });

    await waitFor(() => {
      expect(mockedChatApi.addFlashcards).toHaveBeenCalledWith({
        messageId: "m-asst-1",
        conversationId: "c1",
        cards: [{ front: "What is a generator?", back: "A lazy iterator." }],
      });
      expect(mockToastSuccess).toHaveBeenCalledWith("1 card added to review");
    });
  });
});
