/**
 * P2-3 — Agent identity before first token.
 *
 * The thinking bubble must render:
 *   - neutral "Thinking…" BEFORE the first SSE event (the brief
 *     pre-classification window);
 *   - "{DisplayName} is thinking…" as soon as the first SSE event arrives
 *     with `agent_name`, even when NO content token has streamed yet.
 *
 * We drive the real `useStream` hook via a scripted SSE stream so the
 * wiring between hook → pending message → AssistantBubble's isThinking
 * branch is exercised end-to-end (no mocks of useStream). Heavy deps
 * (IntersectionObserver / markdown / chat-api) are stubbed to keep the
 * test focused on the identity wiring.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

// ── next/navigation ──────────────────────────────────────────────
let currentSearchParams = new URLSearchParams();
const searchParamsSubscribers = new Set<() => void>();

function setSearchParamsFromPath(path: string): void {
  const q = path.includes("?") ? path.slice(path.indexOf("?") + 1) : "";
  currentSearchParams = new URLSearchParams(q);
  for (const cb of searchParamsSubscribers) cb();
}

const routerReplace = vi.fn((path: string) => setSearchParamsFromPath(path));
const routerPush = vi.fn((path: string) => setSearchParamsFromPath(path));

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

// ── chatApi — empty sidebar so we land straight on the welcome screen.
vi.mock("@/lib/chat-api", () => ({
  chatApi: {
    listConversations: vi.fn(async () => []),
    getConversation: vi.fn(),
    postFeedback: vi.fn(),
    renameConversation: vi.fn(),
    archiveConversation: vi.fn(),
    deleteConversation: vi.fn(),
  },
  exportConversationMarkdown: vi.fn(),
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
  postFeedback: Mock;
};
const mockedChatApi = chatApi as unknown as ChatApiMock;

/**
 * A controllable SSE response: individual events are only written when
 * `writeEvent` is called from the test. This lets us assert intermediate
 * render states (before the first event, after only the agent_name event,
 * etc.) without races.
 */
function makeControllableSSE(): {
  response: Response;
  writeEvent: (payload: unknown) => void;
  close: () => void;
} {
  const encoder = new TextEncoder();
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  const writeEvent = (payload: unknown) => {
    controller?.enqueue(
      encoder.encode(`data: ${JSON.stringify(payload)}\n\n`),
    );
  };
  const close = () => {
    controller?.close();
  };
  return {
    response: new Response(stream, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    }),
    writeEvent,
    close,
  };
}

describe("Chat page — P2-3 thinking identity", () => {
  beforeEach(() => {
    routerReplace.mockClear();
    routerPush.mockClear();
    mockedChatApi.listConversations.mockResolvedValue([]);
    currentSearchParams = new URLSearchParams();
    for (const cb of searchParamsSubscribers) cb();
    window.localStorage.clear();

    // jsdom lacks scrollIntoView.
    if (!("scrollIntoView" in HTMLElement.prototype)) {
      // @ts-expect-error patching jsdom prototype
      HTMLElement.prototype.scrollIntoView = () => {};
    }
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows neutral 'Thinking…' before the first SSE event, then '{Agent} is thinking…' once the agent name arrives", async () => {
    const sse = makeControllableSSE();
    // We need the fetch to resolve to our controllable response so the
    // reader starts consuming our scripted events.
    const fetchSpy = vi.fn(async () => sse.response);
    vi.stubGlobal("fetch", fetchSpy);

    render(<ChatPage />);

    // Sidebar settles — welcome screen is up.
    await screen.findByText(/no conversations yet/i);

    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "explain ReAct" } });
    });

    const sendBtn = screen.getByRole("button", { name: /send message/i });
    await act(async () => {
      fireEvent.click(sendBtn);
    });

    // Pre-classification: thinking bubble is up with neutral copy.
    const neutralLabel = await screen.findByTestId("thinking-label");
    expect(neutralLabel.textContent).toBe("Thinking…");

    // Now emit the first SSE event — conversation_id + agent_name, NO chunks.
    // This models what `backend/app/api/v1/routes/stream.py:179` sends
    // BEFORE any token is produced.
    await act(async () => {
      sse.writeEvent({
        conversation_id: "conv-1",
        agent_name: "socratic_tutor",
      });
      // Give the reader a tick to consume the event.
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    // The label must now reflect the routed agent WITHOUT any content token.
    await waitFor(() => {
      const label = screen.getByTestId("thinking-label");
      expect(label.textContent).toBe("Socratic Tutor is thinking…");
    });

    // The category dot has the learning-category teal class.
    const dot = screen.getByTestId("thinking-agent-dot");
    expect(dot.className).toContain("bg-teal-500");

    // Clean up the stream so the hook's finally: block runs.
    await act(async () => {
      sse.writeEvent({ done: true });
      sse.close();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  });

  it("falls back to 'Tutor is thinking…' when the first event carries agent_name='moa'", async () => {
    const sse = makeControllableSSE();
    const fetchSpy = vi.fn(async () => sse.response);
    vi.stubGlobal("fetch", fetchSpy);

    render(<ChatPage />);
    await screen.findByText(/no conversations yet/i);

    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "anything" } });
    });
    const sendBtn = screen.getByRole("button", { name: /send message/i });
    await act(async () => {
      fireEvent.click(sendBtn);
    });

    await act(async () => {
      sse.writeEvent({
        conversation_id: "conv-2",
        agent_name: "moa",
      });
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    await waitFor(() => {
      const label = screen.getByTestId("thinking-label");
      expect(label.textContent).toBe("Tutor is thinking…");
    });

    await act(async () => {
      sse.writeEvent({ done: true });
      sse.close();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  });
});
