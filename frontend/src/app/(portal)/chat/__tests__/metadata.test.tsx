/**
 * P2-5 — Message metadata hover popover.
 *
 * The assistant bubble's agent-label caption should expose a hover/focus
 * popover that summarises the persisted metadata:
 *   - model id (e.g. `claude-sonnet-4-6`)
 *   - first-token latency + total duration
 *   - prompt + completion token counts
 *
 * When the backend returns a conversation whose assistant row carries
 * these fields, `messageFromServer` propagates them into `StreamMessage`
 * and `AssistantBubble` wraps the caption in `MessageMetadataPopover`.
 * Historical rows (all NULL) render the caption plainly — no popover —
 * so the UI doesn't flash a useless "— — —".
 *
 * Heavy deps (next/navigation, markdown, smart auto-scroll) are stubbed
 * so we exercise only the popover wiring. We pre-seed chatApi.getConversation
 * to return a persisted assistant turn with metadata, navigate to the chat
 * page with `?c=<id>`, and assert the popover trigger's accessible name
 * encodes the spec string.
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
import { render, screen, waitFor } from "@testing-library/react";

// ── next/navigation ──────────────────────────────────────────────
let currentSearchParams = new URLSearchParams("c=conv-metadata-1");
const searchParamsSubscribers = new Set<() => void>();

const routerReplace = vi.fn();
const routerPush = vi.fn();

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

// ── chatApi — stubbed sidebar + pre-seeded conversation w/ metadata ──
vi.mock("@/lib/chat-api", () => ({
  chatApi: {
    listConversations: vi.fn(async () => [
      {
        id: "conv-metadata-1",
        title: "Metadata test",
        agent_name: "socratic_tutor",
        updated_at: new Date().toISOString(),
        archived_at: null,
        pinned_at: null,
        message_count: 2,
      },
    ]),
    getConversation: vi.fn(async () => ({
      id: "conv-metadata-1",
      user_id: "user-1",
      agent_name: "socratic_tutor",
      title: "Metadata test",
      archived_at: null,
      pinned_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      messages: [
        {
          id: "user-msg-1",
          conversation_id: "conv-metadata-1",
          role: "user",
          content: "explain recursion",
          agent_name: null,
          token_count: null,
          parent_id: null,
          created_at: new Date().toISOString(),
        },
        {
          id: "assistant-msg-1",
          conversation_id: "conv-metadata-1",
          role: "assistant",
          content: "Recursion is a function that calls itself.",
          agent_name: "socratic_tutor",
          token_count: null,
          parent_id: "user-msg-1",
          created_at: new Date().toISOString(),
          first_token_ms: 123,
          total_duration_ms: 2300,
          input_tokens: 450,
          output_tokens: 890,
          model: "claude-sonnet-4-6",
          my_feedback: null,
          sibling_ids: [],
        },
      ],
    })),
    postFeedback: vi.fn(),
    renameConversation: vi.fn(),
    archiveConversation: vi.fn(),
    pinConversation: vi.fn(),
    deleteConversation: vi.fn(),
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
};
const mockedChatApi = chatApi as unknown as ChatApiMock;

describe("Chat page — P2-5 message metadata popover", () => {
  beforeEach(() => {
    routerReplace.mockClear();
    routerPush.mockClear();
    currentSearchParams = new URLSearchParams("c=conv-metadata-1");
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

  it("renders a metadata popover on the assistant bubble with the spec format", async () => {
    render(<ChatPage />);

    // Wait for the conversation to hydrate.
    await waitFor(() => {
      expect(mockedChatApi.getConversation).toHaveBeenCalledWith(
        "conv-metadata-1",
      );
    });

    // The popover trigger renders as a button wrapping the agent-label
    // caption. `aria-label` encodes the full summary line per the tracker
    // spec: `{model} · {first} first / {total} total · {in} in / {out} out tokens`.
    const trigger = await screen.findByTestId("message-metadata-trigger");
    expect(trigger).toBeTruthy();
    const aria = trigger.getAttribute("aria-label") ?? "";
    // Spec format — all four pieces must appear in order.
    expect(aria).toContain("claude-sonnet-4-6");
    expect(aria).toContain("123ms first");
    expect(aria).toContain("2.3s total");
    expect(aria).toContain("450 in");
    expect(aria).toContain("890 out");

    // The popover body (always mounted, visibility via CSS) carries the
    // individual metric rows as <dt>/<dd> pairs for accessibility.
    const popover = screen.getByTestId("message-metadata-popover");
    expect(popover.getAttribute("role")).toBe("tooltip");
    expect(popover.textContent).toContain("claude-sonnet-4-6");
    expect(popover.textContent).toContain("123ms");
    expect(popover.textContent).toContain("2.3s");
    expect(popover.textContent).toContain("450");
    expect(popover.textContent).toContain("890");
  });

  it("omits the popover when the assistant row has no metadata (historical rows)", async () => {
    // Override the seed for this one test — no metadata fields at all.
    mockedChatApi.getConversation.mockReset();
    mockedChatApi.getConversation.mockResolvedValue({
      id: "conv-metadata-1",
      user_id: "user-1",
      agent_name: "socratic_tutor",
      title: "Historical",
      archived_at: null,
      pinned_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      messages: [
        {
          id: "user-msg-2",
          conversation_id: "conv-metadata-1",
          role: "user",
          content: "explain recursion",
          agent_name: null,
          token_count: null,
          parent_id: null,
          created_at: new Date().toISOString(),
        },
        {
          id: "assistant-msg-2",
          conversation_id: "conv-metadata-1",
          role: "assistant",
          content: "Recursion is a function that calls itself.",
          agent_name: "socratic_tutor",
          token_count: null,
          parent_id: "user-msg-2",
          created_at: new Date().toISOString(),
          // Intentionally missing: first_token_ms / total_duration_ms /
          // input_tokens / output_tokens / model. These rows pre-date
          // the P2-5 migration.
          my_feedback: null,
          sibling_ids: [],
        },
      ],
    });

    render(<ChatPage />);

    await waitFor(() => {
      expect(mockedChatApi.getConversation).toHaveBeenCalled();
    });

    // The assistant content still renders.
    await waitFor(() => {
      const md = screen.queryAllByTestId("md");
      expect(
        md.some((el) =>
          (el.textContent ?? "").includes("Recursion is a function"),
        ),
      ).toBe(true);
    });

    // But the metadata popover is NOT rendered for historical rows.
    expect(screen.queryByTestId("message-metadata-trigger")).toBeNull();
    expect(screen.queryByTestId("message-metadata-popover")).toBeNull();
  });
});
