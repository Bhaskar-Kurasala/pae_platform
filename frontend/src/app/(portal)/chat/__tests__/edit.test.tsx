/**
 * P1-1 — frontend tests for the user-message edit flow.
 *
 * The page hydrates a conversation from `chatApi.getConversation`, the user
 * clicks the Edit pencil on a user bubble, types a replacement, and hits
 * Save. We then verify:
 *   1) The bubble renders the inline editor on Edit click
 *   2) Cancel restores the original view without calling the API
 *   3) Save → POST /chat/messages/{id}/edit with the new content → trailing
 *      messages get dropped → a new stream is kicked off via fetch with the
 *      edited content (useStream's `sendMessage`)
 *   4) An empty draft keeps the editor open and shows an inline error
 *      without calling the API
 *   5) Non-persisted (live-streamed) user messages don't expose the pencil
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
  },
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
};

const mockedChatApi = chatApi as unknown as ChatApiMock;

// ── Helpers ──────────────────────────────────────────────────────

function makeConversation(
  id: string,
  title: string,
): {
  id: string;
  title: string;
  agent_name: string | null;
  updated_at: string;
  archived_at: null;
  pinned_at: null;
  message_count: number;
} {
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

// ── Test suite ───────────────────────────────────────────────────

describe("Chat page — P1-1 edit user message", () => {
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
    // Seed with ?c=c1 so the page hydrates on mount.
    setSearchParamsFromPath("/chat?c=c1");
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "Preloaded"),
    ]);
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c1", [
        { id: "m-user-1", role: "user", content: "original question" },
        { id: "m-asst-1", role: "assistant", content: "original answer" },
      ]),
    );

    render(<ChatPage />);

    await waitFor(() => {
      expect(screen.getByText("original question")).toBeInTheDocument();
    });
  }

  it("clicking Edit swaps the user bubble for an inline textarea", async () => {
    await renderHydrated();

    const editButton = await screen.findByTestId("edit-open");
    await act(async () => {
      fireEvent.click(editButton);
    });

    const textarea = await screen.findByTestId("edit-textarea");
    expect(textarea).toBeInTheDocument();
    expect((textarea as HTMLTextAreaElement).value).toBe("original question");
    expect(screen.getByTestId("edit-save")).toBeInTheDocument();
    expect(screen.getByTestId("edit-cancel")).toBeInTheDocument();
  });

  it("Cancel closes the editor without calling the API", async () => {
    await renderHydrated();

    await act(async () => {
      fireEvent.click(screen.getByTestId("edit-open"));
    });
    await screen.findByTestId("edit-textarea");

    await act(async () => {
      fireEvent.click(screen.getByTestId("edit-cancel"));
    });

    // Textarea gone, original bubble restored.
    expect(screen.queryByTestId("edit-textarea")).not.toBeInTheDocument();
    expect(screen.getByText("original question")).toBeInTheDocument();
    expect(mockedChatApi.editMessage).not.toHaveBeenCalled();
  });

  it("Save posts the edit, drops trailing messages, and re-streams", async () => {
    await renderHydrated();

    mockedChatApi.editMessage.mockResolvedValue({
      id: "m-user-2",
      conversation_id: "c1",
      role: "user",
      content: "rewritten question",
      agent_name: null,
      token_count: null,
      parent_id: "m-user-1",
      created_at: new Date().toISOString(),
    });

    // Intercept fetch for the re-stream call.
    const fetchSpy = vi.fn(async () => makeSSE(["new", " answer"]));
    vi.stubGlobal("fetch", fetchSpy);

    // Open editor.
    await act(async () => {
      fireEvent.click(screen.getByTestId("edit-open"));
    });
    const textarea = await screen.findByTestId("edit-textarea");
    // Change the draft.
    await act(async () => {
      fireEvent.change(textarea, {
        target: { value: "rewritten question" },
      });
    });
    // Save.
    await act(async () => {
      fireEvent.click(screen.getByTestId("edit-save"));
    });

    // API was hit with the right payload.
    await waitFor(() => {
      expect(mockedChatApi.editMessage).toHaveBeenCalledWith("m-user-1", {
        content: "rewritten question",
      });
    });

    // Re-stream fires to /api/v1/agents/stream with the new content.
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    const firstCall = (fetchSpy.mock.calls as unknown[][])[0];
    const init = firstCall?.[1] as
      | { method?: string; body?: string }
      | undefined;
    expect(init?.method).toBe("POST");
    const body = JSON.parse(init?.body ?? "{}") as { message?: string };
    expect(body.message).toBe("rewritten question");

    // The original assistant reply is no longer in the transcript (we trimmed
    // everything after the edited message before firing sendMessage). The new
    // user bubble carrying "rewritten question" shows up instead.
    await waitFor(() => {
      expect(screen.queryByText("original answer")).not.toBeInTheDocument();
    });
    expect(screen.getByText("rewritten question")).toBeInTheDocument();
  });

  it("empty draft disables Save and doesn't call the API", async () => {
    await renderHydrated();

    await act(async () => {
      fireEvent.click(screen.getByTestId("edit-open"));
    });
    const textarea = await screen.findByTestId("edit-textarea");
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "   " } });
    });

    const saveBtn = screen.getByTestId("edit-save") as HTMLButtonElement;
    // Whitespace-only drafts disable the button to prevent a useless round-trip.
    expect(saveBtn.disabled).toBe(true);

    // Fire the click anyway — the disabled attribute should block onClick.
    await act(async () => {
      fireEvent.click(saveBtn);
    });

    expect(mockedChatApi.editMessage).not.toHaveBeenCalled();
    // Editor stays open so the user can correct their input.
    expect(screen.getByTestId("edit-textarea")).toBeInTheDocument();
  });

  it("hides the pencil on a newly-streamed (not-yet-persisted) user message", async () => {
    // Empty start — no sidebar convo, no ?c=, so initialMessages is undefined
    // and any message the user sends lives only client-side until a reload.
    mockedChatApi.listConversations.mockResolvedValue([]);
    const fetchSpy = vi.fn(async () => makeSSE(["ok"]));
    vi.stubGlobal("fetch", fetchSpy);

    render(<ChatPage />);
    await screen.findByText(/no conversations yet/i);

    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "first turn" } });
    });
    const sendBtn = screen.getByRole("button", { name: /send message/i });
    await act(async () => {
      fireEvent.click(sendBtn);
    });

    // The user bubble is in the DOM.
    await waitFor(() => {
      expect(screen.getByText("first turn")).toBeInTheDocument();
    });

    // But no Edit pencil is rendered because `isPersisted` is false for
    // client-generated ids (the SSE stream we mocked doesn't carry message ids).
    expect(screen.queryByTestId("edit-open")).not.toBeInTheDocument();
  });
});
