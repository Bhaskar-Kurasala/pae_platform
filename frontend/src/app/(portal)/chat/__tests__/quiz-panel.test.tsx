/**
 * P3-3 — frontend tests for the "Quiz me" button and quiz panel.
 *
 * Covers:
 *   1) The "Quiz me" button is present on persisted assistant bubbles
 *   2) Clicking it calls chatApi.generateQuiz with the message id + content
 *   3) The quiz panel renders with question text from the mock response
 *   4) Closing the panel removes it from the DOM
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
      generateQuiz: vi.fn(),
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

import ChatPage from "@/app/(portal)/chat/page";
import { chatApi } from "@/lib/chat-api";

type ChatApiMock = {
  listConversations: Mock;
  getConversation: Mock;
  renameConversation: Mock;
  archiveConversation: Mock;
  pinConversation: Mock;
  deleteConversation: Mock;
  postFeedback: Mock;
  getFeedback: Mock;
  editMessage: Mock;
  getMessage: Mock;
  addFlashcards: Mock;
  saveToNotebook: Mock;
  listNotebook: Mock;
  deleteNotebookEntry: Mock;
  generateQuiz: Mock;
};

const mockedChatApi = chatApi as unknown as ChatApiMock;

// ── Fixtures ─────────────────────────────────────────────────────

const MOCK_QUESTIONS = [
  {
    question: "What does RAG stand for in AI?",
    options: [
      "Retrieval Augmented Generation",
      "Random Access Generator",
      "Recursive Agent Graph",
      "Real-time API Gateway",
    ],
    correct_index: 0,
    explanation: "RAG stands for Retrieval Augmented Generation.",
  },
  {
    question: "Which component retrieves context in RAG?",
    options: ["LLM", "Vector store", "Tokenizer", "Encoder only"],
    correct_index: 1,
    explanation: "The vector store retrieves relevant documents.",
  },
];

function makeConversation(id: string, title: string) {
  return {
    id,
    title,
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
    title: "Preloaded",
    archived_at: null,
    pinned_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    messages: [
      {
        id: "m-user-1",
        conversation_id: id,
        role: "user" as const,
        content: "Tell me about RAG",
        agent_name: null,
        token_count: null,
        parent_id: null,
        created_at: new Date().toISOString(),
        sibling_ids: [],
      },
      {
        id: "m-asst-1",
        conversation_id: id,
        role: "assistant" as const,
        content: "RAG stands for Retrieval Augmented Generation.",
        agent_name: "socratic_tutor",
        token_count: null,
        parent_id: "m-user-1",
        created_at: new Date().toISOString(),
        sibling_ids: [],
      },
    ],
  };
}

// ── Test suite ───────────────────────────────────────────────────

describe("Chat page — P3-3 Quiz me button and panel", () => {
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
    mockedChatApi.generateQuiz.mockReset();
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
      makeConversation("c1", "Preloaded"),
    ]);
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c1"),
    );

    render(<ChatPage />);
    await waitFor(() => {
      expect(screen.getByText("Tell me about RAG")).toBeInTheDocument();
    });
  }

  it("shows the Quiz me button on hydrated assistant bubbles", async () => {
    await renderHydrated();

    const quizButtons = await screen.findAllByRole("button", {
      name: /quiz me on this message/i,
    });
    expect(quizButtons.length).toBeGreaterThan(0);
  });

  it("clicking Quiz me calls generateQuiz and renders the panel with question text", async () => {
    mockedChatApi.generateQuiz.mockResolvedValue({
      questions: MOCK_QUESTIONS,
    });

    await renderHydrated();

    const quizBtn = await screen.findByRole("button", {
      name: /quiz me on this message/i,
    });
    await act(async () => {
      fireEvent.click(quizBtn);
    });

    await waitFor(() => {
      expect(mockedChatApi.generateQuiz).toHaveBeenCalledWith(
        "m-asst-1",
        "RAG stands for Retrieval Augmented Generation.",
      );
    });

    // The quiz panel renders with the first question text
    await waitFor(() => {
      expect(screen.getByTestId("quiz-panel")).toBeInTheDocument();
    });

    // The first question text appears in the panel body
    const firstQuestion = screen.getByTestId("quiz-question-0");
    expect(firstQuestion).toHaveTextContent("What does RAG stand for in AI?");
  });

  it("closing the quiz panel removes it from the DOM", async () => {
    mockedChatApi.generateQuiz.mockResolvedValue({
      questions: MOCK_QUESTIONS,
    });

    await renderHydrated();

    const quizBtn = await screen.findByRole("button", {
      name: /quiz me on this message/i,
    });
    await act(async () => {
      fireEvent.click(quizBtn);
    });

    await waitFor(() => {
      expect(screen.getByTestId("quiz-panel")).toBeInTheDocument();
    });

    const closeBtn = screen.getByRole("button", { name: /close quiz panel/i });
    await act(async () => {
      fireEvent.click(closeBtn);
    });

    expect(screen.queryByTestId("quiz-panel")).not.toBeInTheDocument();
  });
});
