/**
 * P2-6 mobile sidebar drawer tests.
 *
 * The desktop sidebar is `hidden lg:flex`; on mobile viewports we surface
 * a hamburger button in the top bar that opens a slide-in drawer hosting
 * the same `<ChatSidebar />`. These tests simulate a `<lg` viewport via
 * `window.matchMedia` + `innerWidth` and exercise the three closing paths:
 * backdrop tap, row selection, and (skipped here) swipe-to-close.
 *
 * Heavy deps (IntersectionObserver, markdown renderer, auto-scroll) are
 * mocked just like page.test.tsx so the test stays focused on the drawer
 * wiring.
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

function makeConversation(
  id: string,
  title: string,
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
    agent_name: null,
    updated_at: new Date().toISOString(),
    archived_at: null,
    pinned_at: null,
    message_count: 2,
  };
}

function makeConversationDetail(
  id: string,
  msgs: Array<{ role: "user" | "assistant"; content: string }>,
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
    title: "Hydrated",
    archived_at: null,
    pinned_at: null,
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
 * Simulate a mobile viewport (<lg breakpoint = 1024px in Tailwind 4).
 * We can't flip `display: none` / `display: flex` for `hidden lg:flex`
 * in jsdom because jsdom doesn't evaluate CSS media queries — but the
 * drawer logic only depends on state, not on CSS. This helper exists
 * to match the mental model + in case a future component reads matchMedia.
 */
function forceMobileViewport(): void {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 500,
  });
  Object.defineProperty(window, "innerHeight", {
    configurable: true,
    value: 800,
  });
  // Minimal matchMedia shim that always reports `matches: false` for
  // `min-width: 1024px` and true for `max-width: 1023px`.
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: /max-width/.test(query) ? true : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

// ── Test suite ───────────────────────────────────────────────────

describe("Chat page — P2-6 mobile drawer", () => {
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

    if (!("scrollIntoView" in HTMLElement.prototype)) {
      // @ts-expect-error patching jsdom prototype
      HTMLElement.prototype.scrollIntoView = () => {};
    }

    window.localStorage.clear();
    forceMobileViewport();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the hamburger 'Open conversations' button on mobile", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "RAG basics"),
    ]);

    render(<ChatPage />);

    // Hamburger has an accessible label.
    const hamburger = await screen.findByRole("button", {
      name: /open conversations/i,
    });
    expect(hamburger).toBeInTheDocument();
  });

  it("clicking the hamburger opens the drawer", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "RAG basics"),
    ]);

    render(<ChatPage />);

    const hamburger = await screen.findByRole("button", {
      name: /open conversations/i,
    });

    // Drawer is unmounted when closed — the testid shouldn't exist yet.
    expect(
      screen.queryByTestId("mobile-conversations-drawer"),
    ).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(hamburger);
    });

    // Drawer is mounted + positioned on-screen.
    const drawer = await screen.findByTestId("mobile-conversations-drawer");
    expect(drawer.className).toMatch(/translate-x-0/);
    // Close button (the backdrop) becomes available once open.
    expect(
      screen.getByRole("button", { name: /close conversations/i }),
    ).toBeInTheDocument();
  });

  it("backdrop tap closes the drawer", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "RAG basics"),
    ]);

    render(<ChatPage />);

    const hamburger = await screen.findByRole("button", {
      name: /open conversations/i,
    });
    await act(async () => {
      fireEvent.click(hamburger);
    });

    // Drawer is mounted now.
    expect(
      screen.getByTestId("mobile-conversations-drawer"),
    ).toBeInTheDocument();

    const backdrop = screen.getByRole("button", {
      name: /close conversations/i,
    });

    await act(async () => {
      fireEvent.click(backdrop);
    });

    // Drawer is unmounted on close.
    await waitFor(() => {
      expect(
        screen.queryByTestId("mobile-conversations-drawer"),
      ).not.toBeInTheDocument();
    });
  });

  it("selecting a conversation row closes the drawer", async () => {
    mockedChatApi.listConversations.mockResolvedValue([
      makeConversation("c1", "RAG basics"),
    ]);
    mockedChatApi.getConversation.mockResolvedValue(
      makeConversationDetail("c1", [
        { role: "user", content: "what is rag?" },
      ]),
    );

    render(<ChatPage />);

    const hamburger = await screen.findByRole("button", {
      name: /open conversations/i,
    });
    await act(async () => {
      fireEvent.click(hamburger);
    });

    // Drawer is open — grab the row from within the drawer. The same
    // label exists in the desktop sidebar too (also mounted, just
    // `hidden lg:flex` in production CSS), so scope the query to the
    // drawer subtree.
    const drawer = screen.getByTestId("mobile-conversations-drawer");
    const row = await waitFor(() => {
      const btn = drawer.querySelector(
        'button[aria-label="Open conversation: RAG basics"]',
      );
      if (!btn) throw new Error("row not yet rendered in drawer");
      return btn as HTMLButtonElement;
    });

    await act(async () => {
      fireEvent.click(row);
    });

    // Drawer is unmounted on selection.
    await waitFor(() => {
      expect(
        screen.queryByTestId("mobile-conversations-drawer"),
      ).not.toBeInTheDocument();
    });
    // Selection still hydrates the conversation as normal.
    await waitFor(() => {
      expect(mockedChatApi.getConversation).toHaveBeenCalledWith("c1");
    });
  });

  // Swipe-to-close is wired via touch events on the drawer aside. jsdom
  // doesn't simulate real gesture mechanics (no pointer events pipeline,
  // no native touchAction handling), so verifying the handler's behaviour
  // in isolation would mostly assert implementation details. We skip it
  // here and leave the gesture to manual + Playwright E2E coverage.
  it.skip("swipe-left on the drawer closes it (covered in E2E)", () => {});
});
