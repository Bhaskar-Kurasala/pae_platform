/**
 * P3-1 — frontend tests for the "Explain differently" hover action.
 *
 * Covers:
 *   1) The "Explain differently" trigger button appears on hydrated assistant bubbles
 *   2) Clicking the trigger opens the 4-option menu
 *   3) Clicking "Simpler" calls regenerateMessage with { explainStyle: "simpler" }
 *   4) Each of the 4 options calls regenerateMessage with the correct explainStyle
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
import { chatApi, regenerateMessage } from "@/lib/chat-api";

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
};

const mockedChatApi = chatApi as unknown as ChatApiMock;
const mockedRegenerate = regenerateMessage as unknown as Mock;

// ── Helpers ──────────────────────────────────────────────────────

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

function makeConversationDetail(
  id: string,
  msgs: Array<{
    id: string;
    role: "user" | "assistant";
    content: string;
    parent_id?: string | null;
    sibling_ids?: string[];
  }>,
) {
  return {
    id,
    user_id: "u1",
    agent_name: null,
    title: "Preloaded",
    archived_at: null,
    pinned_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    messages: msgs.map((m) => ({
      id: m.id,
      conversation_id: id,
      role: m.role as "user" | "assistant" | "system",
      content: m.content,
      agent_name: null,
      token_count: null,
      parent_id: m.parent_id ?? null,
      created_at: new Date().toISOString(),
      sibling_ids: m.sibling_ids,
    })),
  };
}

function makeSSE(chunks: string[], extraFirst?: Record<string, unknown>): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      if (extraFirst) {
        controller.enqueue(
          encoder.encode(
            `data: ${JSON.stringify({ chunk: "", ...extraFirst })}\n\n`,
          ),
        );
      }
      for (const c of chunks) {
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify({ chunk: c })}\n\n`),
        );
      }
      controller.enqueue(
        encoder.encode(`data: ${JSON.stringify({ done: true })}\n\n`),
      );
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

// ── Test suite ───────────────────────────────────────────────────

describe("Chat page — P3-1 Explain differently", () => {
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
    mockedChatApi.getMessage.mockReset();
    mockedRegenerate.mockReset();
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
      makeConversationDetail("c1", [
        { id: "m-user-1", role: "user", content: "explain recursion" },
        {
          id: "m-asst-1",
          role: "assistant",
          content: "original answer",
          parent_id: "m-user-1",
        },
      ]),
    );

    render(<ChatPage />);
    await waitFor(() => {
      expect(screen.getByText("explain recursion")).toBeInTheDocument();
    });
  }

  it("shows the 'Explain differently' button on hydrated assistant bubbles", async () => {
    await renderHydrated();

    const triggerBtn = await screen.findByTestId("explain-differently-trigger");
    expect(triggerBtn).toBeInTheDocument();
    expect(triggerBtn).toHaveAttribute("aria-label", "Explain differently");
  });

  it("clicking the trigger opens the dropdown menu with 4 options", async () => {
    await renderHydrated();

    const triggerBtn = await screen.findByTestId("explain-differently-trigger");
    await act(async () => {
      fireEvent.click(triggerBtn);
    });

    const menu = screen.getByTestId("explain-differently-menu");
    expect(menu).toBeInTheDocument();

    expect(screen.getByTestId("explain-option-simpler")).toBeInTheDocument();
    expect(screen.getByTestId("explain-option-more_rigorous")).toBeInTheDocument();
    expect(screen.getByTestId("explain-option-via_analogy")).toBeInTheDocument();
    expect(screen.getByTestId("explain-option-show_code")).toBeInTheDocument();
  });

  it("clicking 'Simpler' calls regenerateMessage with { explainStyle: 'simpler' }", async () => {
    await renderHydrated();

    mockedRegenerate.mockResolvedValue(
      makeSSE(["simpler answer"], { regenerated_from: "m-asst-1" }),
    );

    const triggerBtn = await screen.findByTestId("explain-differently-trigger");
    await act(async () => {
      fireEvent.click(triggerBtn);
    });

    const simplerOption = screen.getByTestId("explain-option-simpler");
    await act(async () => {
      fireEvent.click(simplerOption);
    });

    await waitFor(() => {
      expect(mockedRegenerate).toHaveBeenCalledWith(
        "m-asst-1",
        { explainStyle: "simpler" },
      );
    });
  });

  it.each([
    ["simpler",       "simpler"],
    ["more_rigorous", "more_rigorous"],
    ["via_analogy",   "via_analogy"],
    ["show_code",     "show_code"],
  ] as const)(
    "selecting '%s' passes explainStyle: '%s' to regenerateMessage",
    async (optionTestId, expectedStyle) => {
      await renderHydrated();

      mockedRegenerate.mockResolvedValue(
        makeSSE(["response"], { regenerated_from: "m-asst-1" }),
      );

      const triggerBtn = await screen.findByTestId("explain-differently-trigger");
      await act(async () => {
        fireEvent.click(triggerBtn);
      });

      const option = screen.getByTestId(`explain-option-${optionTestId}`);
      await act(async () => {
        fireEvent.click(option);
      });

      await waitFor(() => {
        expect(mockedRegenerate).toHaveBeenCalledWith(
          "m-asst-1",
          { explainStyle: expectedStyle },
        );
      });

      // Reset for next iteration
      mockedRegenerate.mockReset();
    },
  );

  it("menu closes after selecting an option", async () => {
    await renderHydrated();

    mockedRegenerate.mockResolvedValue(
      makeSSE(["response"], { regenerated_from: "m-asst-1" }),
    );

    const triggerBtn = await screen.findByTestId("explain-differently-trigger");
    await act(async () => {
      fireEvent.click(triggerBtn);
    });

    expect(screen.getByTestId("explain-differently-menu")).toBeInTheDocument();

    const option = screen.getByTestId("explain-option-simpler");
    await act(async () => {
      fireEvent.click(option);
    });

    expect(
      screen.queryByTestId("explain-differently-menu"),
    ).not.toBeInTheDocument();
  });
});
