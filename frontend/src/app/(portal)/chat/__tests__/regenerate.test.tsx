/**
 * P1-2 — frontend tests for the Regenerate assistant-message flow.
 *
 * Covers:
 *   1) The Regenerate button is visible on hydrated assistant bubbles and
 *      hidden on client-only (not-yet-persisted) bubbles
 *   2) Clicking Regenerate streams a new variant that replaces the bubble
 *      content in place
 *   3) After regenerate, the sibling navigator `< 1 / 2 >` appears with
 *      the correct count
 *   4) Clicking the `<` arrow fetches the earlier sibling and swaps the
 *      bubble's content back
 *   5) Pre-hydrated conversations with `sibling_ids.length > 1` show the
 *      navigator immediately on load (no regenerate needed first)
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

describe("Chat page — P1-2 regenerate assistant message", () => {
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

  async function renderHydrated(
    messages?: Array<{
      id: string;
      role: "user" | "assistant";
      content: string;
      parent_id?: string | null;
      sibling_ids?: string[];
    }>,
  ): Promise<void> {
    setSearchParamsFromPath("/chat?c=c1");
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "Preloaded"),
    ]);
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail(
        "c1",
        messages ?? [
          { id: "m-user-1", role: "user", content: "explain recursion" },
          {
            id: "m-asst-1",
            role: "assistant",
            content: "original answer",
            parent_id: "m-user-1",
          },
        ],
      ),
    );

    render(<ChatPage />);
    await waitFor(() => {
      expect(screen.getByText("explain recursion")).toBeInTheDocument();
    });
  }

  it("shows the Regenerate button on hydrated assistant bubbles", async () => {
    await renderHydrated();

    const regenButtons = await screen.findAllByRole("button", {
      name: /regenerate response/i,
    });
    expect(regenButtons.length).toBeGreaterThan(0);
  });

  it("clicking Regenerate streams a new variant that replaces content", async () => {
    await renderHydrated();

    // Server response after the regenerate: the assistant bubble gets a fresh
    // id ("m-asst-2") and carries both siblings.
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c1", [
        { id: "m-user-1", role: "user", content: "explain recursion" },
        {
          id: "m-asst-2",
          role: "assistant",
          content: "fresh variant",
          parent_id: "m-user-1",
          sibling_ids: ["m-asst-1", "m-asst-2"],
        },
      ]),
    );

    mockedRegenerate.mockResolvedValue(
      makeSSE(["fresh", " variant"], {
        regenerated_from: "m-asst-1",
        agent_name: "socratic_tutor",
      }),
    );

    const regenBtn = await screen.findByRole("button", {
      name: /regenerate response/i,
    });
    await act(async () => {
      fireEvent.click(regenBtn);
    });

    // The regenerate fetch was called with the source assistant id.
    await waitFor(() => {
      expect(mockedRegenerate).toHaveBeenCalledWith("m-asst-1");
    });

    // Bubble swaps to the new content after the stream + hydrate.
    await waitFor(() => {
      expect(screen.getByText("fresh variant")).toBeInTheDocument();
    });
    expect(screen.queryByText("original answer")).not.toBeInTheDocument();
  });

  it("sibling navigator appears after regeneration with < 1 / 2 > counter", async () => {
    await renderHydrated();

    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c1", [
        { id: "m-user-1", role: "user", content: "explain recursion" },
        {
          id: "m-asst-2",
          role: "assistant",
          content: "variant two",
          parent_id: "m-user-1",
          sibling_ids: ["m-asst-1", "m-asst-2"],
        },
      ]),
    );

    mockedRegenerate.mockResolvedValue(makeSSE(["variant", " two"]));

    const regenBtn = await screen.findByRole("button", {
      name: /regenerate response/i,
    });
    await act(async () => {
      fireEvent.click(regenBtn);
    });

    // Navigator labels itself "Response 2 of 2" on the latest variant.
    await waitFor(() => {
      const nav = screen.getByTestId("sibling-navigator");
      expect(nav).toHaveAttribute("aria-label", "Response 2 of 2");
    });
    // Counter text "2 / 2" is visible in the UI.
    expect(screen.getByText(/2 \/ 2/)).toBeInTheDocument();
  });

  it("clicking the previous arrow fetches and swaps to the earlier sibling", async () => {
    // Start with a pre-hydrated conversation that already has two siblings.
    await renderHydrated([
      { id: "m-user-1", role: "user", content: "explain recursion" },
      {
        id: "m-asst-2",
        role: "assistant",
        content: "variant two",
        parent_id: "m-user-1",
        sibling_ids: ["m-asst-1", "m-asst-2"],
      },
    ]);

    mockedChatApi.getMessage.mockResolvedValue({
      id: "m-asst-1",
      conversation_id: "c1",
      role: "assistant",
      content: "variant one",
      agent_name: null,
      token_count: null,
      parent_id: "m-user-1",
      created_at: new Date().toISOString(),
      sibling_ids: ["m-asst-1", "m-asst-2"],
    });

    const prevBtn = await screen.findByRole("button", {
      name: /previous response/i,
    });
    await act(async () => {
      fireEvent.click(prevBtn);
    });

    await waitFor(() => {
      expect(mockedChatApi.getMessage).toHaveBeenCalledWith("m-asst-1");
    });
    await waitFor(() => {
      expect(screen.getByText("variant one")).toBeInTheDocument();
    });
    // Navigator now reads 1 of 2.
    const nav = screen.getByTestId("sibling-navigator");
    expect(nav).toHaveAttribute("aria-label", "Response 1 of 2");
  });

  it("navigator is not rendered when the assistant has no siblings", async () => {
    await renderHydrated();

    // sibling_ids was undefined in the default hydration fixture → no navigator.
    expect(
      screen.queryByRole("button", { name: /previous response/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /next response/i }),
    ).not.toBeInTheDocument();
  });

  it("pre-hydrated conversations with siblings show the navigator immediately", async () => {
    await renderHydrated([
      { id: "m-user-1", role: "user", content: "explain recursion" },
      {
        id: "m-asst-2",
        role: "assistant",
        content: "variant two",
        parent_id: "m-user-1",
        sibling_ids: ["m-asst-1", "m-asst-2"],
      },
    ]);

    const nav = await screen.findByTestId("sibling-navigator");
    expect(nav).toHaveAttribute("aria-label", "Response 2 of 2");
    expect(
      screen.getByRole("button", { name: /previous response/i }),
    ).toBeInTheDocument();
  });
});
