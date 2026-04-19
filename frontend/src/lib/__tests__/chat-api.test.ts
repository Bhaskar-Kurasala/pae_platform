/**
 * Tests for the chat-api helpers (P1-9 — export to Markdown).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  exportConversationMarkdown,
  filenameFromDisposition,
  uploadAttachment,
} from "@/lib/chat-api";

const CONV_ID = "abcdef12-3456-7890-abcd-ef1234567890";
const AUTH_TOKEN = "test-token-xyz";

function seedAuthStorage(token: string | null): void {
  if (token === null) {
    window.localStorage.removeItem("auth-storage");
    return;
  }
  window.localStorage.setItem(
    "auth-storage",
    JSON.stringify({ state: { token } }),
  );
}

describe("filenameFromDisposition", () => {
  it("extracts the filename from a quoted attachment header", () => {
    expect(
      filenameFromDisposition('attachment; filename="conversation-abcd1234-20260419.md"'),
    ).toBe("conversation-abcd1234-20260419.md");
  });

  it("falls back when no header is provided", () => {
    expect(filenameFromDisposition(null)).toBe("conversation.md");
  });

  it("accepts custom fallbacks", () => {
    expect(filenameFromDisposition(null, "fallback.md")).toBe("fallback.md");
  });

  it("handles unquoted filename= values", () => {
    expect(filenameFromDisposition("attachment; filename=plain.md")).toBe(
      "plain.md",
    );
  });
});

describe("exportConversationMarkdown", () => {
  const originalFetch = globalThis.fetch;
  const originalCreateObjectURL = URL.createObjectURL;
  const originalRevokeObjectURL = URL.revokeObjectURL;

  beforeEach(() => {
    seedAuthStorage(AUTH_TOKEN);
    // Stub URL.createObjectURL / revokeObjectURL (jsdom doesn't implement them).
    URL.createObjectURL = vi.fn(() => "blob:mock-url");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    seedAuthStorage(null);
    vi.restoreAllMocks();
  });

  it("requests the correct URL with auth header and consumes the blob", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("# hello\n", {
        status: 200,
        headers: {
          "Content-Type": "text/markdown; charset=utf-8",
          "Content-Disposition": 'attachment; filename="conversation-abcd1234-20260419.md"',
        },
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const filename = await exportConversationMarkdown(CONV_ID);

    expect(filename).toBe("conversation-abcd1234-20260419.md");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain(`/api/v1/chat/conversations/${CONV_ID}/export?format=md`);
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe(`Bearer ${AUTH_TOKEN}`);
    // Browser download path fired.
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it("still calls fetch even when there is no stored token (server will 401)", async () => {
    seedAuthStorage(null);
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response("# hello\n", {
          status: 200,
          headers: {
            "Content-Type": "text/markdown; charset=utf-8",
            "Content-Disposition": 'attachment; filename="conversation.md"',
          },
        }),
      );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await expect(exportConversationMarkdown(CONV_ID)).resolves.toBeDefined();
    const init = (fetchMock.mock.calls[0] as [string, RequestInit])[1];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("throws a descriptive error on non-2xx responses", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response("boom", {
        status: 500,
        statusText: "Internal Server Error",
      }),
    ) as unknown as typeof fetch;

    await expect(exportConversationMarkdown(CONV_ID)).rejects.toThrow(
      /Export failed: 500/,
    );
  });

  it("throws synchronously when conversationId is empty", async () => {
    await expect(exportConversationMarkdown("")).rejects.toThrow(
      /conversationId is required/,
    );
  });
});

describe("uploadAttachment", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    seedAuthStorage(AUTH_TOKEN);
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    seedAuthStorage(null);
    vi.restoreAllMocks();
  });

  it("POSTs multipart/form-data and returns the attachment row", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "11111111-2222-3333-4444-555555555555",
          filename: "tiny.png",
          mime_type: "image/png",
          size_bytes: 42,
        }),
        {
          status: 201,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const file = new File([new Uint8Array([1, 2, 3])], "tiny.png", {
      type: "image/png",
    });
    const row = await uploadAttachment(file);

    expect(row.filename).toBe("tiny.png");
    expect(row.mime_type).toBe("image/png");
    expect(row.size_bytes).toBe(42);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/chat/attachments");
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe(`Bearer ${AUTH_TOKEN}`);
    // Must not set Content-Type manually — the browser fills the multipart
    // boundary itself when the body is a FormData instance.
    expect(headers["Content-Type"]).toBeUndefined();
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("surfaces the backend's detail on 415", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "Unsupported attachment type: 'application/x-msdownload'." }),
        {
          status: 415,
          headers: { "Content-Type": "application/json" },
        },
      ),
    ) as unknown as typeof fetch;

    const file = new File([new Uint8Array([77, 90])], "evil.exe", {
      type: "application/x-msdownload",
    });
    await expect(uploadAttachment(file)).rejects.toThrow(
      /Unsupported attachment type/,
    );
  });

  it("falls back to status text when the body isn't JSON", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response("nope", { status: 413, statusText: "Payload Too Large" }),
    ) as unknown as typeof fetch;

    const file = new File([new Uint8Array([0])], "big.png", { type: "image/png" });
    await expect(uploadAttachment(file)).rejects.toThrow(/413/);
  });
});
