/**
 * P1-6 — frontend tests for the attachment composer affordances.
 *
 * Covers:
 *   1) clicking the paperclip triggers the hidden file input; a successful
 *      upload renders a chip with filename + size + a remove ×
 *   2) clicking × removes the chip without calling the upload endpoint again
 *   3) pasting a File from the clipboard triggers an upload + chip
 *   4) send → POST /api/v1/agents/stream carries the uploaded id in
 *      `attachment_ids`, and the chip row clears after send
 *   5) a failed upload surfaces the backend's error message under the composer
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
    uploadAttachment: vi.fn(),
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
import { chatApi, uploadAttachment } from "@/lib/chat-api";

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
const mockedUploadAttachment = uploadAttachment as unknown as Mock;

// ── Helpers ──────────────────────────────────────────────────────

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

function pngRow(id: string): {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
} {
  return {
    id,
    filename: "tiny.png",
    mime_type: "image/png",
    size_bytes: 2048,
  };
}

// ── Test suite ───────────────────────────────────────────────────

describe("Chat page — P1-6 attachments", () => {
  beforeEach(() => {
    routerReplace.mockReset();
    routerPush.mockReset();
    mockedChatApi.listConversations.mockReset();
    mockedChatApi.listConversations.mockResolvedValue([]);
    mockedChatApi.getConversation.mockReset();
    mockedUploadAttachment.mockReset();
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

  it("upload via file picker renders a chip with filename + size + remove", async () => {
    mockedUploadAttachment.mockResolvedValue(pngRow("att-1"));

    render(<ChatPage />);
    // Wait for hydration to settle.
    await waitFor(() => {
      expect(screen.getByLabelText(/Attach files/i)).toBeInTheDocument();
    });

    // Grab the hidden file input (sibling of the paperclip button).
    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    expect(fileInput).not.toBeNull();
    const file = new File([new Uint8Array(2048)], "tiny.png", {
      type: "image/png",
    });
    await act(async () => {
      fireEvent.change(fileInput, { target: { files: [file] } });
    });

    await waitFor(() => {
      expect(mockedUploadAttachment).toHaveBeenCalledTimes(1);
    });

    // Chip renders with the filename and a remove button.
    const chips = await screen.findByTestId("attachment-chips");
    expect(chips).toHaveTextContent("tiny.png");
    expect(chips).toHaveTextContent("2 KB");
    const removeBtn = screen.getByLabelText(/Remove tiny\.png/i);
    expect(removeBtn).toBeInTheDocument();

    // Click remove → chip disappears.
    await act(async () => {
      fireEvent.click(removeBtn);
    });
    expect(screen.queryByTestId("attachment-chips")).not.toBeInTheDocument();
    // Removal must NOT re-upload.
    expect(mockedUploadAttachment).toHaveBeenCalledTimes(1);
  });

  it("send includes attachment_ids in the stream body and clears the chip row", async () => {
    mockedUploadAttachment.mockResolvedValue(pngRow("att-send"));

    // Capture the fetch call so we can inspect the payload.
    const fetchSpy = vi.fn(async () => makeSSE(["ok"]));
    vi.stubGlobal("fetch", fetchSpy);

    render(<ChatPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/Attach files/i)).toBeInTheDocument();
    });

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = new File([new Uint8Array(10)], "tiny.png", {
      type: "image/png",
    });
    await act(async () => {
      fireEvent.change(fileInput, { target: { files: [file] } });
    });
    await screen.findByTestId("attachment-chips");

    // Type + send.
    const composer = screen.getByLabelText(/Message input/i);
    await act(async () => {
      fireEvent.change(composer, { target: { value: "look at this" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/Send message/i));
    });

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });

    // Verify the stream request body carried the pending id.
    const call = (fetchSpy.mock.calls as unknown[][]).find((c) =>
      String(c[0]).includes("/api/v1/agents/stream"),
    );
    expect(call).toBeDefined();
    const init = call![1] as RequestInit;
    const body = JSON.parse(String(init.body)) as {
      message: string;
      attachment_ids?: string[];
    };
    expect(body.message).toBe("look at this");
    expect(body.attachment_ids).toEqual(["att-send"]);

    // Chip row cleared after send.
    await waitFor(() => {
      expect(
        screen.queryByTestId("attachment-chips"),
      ).not.toBeInTheDocument();
    });
  });

  it("surfaces the upload error detail under the composer on failure", async () => {
    mockedUploadAttachment.mockRejectedValue(
      new Error("Unsupported attachment type: 'application/x-msdownload'."),
    );

    render(<ChatPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/Attach files/i)).toBeInTheDocument();
    });

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = new File([new Uint8Array([77, 90])], "evil.exe", {
      type: "application/x-msdownload",
    });
    await act(async () => {
      fireEvent.change(fileInput, { target: { files: [file] } });
    });

    await waitFor(() => {
      expect(
        screen.getByText(/Unsupported attachment type/i),
      ).toBeInTheDocument();
    });
    // No chip was produced.
    expect(screen.queryByTestId("attachment-chips")).not.toBeInTheDocument();
  });

  it("paste handler uploads clipboard files and renders chips", async () => {
    mockedUploadAttachment.mockResolvedValue(pngRow("att-paste"));

    render(<ChatPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/Message input/i)).toBeInTheDocument();
    });

    const composer = screen.getByLabelText(/Message input/i);
    const file = new File([new Uint8Array(10)], "tiny.png", {
      type: "image/png",
    });

    // React's synthetic ClipboardEvent wraps a DataTransfer-like surface. We
    // drive it through a fake `clipboardData.items` list that exposes the
    // same `.kind` / `.getAsFile()` contract the handler reads.
    const clipboardData = {
      items: [
        {
          kind: "file",
          type: "image/png",
          getAsFile: () => file,
        },
      ],
    };
    await act(async () => {
      fireEvent.paste(composer, { clipboardData });
    });

    await waitFor(() => {
      expect(mockedUploadAttachment).toHaveBeenCalledTimes(1);
    });
    const chips = await screen.findByTestId("attachment-chips");
    expect(chips).toHaveTextContent("tiny.png");
  });
});
