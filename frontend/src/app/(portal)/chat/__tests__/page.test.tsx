/**
 * P0-3 page-level tests — sidebar loads real conversations, clicking hydrates
 * messages + updates the URL, initial mount honors `?c=`, and the first
 * SSE `conversation_id` optimistically inserts a sidebar row + updates the URL.
 *
 * Heavy deps (IntersectionObserver, markdown renderer work, auto-scroll) are
 * mocked so the test stays focused on page-level wiring. `chatApi` + `fetch`
 * are mocked per-test.
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

// Reactive search-params holder. The page uses `router.replace(/chat?c=...)`
// to update the URL; in real Next the `useSearchParams` hook then re-emits
// the new params, triggering the page's URL-sync effect. We mirror that
// here by (a) parsing the next path on every router.replace call and (b)
// bumping a counter state so any consumer re-renders with the new value.
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
    // Subscribe to the external mutable holder so each router.replace
    // triggers a re-render with fresh params — matches Next's behavior.
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

// `chatApi` is the sole gateway to `/api/v1/chat/*` — mocking it lets us
// shape the sidebar + hydration responses without intercepting fetch twice.
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

// Stub the auto-scroll hook (IntersectionObserver + scrollIntoView) — we
// don't need real behavior here, and jsdom doesn't implement IO.
vi.mock("@/hooks/use-smart-auto-scroll", () => ({
  useSmartAutoScroll: () => ({ isAtBottom: true, jumpToBottom: vi.fn() }),
}));

// Markdown renderer pulls in a big tree + highlight.js. Keep tests fast
// and deterministic with a passthrough.
vi.mock("@/components/features/markdown-renderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="md">{content}</div>
  ),
}));

// Only used for DISC-38 prefill — mock to no-op so tests without submission_id
// don't need to worry about it.
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

function makeConversation(
  id: string,
  title: string,
  agent: string | null = null,
  opts: { pinnedAt?: string | null; archivedAt?: string | null } = {},
): {
  id: string;
  title: string;
  agent_name: string | null;
  updated_at: string;
  archived_at: string | null;
  pinned_at: string | null;
  message_count: number;
} {
  return {
    id,
    title,
    agent_name: agent,
    updated_at: new Date().toISOString(),
    archived_at: opts.archivedAt ?? null,
    pinned_at: opts.pinnedAt ?? null,
    message_count: 2,
  };
}

function makeConversationDetail(
  id: string,
  msgs: Array<{ role: "user" | "assistant"; content: string }>,
  opts: { title?: string; pinnedAt?: string | null; archivedAt?: string | null } = {},
): {
  id: string;
  user_id: string;
  agent_name: string | null;
  title: string;
  archived_at: string | null;
  pinned_at: string | null;
  created_at: string;
  updated_at: string;
  messages: Array<{
    id: string;
    conversation_id: string;
    role: "user" | "assistant" | "system";
    content: string;
    agent_name: string | null;
    token_count: number | null;
    parent_id: null;
    created_at: string;
  }>;
} {
  return {
    id,
    user_id: "u1",
    agent_name: null,
    title: opts.title ?? "Hydrated",
    archived_at: opts.archivedAt ?? null,
    pinned_at: opts.pinnedAt ?? null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    messages: msgs.map((m, i) => ({
      id: `${id}-m${i}`,
      conversation_id: id,
      role: m.role,
      content: m.content,
      agent_name: null,
      token_count: null,
      parent_id: null,
      created_at: new Date().toISOString(),
    })),
  };
}

/**
 * Build an SSE response whose first event carries `conversation_id`,
 * then some content, then `done`. Models a fresh-conversation stream.
 */
function makeSSEWithConversationId(id: string, chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        encoder.encode(`data: ${JSON.stringify({ conversation_id: id })}\n\n`),
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

// ── Test suite ───────────────────────────────────────────────────

describe("Chat page — P0-3 sidebar + URL sync", () => {
  beforeEach(() => {
    // Reset mocks between tests.
    routerReplace.mockReset();
    routerPush.mockReset();
    // Re-install the search-params mutator so URL navigations from the
    // component propagate into useSearchParams for the next test.
    routerReplace.mockImplementation((path: string) => {
      setSearchParamsFromPath(path);
    });
    routerPush.mockImplementation((path: string) => {
      setSearchParamsFromPath(path);
    });
    mockedChatApi.listConversations.mockReset();
    mockedChatApi.getConversation.mockReset();
    mockedChatApi.renameConversation.mockReset();
    mockedChatApi.archiveConversation.mockReset();
    mockedChatApi.pinConversation.mockReset();
    mockedChatApi.deleteConversation.mockReset();
    currentSearchParams = new URLSearchParams();
    for (const cb of searchParamsSubscribers) cb();

    // Default: no-op scrollIntoView (jsdom).
    if (!("scrollIntoView" in HTMLElement.prototype)) {
      // @ts-expect-error patching jsdom prototype
      HTMLElement.prototype.scrollIntoView = () => {};
    }

    // Clean localStorage between runs (last-viewed-id state).
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the sidebar with conversations fetched on mount", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "RAG basics", "socratic_tutor"),
      makeConversation("c2", "Python review", "coding_assistant"),
    ]);

    render(<ChatPage />);

    // Loading spinner appears first.
    expect(screen.getByLabelText(/loading conversations/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("RAG basics")).toBeInTheDocument();
      expect(screen.getByText("Python review")).toBeInTheDocument();
    });
    expect(mockedChatApi.listConversations).toHaveBeenCalledTimes(1);
  });

  it("renders an empty-state when the server returns no conversations", async () => {
    mockedChatApi.listConversations.mockResolvedValue([]);

    render(<ChatPage />);

    await waitFor(() => {
      expect(screen.getByText(/no conversations yet/i)).toBeInTheDocument();
    });
  });

  it("clicking a sidebar row fetches the detail and updates the URL to ?c=<id>", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "RAG basics"),
    ]);
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c1", [
        { role: "user", content: "what is rag?" },
        { role: "assistant", content: "retrieval augmented generation" },
      ]),
    );

    render(<ChatPage />);

    const row = await screen.findByRole("button", {
      name: /open conversation: rag basics/i,
    });

    await act(async () => {
      fireEvent.click(row);
    });

    await waitFor(() => {
      expect(mockedChatApi.getConversation).toHaveBeenCalledWith("c1");
    });

    // URL updated via router.replace so back/forward works.
    expect(routerReplace).toHaveBeenCalledWith("/chat?c=c1");

    // Hydrated messages visible.
    await waitFor(() => {
      expect(screen.getByText("what is rag?")).toBeInTheDocument();
    });

    // last-viewed-id persisted so a reload re-renders the same conversation.
    expect(window.localStorage.getItem("chat-last-viewed-v1")).toBe("c1");
  });

  it("initial mount with ?c=<id> hydrates that conversation", async () => {
    // Seed the reactive holder so useSearchParams returns c=c42 on mount.
    setSearchParamsFromPath("/chat?c=c42");
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c42", "Preloaded"),
    ]);
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c42", [
        { role: "user", content: "preloaded question" },
      ]),
    );

    render(<ChatPage />);

    await waitFor(() => {
      expect(mockedChatApi.getConversation).toHaveBeenCalledWith("c42");
    });
    await waitFor(() => {
      expect(screen.getByText("preloaded question")).toBeInTheDocument();
    });
  });

  it("clicking 'New conversation' clears active state and drops ?c=", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "Existing"),
    ]);
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c1", [{ role: "user", content: "hi" }]),
    );

    render(<ChatPage />);

    // Open the existing conversation first.
    const row = await screen.findByRole("button", {
      name: /open conversation: existing/i,
    });
    await act(async () => {
      fireEvent.click(row);
    });
    await waitFor(() => {
      expect(routerReplace).toHaveBeenCalledWith("/chat?c=c1");
    });

    // Now click the "+" button in the sidebar header.
    const newBtn = screen.getAllByRole("button", {
      name: /new conversation/i,
    })[0];
    await act(async () => {
      fireEvent.click(newBtn);
    });

    // URL goes back to /chat (no ?c=).
    expect(routerReplace).toHaveBeenLastCalledWith("/chat");
    // last-viewed-id wiped.
    expect(window.localStorage.getItem("chat-last-viewed-v1")).toBeNull();
  });

  it("first send on a fresh conversation: SSE conversation_id inserts sidebar row + updates URL", async () => {
    mockedChatApi.listConversations.mockResolvedValue([]);

    // Stub global fetch so `useStream.sendMessage` returns our scripted SSE.
    const fetchSpy = vi.fn(async () =>
      makeSSEWithConversationId("fresh-conv", ["hello", " there"]),
    );
    vi.stubGlobal("fetch", fetchSpy);

    render(<ChatPage />);

    // Wait for empty sidebar to settle before typing.
    await screen.findByText(/no conversations yet/i);

    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "hey tutor" } });
    });

    const sendBtn = screen.getByRole("button", { name: /send message/i });
    await act(async () => {
      fireEvent.click(sendBtn);
    });

    // URL gets replaced with the server-assigned id.
    await waitFor(() => {
      expect(routerReplace).toHaveBeenCalledWith("/chat?c=fresh-conv");
    });

    // Sidebar gained a row without re-fetching the list.
    await waitFor(() => {
      // Dedup by id — there's exactly one "Open conversation:" button.
      const rows = screen.getAllByRole("button", {
        name: /open conversation:/i,
      });
      expect(rows).toHaveLength(1);
    });
    expect(mockedChatApi.listConversations).toHaveBeenCalledTimes(1);

    // last-viewed-id got written.
    expect(window.localStorage.getItem("chat-last-viewed-v1")).toBe(
      "fresh-conv",
    );
  });

  it("falls back to last-viewed-id when there is no ?c= on mount", async () => {
    window.localStorage.setItem("chat-last-viewed-v1", "c99");
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c99", "Last time"),
    ]);
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c99", [{ role: "user", content: "old q" }]),
    );

    render(<ChatPage />);

    await waitFor(() => {
      expect(mockedChatApi.getConversation).toHaveBeenCalledWith("c99");
    });
  });
});

// ── P1-8 — sidebar management (search, rename, pin, archive, delete) ──
describe("Chat page — P1-8 sidebar management", () => {
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
    mockedChatApi.renameConversation.mockReset();
    mockedChatApi.archiveConversation.mockReset();
    mockedChatApi.pinConversation.mockReset();
    mockedChatApi.deleteConversation.mockReset();
    currentSearchParams = new URLSearchParams();
    for (const cb of searchParamsSubscribers) cb();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("renders a Pinned header + divider when any row has pinned_at", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("p1", "Starred one", null, {
        pinnedAt: new Date().toISOString(),
      }),
      makeConversation("r1", "Ordinary"),
    ]);

    render(<ChatPage />);

    await screen.findByText("Starred one");
    expect(screen.getByText(/^pinned$/i)).toBeInTheDocument();
    expect(screen.getByText(/^recent$/i)).toBeInTheDocument();
    // The pin icon is aria-labelled and appears next to the title.
    expect(screen.getByLabelText("Pinned")).toBeInTheDocument();
  });

  it("debounces the search input and refetches with q=", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "RAG basics"),
    ]);

    render(<ChatPage />);

    // Initial mount fetch (no q, include_archived=false).
    await waitFor(() => {
      expect(mockedChatApi.listConversations).toHaveBeenCalledTimes(1);
    });
    expect(mockedChatApi.listConversations).toHaveBeenLastCalledWith({
      includeArchived: false,
      q: undefined,
    });

    const searchInput = screen.getByLabelText(/search conversations/i);
    await act(async () => {
      fireEvent.change(searchInput, { target: { value: "rag" } });
    });

    // Debounce is 300ms; wait for the refetch to land.
    await waitFor(
      () => {
        expect(mockedChatApi.listConversations).toHaveBeenCalledTimes(2);
      },
      { timeout: 2000 },
    );
    expect(mockedChatApi.listConversations).toHaveBeenLastCalledWith({
      includeArchived: false,
      q: "rag",
    });
  });

  it("toggles 'Show archived' and refetches with include_archived=true", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "Active"),
    ]);

    render(<ChatPage />);

    await waitFor(() => {
      expect(mockedChatApi.listConversations).toHaveBeenCalledTimes(1);
    });

    const toggle = screen.getByLabelText(/show archived conversations/i);
    await act(async () => {
      fireEvent.click(toggle);
    });

    await waitFor(() => {
      expect(mockedChatApi.listConversations).toHaveBeenLastCalledWith({
        includeArchived: true,
        q: undefined,
      });
    });
  });

  it("inline rename: Enter commits and updates the sidebar row", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "Original title"),
    ]);
    mockedChatApi.renameConversation.mockResolvedValue({
      id: "c1",
      user_id: "u1",
      agent_name: null,
      title: "New title",
      archived_at: null,
      pinned_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      messages: [],
    });

    render(<ChatPage />);

    await screen.findByText("Original title");

    // Open the row's ⋯ menu.
    const menuBtn = screen.getByRole("button", { name: /conversation actions/i });
    await act(async () => {
      fireEvent.click(menuBtn);
    });

    const renameItem = screen.getByRole("menuitem", { name: /rename/i });
    await act(async () => {
      fireEvent.click(renameItem);
    });

    const input = screen.getByLabelText(/rename conversation/i) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: "New title" } });
      fireEvent.keyDown(input, { key: "Enter" });
    });

    await waitFor(() => {
      expect(mockedChatApi.renameConversation).toHaveBeenCalledWith(
        "c1",
        "New title",
      );
    });
    await waitFor(() => {
      expect(screen.getByText("New title")).toBeInTheDocument();
    });
  });

  it("pin toggle: POST pin then sort pinned row above the rest", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("a", "Alpha"),
      makeConversation("b", "Beta"),
    ]);
    const pinStamp = new Date().toISOString();
    mockedChatApi.pinConversation.mockResolvedValue({
      id: "b",
      user_id: "u1",
      agent_name: null,
      title: "Beta",
      archived_at: null,
      pinned_at: pinStamp,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      messages: [],
    });

    render(<ChatPage />);
    await screen.findByText("Beta");

    // Open the Beta row's ⋯ menu (second row).
    const menuBtns = screen.getAllByRole("button", {
      name: /conversation actions/i,
    });
    // Rows render Alpha first, Beta second.
    await act(async () => {
      fireEvent.click(menuBtns[1]);
    });

    const pinItem = screen.getByRole("menuitem", { name: /^pin conversation$/i });
    await act(async () => {
      fireEvent.click(pinItem);
    });

    await waitFor(() => {
      expect(mockedChatApi.pinConversation).toHaveBeenCalledWith("b", true);
    });

    // Pinned header now present, with Beta listed above Alpha.
    await waitFor(() => {
      expect(screen.getByText(/^pinned$/i)).toBeInTheDocument();
    });
  });

  it("delete: confirms via dialog then removes the row + resets active if open", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "To delete"),
    ]);
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c1", [{ role: "user", content: "hi" }]),
    );
    mockedChatApi.deleteConversation.mockResolvedValue(undefined);

    render(<ChatPage />);

    // Open it first so we exercise the "reset active pane" branch.
    const row = await screen.findByRole("button", {
      name: /open conversation: to delete/i,
    });
    await act(async () => {
      fireEvent.click(row);
    });
    await waitFor(() => {
      expect(routerReplace).toHaveBeenCalledWith("/chat?c=c1");
    });

    // Open menu → Delete → confirm.
    const menuBtn = screen.getByRole("button", { name: /conversation actions/i });
    await act(async () => {
      fireEvent.click(menuBtn);
    });
    const deleteItem = screen.getByRole("menuitem", {
      name: /delete conversation/i,
    });
    await act(async () => {
      fireEvent.click(deleteItem);
    });

    // Confirm dialog appears.
    expect(
      screen.getByRole("dialog", { name: /confirm delete conversation/i }),
    ).toBeInTheDocument();

    const confirmBtn = screen.getByRole("button", { name: /confirm delete/i });
    await act(async () => {
      fireEvent.click(confirmBtn);
    });

    await waitFor(() => {
      expect(mockedChatApi.deleteConversation).toHaveBeenCalledWith("c1");
    });
    // Row gone.
    await waitFor(() => {
      expect(screen.queryByText("To delete")).not.toBeInTheDocument();
    });
    // URL reset — last replace is /chat (not /chat?c=c1).
    expect(routerReplace).toHaveBeenLastCalledWith("/chat");
  });

  it("archive toggle: hides the row by default but keeps it when 'Show archived' is on", async () => {
    // First fetch: two unarchived rows.
    mockedChatApi.listConversations.mockResolvedValueOnce([
      makeConversation("c1", "Will archive"),
      makeConversation("c2", "Keeps"),
    ]);
    const archivedStamp = new Date().toISOString();
    mockedChatApi.archiveConversation.mockResolvedValue({
      id: "c1",
      user_id: "u1",
      agent_name: null,
      title: "Will archive",
      archived_at: archivedStamp,
      pinned_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      messages: [],
    });

    render(<ChatPage />);
    await screen.findByText("Will archive");

    const menuBtns = screen.getAllByRole("button", {
      name: /conversation actions/i,
    });
    await act(async () => {
      fireEvent.click(menuBtns[0]);
    });

    const archiveItem = screen.getByRole("menuitem", {
      name: /archive conversation/i,
    });
    await act(async () => {
      fireEvent.click(archiveItem);
    });

    await waitFor(() => {
      expect(mockedChatApi.archiveConversation).toHaveBeenCalledWith(
        "c1",
        true,
      );
    });
    // Row removed from the default view.
    await waitFor(() => {
      expect(screen.queryByText("Will archive")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Keeps")).toBeInTheDocument();
  });
});
