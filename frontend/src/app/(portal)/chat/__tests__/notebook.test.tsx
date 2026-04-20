/**
 * P3-4 — "Save to notebook" bookmark button on assistant chat bubbles.
 *
 * Verifies:
 *   1) The bookmark button is visible on a hydrated assistant bubble.
 *   2) Clicking it calls `chatApi.saveToNotebook` with the right args.
 *   3) A success toast appears with "Saved to notebook".
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
  saveToNotebook: Mock;
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
        content: "What are generators?",
        agent_name: null,
        token_count: null,
        parent_id: null,
        created_at: new Date().toISOString(),
      },
      {
        id: "m-asst-1",
        conversation_id: id,
        role: "assistant" as const,
        content: "Generators are lazy iterators in Python.",
        agent_name: "socratic_tutor",
        token_count: null,
        parent_id: "m-user-1",
        created_at: new Date().toISOString(),
      },
    ],
  };
}

// ── Tests ─────────────────────────────────────────────────────────

describe("Chat page — P3-4 save to notebook", () => {
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
    mockedChatApi.saveToNotebook.mockReset();
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
    mockedChatApi.listConversations.mockResolvedValue([makeConversation("c1")]);
    mockedChatApi.getConversation.mockResolvedValue(makeConversationDetail("c1"));
    render(<ChatPage />);
    await waitFor(() => {
      expect(screen.getByText("What are generators?")).toBeInTheDocument();
    });
  }

  it("shows the bookmark button on a hydrated assistant bubble", async () => {
    await renderHydrated();

    const bookmarkBtns = await screen.findAllByRole("button", {
      name: /save to notebook/i,
    });
    expect(bookmarkBtns.length).toBeGreaterThan(0);
  });

  it("calls saveToNotebook with the message id and content on click", async () => {
    mockedChatApi.saveToNotebook.mockResolvedValue({ id: "nb-1" });
    await renderHydrated();

    const bookmarkBtn = await screen.findByRole("button", {
      name: /save to notebook/i,
    });
    await act(async () => {
      fireEvent.click(bookmarkBtn);
    });

    await waitFor(() => {
      expect(mockedChatApi.saveToNotebook).toHaveBeenCalledWith(
        expect.objectContaining({
          messageId: "m-asst-1",
          content: "Generators are lazy iterators in Python.",
          conversationId: "c1",
        }),
      );
    });
  });

  it("shows a success toast after saving to notebook", async () => {
    mockedChatApi.saveToNotebook.mockResolvedValue({ id: "nb-1" });
    await renderHydrated();

    const bookmarkBtn = await screen.findByRole("button", {
      name: /save to notebook/i,
    });
    await act(async () => {
      fireEvent.click(bookmarkBtn);
    });

    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith("Saved to notebook");
    });
  });
});
