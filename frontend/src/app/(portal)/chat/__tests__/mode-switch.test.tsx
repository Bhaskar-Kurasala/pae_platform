/**
 * P2-10 — mode-switch + "Start new conversation" confirm dialog.
 *
 * Covers:
 *   1) switching mode MID-conversation does NOT clear messages and does NOT
 *      drop the server-side conversation id from the URL (the old behavior
 *      remounted `ChatArea` via `key={chatKey}` and wiped everything).
 *   2) the NEXT send after a mode switch carries the newly-selected
 *      `agent_name` in the stream request body — proving per-turn override
 *      reaches the backend.
 *   3) the composer's ⊕ "Start new conversation" button opens a confirm
 *      dialog; clicking Cancel keeps the current transcript + URL intact;
 *      clicking Start new clears messages, drops `?c=`, and resets the
 *      chat pane to its empty/welcome state.
 *
 * Heavy deps (IntersectionObserver, markdown renderer, auto-scroll) are
 * mocked so the test stays focused on page-level wiring.
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

// ── Module mocks (hoisted by vitest) ─────────────────────────────

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
  const actual =
    await vi.importActual<typeof import("@/lib/chat-api")>("@/lib/chat-api");
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
};

const mockedChatApi = chatApi as unknown as ChatApiMock;

// ── Helpers ──────────────────────────────────────────────────────

function makeSSEWithConversationId(
  id: string,
  chunks: string[],
  agentName?: string,
): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        encoder.encode(
          `data: ${JSON.stringify({
            conversation_id: id,
            ...(agentName ? { agent_name: agentName } : {}),
          })}\n\n`,
        ),
      );
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

function readSentBody(fetchSpy: Mock): {
  message?: string;
  agent_name?: string | null;
  conversation_id?: string | null;
} {
  const call = (fetchSpy.mock.calls as unknown[][]).find((c) =>
    String(c[0]).includes("/api/v1/agents/stream"),
  );
  if (!call) throw new Error("stream endpoint was not called");
  const init = call[1] as RequestInit;
  return JSON.parse(String(init.body)) as {
    message?: string;
    agent_name?: string | null;
    conversation_id?: string | null;
  };
}

// ── Test suite ───────────────────────────────────────────────────

describe("Chat page — P2-10 mode switch + start-new confirm", () => {
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
    mockedChatApi.listConversations.mockResolvedValue([]);
    mockedChatApi.getConversation.mockReset();
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

  it("switching mode mid-conversation preserves messages and conversation_id", async () => {
    // Fetch returns a conversation-id on the first send so we exit the
    // "fresh chat" empty state and get a real `?c=<id>`. The next send
    // (after the mode switch) re-echoes the same conversation_id to
    // prove we stayed in the same conversation.
    const fetchSpy = vi
      .fn()
      // First send → auto mode
      .mockImplementationOnce(async () =>
        makeSSEWithConversationId("conv-1", ["hello"]),
      )
      // Second send → tutor mode, same conversation
      .mockImplementationOnce(async () =>
        makeSSEWithConversationId("conv-1", [" back"], "socratic_tutor"),
      );
    vi.stubGlobal("fetch", fetchSpy);

    render(<ChatPage />);

    await waitFor(() => {
      expect(screen.getByLabelText(/message input/i)).toBeInTheDocument();
    });

    // First turn — auto mode (no chip selected).
    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "first turn" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/send message/i));
    });

    // First reply has landed; conversation id is live.
    await waitFor(() => {
      expect(screen.getByText("first turn")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(routerReplace).toHaveBeenCalledWith("/chat?c=conv-1");
    });

    // Now switch mode to Tutor. Under P2-10 this must NOT clear messages
    // and NOT remove `?c=conv-1` from the URL. The old behavior called
    // router.replace("/chat") and bumped chatKey, wiping transcript.
    const tutorChip = screen.getByRole("button", {
      name: /switch to tutor mode/i,
    });
    await act(async () => {
      fireEvent.click(tutorChip);
    });

    // Transcript is still here.
    expect(screen.getByText("first turn")).toBeInTheDocument();
    // URL is still `?c=conv-1` — router.replace was NOT called to strip it.
    expect(routerReplace).not.toHaveBeenCalledWith("/chat");
    // Chip now shows aria-pressed on Tutor.
    expect(tutorChip).toHaveAttribute("aria-pressed", "true");

    // Second turn — the per-turn agent_name override must reach the
    // backend as "socratic_tutor" (the newly-selected mode) and the
    // conversation_id must be "conv-1" (no new conversation created).
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "second turn" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/send message/i));
    });

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(2);
    });
    const secondCallInit = (fetchSpy.mock.calls as unknown[][])[1]![1] as RequestInit;
    const secondBody = JSON.parse(String(secondCallInit.body)) as {
      message: string;
      agent_name: string | null;
      conversation_id: string | null;
    };
    expect(secondBody.message).toBe("second turn");
    expect(secondBody.agent_name).toBe("socratic_tutor");
    expect(secondBody.conversation_id).toBe("conv-1");
  });

  it("first-turn send picks up the currently-selected mode as agent_name", async () => {
    const fetchSpy = vi.fn(async () =>
      makeSSEWithConversationId("conv-new", ["yo"], "coding_assistant"),
    );
    vi.stubGlobal("fetch", fetchSpy);

    render(<ChatPage />);

    await waitFor(() => {
      expect(screen.getByLabelText(/message input/i)).toBeInTheDocument();
    });

    // Pick Code Review BEFORE sending the first turn.
    const codeChip = screen.getByRole("button", {
      name: /switch to code review mode/i,
    });
    await act(async () => {
      fireEvent.click(codeChip);
    });

    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "review this" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/send message/i));
    });

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    const body = readSentBody(fetchSpy);
    expect(body.agent_name).toBe("coding_assistant");
  });

  it("Start new conversation button opens a confirm dialog; Cancel preserves state", async () => {
    const fetchSpy = vi.fn(async () =>
      makeSSEWithConversationId("conv-keep", ["ok"]),
    );
    vi.stubGlobal("fetch", fetchSpy);

    render(<ChatPage />);

    // Seed transcript so the ⊕ affordance renders.
    await waitFor(() => {
      expect(screen.getByLabelText(/message input/i)).toBeInTheDocument();
    });
    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "seed" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/send message/i));
    });
    await waitFor(() => {
      expect(screen.getByText("seed")).toBeInTheDocument();
    });

    // The ⊕ affordance should now be visible on the composer. There may be
    // two "start new conversation" triggers (sidebar New + composer ⊕);
    // grab the one inside the composer by its exact aria-label match.
    const startNewButtons = screen.getAllByRole("button", {
      name: /^start new conversation$/i,
    });
    // The composer ⊕ is the one rendered inside the InputBar.
    const composerStartNew = startNewButtons[startNewButtons.length - 1]!;
    await act(async () => {
      fireEvent.click(composerStartNew);
    });

    // Dialog is open.
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/start a new conversation/i);
    expect(dialog).toHaveTextContent(/move to the sidebar/i);

    // Cancel → dialog closes; transcript is intact. Scope the query to the
    // dialog body so the outside-click backdrop (also aria-labelled "Cancel")
    // isn't a collision. The Cancel TEXT button is the visible one.
    const cancelButtons = screen.getAllByRole("button", { name: /^cancel$/i });
    // Pick the one that actually carries the visible "Cancel" text — the
    // backdrop button has aria-label only and no text content.
    const cancelBtn = cancelButtons.find((b) => b.textContent?.trim() === "Cancel");
    expect(cancelBtn).toBeDefined();
    await act(async () => {
      fireEvent.click(cancelBtn!);
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("seed")).toBeInTheDocument();
  });

  it("Start new conversation confirm clears transcript and drops ?c=", async () => {
    const fetchSpy = vi.fn(async () =>
      makeSSEWithConversationId("conv-gone", ["ok"]),
    );
    vi.stubGlobal("fetch", fetchSpy);

    render(<ChatPage />);

    await waitFor(() => {
      expect(screen.getByLabelText(/message input/i)).toBeInTheDocument();
    });
    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "throwaway" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/send message/i));
    });
    await waitFor(() => {
      expect(screen.getByText("throwaway")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(routerReplace).toHaveBeenCalledWith("/chat?c=conv-gone");
    });

    const startNewButtons = screen.getAllByRole("button", {
      name: /^start new conversation$/i,
    });
    const composerStartNew = startNewButtons[startNewButtons.length - 1]!;
    await act(async () => {
      fireEvent.click(composerStartNew);
    });

    // Confirm.
    const confirmBtn = await screen.findByRole("button", { name: /^start new$/i });
    await act(async () => {
      fireEvent.click(confirmBtn);
    });

    // Transcript cleared — the user's prior prompt is gone.
    await waitFor(() => {
      expect(screen.queryByText("throwaway")).not.toBeInTheDocument();
    });
    // URL is reset to /chat (no ?c=). router.replace is called with "/chat".
    expect(routerReplace).toHaveBeenLastCalledWith("/chat");
    // Dialog closed.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
