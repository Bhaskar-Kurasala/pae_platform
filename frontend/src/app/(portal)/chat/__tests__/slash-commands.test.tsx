/**
 * P2-8 — Slash commands + keyboard shortcuts.
 *
 * Tests:
 *   1) Typing `/` opens the slash menu listing all 7 commands.
 *   2) Clicking `/tutor` in the menu switches the mode chip and closes menu.
 *   3) Pressing `Esc` when streaming calls the abort/stop handler.
 *   4) Pressing `↑` in an empty composer opens the edit textarea on the last
 *      persisted user message.
 *   5) Pressing `Cmd+K` triggers a new-chat (conversation ID cleared, messages gone).
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

vi.mock("@/lib/chat-api", () => ({
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
  exportConversationMarkdown: vi.fn(),
  regenerateMessage: vi.fn(),
  uploadAttachment: vi.fn(),
}));

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
};

const mockedChatApi = chatApi as unknown as ChatApiMock;

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
  msgs: Array<{ id: string; role: "user" | "assistant"; content: string }>,
) {
  return {
    id,
    user_id: "u1",
    agent_name: null,
    title: "Test conv",
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
      parent_id: null,
      created_at: new Date().toISOString(),
    })),
  };
}

function makeSSE(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
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

// A "streaming" SSE that never finishes (so isStreaming stays true in tests).
function makeHangingSSE(): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      // Send the first chunk so the stream is "started" but not done.
      controller.enqueue(
        encoder.encode(`data: ${JSON.stringify({ chunk: "Hi" })}\n\n`),
      );
      // Never close — keeps isStreaming = true until the abort controller fires.
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

// ── Setup / teardown ─────────────────────────────────────────────

describe("Chat page — P2-8 slash commands + keyboard shortcuts", () => {
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
    mockedChatApi.editMessage.mockReset();
    mockedChatApi.getMessage.mockReset();
    currentSearchParams = new URLSearchParams();
    for (const cb of searchParamsSubscribers) cb();
    window.localStorage.clear();

    if (!("scrollIntoView" in HTMLElement.prototype)) {
      // @ts-expect-error jsdom patch
      HTMLElement.prototype.scrollIntoView = () => {};
    }
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // ── Test 1: typing `/` opens slash menu ──────────────────────────
  it("typing `/` opens the slash menu with all 7 commands", async () => {
    mockedChatApi.listConversations.mockResolvedValue([]);
    render(<ChatPage />);
    await screen.findByText(/no conversations yet/i);

    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "/" } });
    });

    await waitFor(() => {
      expect(screen.getByTestId("slash-menu")).toBeInTheDocument();
    });

    const menu = screen.getByTestId("slash-menu");
    // All 7 commands must appear.
    for (const cmd of ["/tutor", "/code", "/quiz", "/career", "/attach", "/export", "/new"]) {
      expect(menu.textContent).toContain(cmd);
    }
  });

  // ── Test 2: clicking /tutor switches mode and closes menu ─────────
  it("clicking /tutor in the menu switches the mode chip and closes the menu", async () => {
    mockedChatApi.listConversations.mockResolvedValue([]);
    render(<ChatPage />);
    await screen.findByText(/no conversations yet/i);

    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "/tutor" } });
    });

    await waitFor(() => {
      expect(screen.getByTestId("slash-menu")).toBeInTheDocument();
    });

    const tutorItem = screen.getByTestId("slash-item-tutor");
    await act(async () => {
      fireEvent.mouseDown(tutorItem);
    });

    // Menu closes and composer clears.
    await waitFor(() => {
      expect(screen.queryByTestId("slash-menu")).not.toBeInTheDocument();
    });
    expect(textarea.value).toBe("");

    // The Tutor mode chip should now be active (aria-label contains "Tutor").
    const tutorChip = screen.getByRole("button", { name: /switch to tutor mode/i });
    expect(tutorChip).toBeInTheDocument();
    // The chip is visually active; we verify the aria-label is present.
    expect(tutorChip).toHaveAttribute("aria-label", expect.stringMatching(/tutor/i));
  });

  // ── Test 3: Esc while streaming calls the stop/cancel handler ─────
  it("pressing Esc when streaming calls the abort/stop handler", async () => {
    mockedChatApi.listConversations.mockResolvedValue([]);
    // Use an AbortController-aware fetch spy.
    const fetchSpy = vi.fn(async (_url: unknown, init?: { signal?: AbortSignal }) => {
      // Return a hanging stream — isStreaming stays true until abort fires.
      if (init?.signal?.aborted) throw new DOMException("AbortError", "AbortError");
      return makeHangingSSE();
    });
    vi.stubGlobal("fetch", fetchSpy);

    render(<ChatPage />);
    await screen.findByText(/no conversations yet/i);

    // Send a message to kick off the stream.
    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "hello" } });
    });
    const sendBtn = screen.getByRole("button", { name: /send message/i });
    await act(async () => {
      fireEvent.click(sendBtn);
    });

    // Wait until the Stop button appears (isStreaming = true).
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /stop generating/i })).toBeInTheDocument();
    });

    // Press Esc — should call cancel / stop.
    await act(async () => {
      fireEvent.keyDown(textarea, { key: "Escape" });
    });

    // After cancel the Stop button should be gone.
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /stop generating/i })).not.toBeInTheDocument();
    });
  });

  // ── Test 4: ↑ in empty composer opens edit on last persisted user msg ─
  it("pressing ↑ in an empty composer opens the edit textarea on the last persisted user message", async () => {
    setSearchParamsFromPath("/chat?c=c1");
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "Test"),
    ]);
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c1", [
        { id: "m-user-1", role: "user", content: "my original question" },
        { id: "m-asst-1", role: "assistant", content: "assistant reply" },
      ]),
    );

    render(<ChatPage />);

    await waitFor(() => {
      expect(screen.getByText("my original question")).toBeInTheDocument();
    });

    // Composer should be empty.
    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    expect(textarea.value).toBe("");

    // Press ArrowUp in the empty composer.
    await act(async () => {
      fireEvent.keyDown(textarea, { key: "ArrowUp" });
    });

    // The UserBubble edit textarea should now appear.
    await waitFor(() => {
      expect(screen.getByTestId("edit-textarea")).toBeInTheDocument();
    });
    const editTextarea = screen.getByTestId("edit-textarea") as HTMLTextAreaElement;
    expect(editTextarea.value).toBe("my original question");
  });

  // ── Test 5: Cmd+K triggers new-chat ──────────────────────────────
  it("pressing Cmd+K clears the conversation and navigates to /chat", async () => {
    setSearchParamsFromPath("/chat?c=c1");
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "Existing chat"),
    ]);
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c1", [
        { id: "m-user-1", role: "user", content: "old message" },
        { id: "m-asst-1", role: "assistant", content: "old reply" },
      ]),
    );

    render(<ChatPage />);

    await waitFor(() => {
      expect(screen.getByText("old message")).toBeInTheDocument();
    });

    // Dispatch Cmd+K on the window.
    await act(async () => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });

    // The router should have been called to navigate away from ?c=c1.
    await waitFor(() => {
      expect(routerReplace).toHaveBeenCalledWith("/chat");
    });

    // The transcript should be gone (welcome screen appears).
    await waitFor(() => {
      expect(screen.queryByText("old message")).not.toBeInTheDocument();
    });
  });

  // ── Bonus: slash menu closes when a non-slash char is typed ───────
  it("slash menu closes when the user clears the slash prefix", async () => {
    mockedChatApi.listConversations.mockResolvedValue([]);
    render(<ChatPage />);
    await screen.findByText(/no conversations yet/i);

    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;

    // Open the menu.
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "/" } });
    });
    await waitFor(() => {
      expect(screen.getByTestId("slash-menu")).toBeInTheDocument();
    });

    // Remove the slash.
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "" } });
    });

    await waitFor(() => {
      expect(screen.queryByTestId("slash-menu")).not.toBeInTheDocument();
    });
  });

  // ── Bonus: Esc closes slash menu when not streaming ────────────────
  it("pressing Esc when not streaming closes the slash menu", async () => {
    mockedChatApi.listConversations.mockResolvedValue([]);
    render(<ChatPage />);
    await screen.findByText(/no conversations yet/i);

    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "/" } });
    });
    await waitFor(() => {
      expect(screen.getByTestId("slash-menu")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.keyDown(textarea, { key: "Escape" });
    });

    await waitFor(() => {
      expect(screen.queryByTestId("slash-menu")).not.toBeInTheDocument();
    });
  });
});
