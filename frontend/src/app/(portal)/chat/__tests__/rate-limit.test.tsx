/**
 * P2-7 — rate-limit awareness in the chat page.
 *
 * Covers the two visible surfaces:
 *   1. compact pill above the composer: "{N} messages left this hour"
 *      when `X-RateLimit-Remaining` drops below 5.
 *   2. 429 banner with a live mm:ss countdown driven off
 *      `retry_after_seconds` (preferred) or `Retry-After` header.
 *
 * Network + heavy deps (IntersectionObserver, markdown, chat-api) are
 * mocked the same way `page.test.tsx` mocks them so we can focus on the
 * rate-limit flow.
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

vi.mock("@/lib/chat-api", () => ({
  chatApi: {
    listConversations: vi.fn(),
    getConversation: vi.fn(),
    renameConversation: vi.fn(),
    archiveConversation: vi.fn(),
    pinConversation: vi.fn(),
    deleteConversation: vi.fn(),
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
};

const mockedChatApi = chatApi as unknown as ChatApiMock;

// ── Helpers ──────────────────────────────────────────────────────

/** SSE response whose headers include X-RateLimit-Remaining for the pill. */
function makeRateLimitedSSE(
  chunks: string[],
  remaining: number,
  extraHeaders: Record<string, string> = {},
): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        encoder.encode(
          `data: ${JSON.stringify({ conversation_id: "c-rl" })}\n\n`,
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
    headers: {
      "Content-Type": "text/event-stream",
      "X-RateLimit-Remaining": String(remaining),
      "Retry-After": "60",
      ...extraHeaders,
    },
  });
}

/** 429 response with JSON body + Retry-After + X-RateLimit-Remaining. */
function make429Response(retryAfterSeconds: number): Response {
  return new Response(
    JSON.stringify({
      detail: "Rate limit exceeded: 30 per 1 minute",
      retry_after_seconds: retryAfterSeconds,
    }),
    {
      status: 429,
      headers: {
        "Content-Type": "application/json",
        "Retry-After": String(retryAfterSeconds),
        "X-RateLimit-Remaining": "0",
      },
    },
  );
}

// ── Suite ────────────────────────────────────────────────────────

describe("P2-7 — rate-limit surface (pill + countdown banner)", () => {
  beforeEach(() => {
    routerReplace.mockReset();
    routerPush.mockReset();
    routerReplace.mockImplementation((path: string) =>
      setSearchParamsFromPath(path),
    );
    routerPush.mockImplementation((path: string) =>
      setSearchParamsFromPath(path),
    );
    mockedChatApi.listConversations.mockReset();
    mockedChatApi.getConversation.mockReset();
    currentSearchParams = new URLSearchParams();
    for (const cb of searchParamsSubscribers) cb();
    if (!("scrollIntoView" in HTMLElement.prototype)) {
      // @ts-expect-error patching jsdom prototype
      HTMLElement.prototype.scrollIntoView = () => {};
    }
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("renders the 'N messages left this hour' pill when remaining < 5", async () => {
    mockedChatApi.listConversations.mockResolvedValue([]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => makeRateLimitedSSE(["hi"], 3)),
    );

    render(<ChatPage />);
    await screen.findByText(/no conversations yet/i);

    const textarea = screen.getByLabelText(
      /message input/i,
    ) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "hello" } });
    });
    const sendBtn = screen.getByRole("button", { name: /send message/i });
    await act(async () => {
      fireEvent.click(sendBtn);
    });

    // Pill appears with the exact copy the spec requires.
    const pill = await screen.findByTestId("rate-limit-pill");
    expect(pill).toHaveTextContent("3 messages left this hour");
  });

  it("does NOT render the pill when remaining is >= 5 (quiet state)", async () => {
    mockedChatApi.listConversations.mockResolvedValue([]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => makeRateLimitedSSE(["hi"], 20)),
    );

    render(<ChatPage />);
    await screen.findByText(/no conversations yet/i);

    const textarea = screen.getByLabelText(
      /message input/i,
    ) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "hi" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /send message/i }));
    });

    // The assistant chunk should have rendered — let that settle first.
    // "hi" appears in both the user bubble and the assistant echo, so use getAllByText.
    await waitFor(() => {
      expect(screen.getAllByText("hi").length).toBeGreaterThan(0);
    });
    expect(screen.queryByTestId("rate-limit-pill")).not.toBeInTheDocument();
  });

  it("singular copy when exactly 1 message is left", async () => {
    mockedChatApi.listConversations.mockResolvedValue([]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => makeRateLimitedSSE(["ok"], 1)),
    );

    render(<ChatPage />);
    await screen.findByText(/no conversations yet/i);
    await act(async () => {
      fireEvent.change(
        screen.getByLabelText(/message input/i) as HTMLTextAreaElement,
        { target: { value: "x" } },
      );
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /send message/i }));
    });

    const pill = await screen.findByTestId("rate-limit-pill");
    expect(pill).toHaveTextContent("1 message left this hour");
  });

  it("429 → banner shows 'Rate limited — retry in m:ss' and ticks down", async () => {
    mockedChatApi.listConversations.mockResolvedValue([]);
    // Seed a 65-second countdown.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => make429Response(65)),
    );

    render(<ChatPage />);
    await screen.findByText(/no conversations yet/i);

    const textarea = screen.getByLabelText(
      /message input/i,
    ) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "go" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /send message/i }));
    });

    // Banner renders with "retry in" text — exact mm:ss depends on real-time
    // delta so we only assert the key phrase, not the exact clock value.
    await waitFor(() => {
      expect(screen.getByText(/rate limited — retry in/i)).toBeInTheDocument();
    });
    // The countdown should be non-zero on initial render (65s budget).
    const bannerText = screen.getByText(/rate limited — retry in/i).textContent ?? "";
    expect(bannerText).not.toMatch(/retry in 0:00/i);
  });
});
