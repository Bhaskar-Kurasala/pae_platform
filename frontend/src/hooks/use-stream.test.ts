import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import {
  buildHistoryPayload,
  useStream,
  type StreamError,
  type StreamMessage,
} from "./use-stream";
import { useAuthStore } from "@/stores/auth-store";

// ---------- buildHistoryPayload: pure-function coverage ----------

function mkMsg(
  role: "user" | "assistant",
  content: string,
  extra: Partial<StreamMessage> = {},
): StreamMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    timestamp: new Date(),
    ...extra,
  };
}

describe("buildHistoryPayload", () => {
  it("returns [] when there are no prior messages (first turn)", () => {
    expect(buildHistoryPayload([])).toEqual([]);
  });

  it("returns prior turns in chronological order with only role+content", () => {
    const prior: StreamMessage[] = [
      mkMsg("user", "first", { agentName: "socratic_tutor" }),
      mkMsg("assistant", "reply-1", { agentName: "socratic_tutor" }),
      mkMsg("user", "second"),
      mkMsg("assistant", "reply-2"),
    ];
    expect(buildHistoryPayload(prior)).toEqual([
      { role: "user", content: "first" },
      { role: "assistant", content: "reply-1" },
      { role: "user", content: "second" },
      { role: "assistant", content: "reply-2" },
    ]);
  });

  it("caps at 12 turns — older turns are dropped first", () => {
    // 20 short turns; only the last 12 should be kept.
    const prior: StreamMessage[] = [];
    for (let i = 0; i < 20; i++) {
      prior.push(mkMsg(i % 2 === 0 ? "user" : "assistant", `t${i}`));
    }
    const history = buildHistoryPayload(prior);
    expect(history).toHaveLength(12);
    expect(history[0]).toEqual({ role: "user", content: "t8" }); // 20 - 12 = 8
    expect(history[11]).toEqual({ role: "assistant", content: "t19" });
  });

  it("caps at 6000 chars before 12 turns when content is long", () => {
    // Six turns of 1200 chars each = 7200 chars total > 6000.
    // Walking backwards, the 6th (oldest) turn would push past 6000 and be dropped.
    // 5 * 1200 = 6000 exactly → 5 turns kept.
    const prior: StreamMessage[] = [];
    for (let i = 0; i < 6; i++) {
      prior.push(mkMsg(i % 2 === 0 ? "user" : "assistant", "x".repeat(1200)));
    }
    const history = buildHistoryPayload(prior);
    expect(history).toHaveLength(5);
    // Oldest kept is index 1, newest is index 5.
    expect(history[0].content.length).toBe(1200);
    expect(history[history.length - 1].content.length).toBe(1200);
    const total = history.reduce((sum, t) => sum + t.content.length, 0);
    expect(total).toBe(6000);
    expect(total).toBeLessThanOrEqual(6000);
  });

  it("excludes placeholder-thinking assistant messages", () => {
    const prior: StreamMessage[] = [
      mkMsg("user", "hello"),
      mkMsg("assistant", "", { isThinking: true }),
    ];
    expect(buildHistoryPayload(prior)).toEqual([
      { role: "user", content: "hello" },
    ]);
  });

  it("excludes empty-content turns defensively", () => {
    const prior: StreamMessage[] = [
      mkMsg("user", "a"),
      mkMsg("assistant", ""),
      mkMsg("user", "b"),
    ];
    expect(buildHistoryPayload(prior)).toEqual([
      { role: "user", content: "a" },
      { role: "user", content: "b" },
    ]);
  });

  it("strips non-contract fields (id, timestamp, agentName, isThinking)", () => {
    const prior: StreamMessage[] = [
      mkMsg("user", "hi", { agentName: "socratic_tutor" }),
    ];
    const history = buildHistoryPayload(prior);
    expect(history).toHaveLength(1);
    expect(Object.keys(history[0]).sort()).toEqual(["content", "role"]);
  });
});

// ---------- useStream integration: request body shape ----------

interface CapturedRequest {
  url: string;
  body: {
    message: string;
    agent_name: string | null;
    context: Record<string, unknown>;
  };
}

function makeSSEResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify({ chunk, done: false })}\n\n`),
        );
      }
      controller.enqueue(
        encoder.encode(`data: ${JSON.stringify({ chunk: "", done: true })}\n\n`),
      );
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("useStream sendMessage conversation_history payload", () => {
  const captured: CapturedRequest[] = [];
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    captured.length = 0;
    fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body ?? "{}")) as CapturedRequest["body"];
      captured.push({ url, body });
      return makeSSEResponse(["ok"]);
    });
    vi.stubGlobal("fetch", fetchSpy);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends empty conversation_history on the first message", async () => {
    const { result } = renderHook(() => useStream({ agentName: "socratic_tutor" }));

    await act(async () => {
      await result.current.sendMessage("what is RAG?");
    });

    expect(captured).toHaveLength(1);
    expect(captured[0].body.message).toBe("what is RAG?");
    expect(captured[0].body.context.conversation_history).toEqual([]);
  });

  it("sends prior turns on the second message, excluding the just-sent user text", async () => {
    const { result } = renderHook(() => useStream({ agentName: "socratic_tutor" }));

    await act(async () => {
      await result.current.sendMessage("what is RAG?");
    });

    // After the first turn completes, messages should contain the user message
    // and the assistant's streamed reply ("ok").
    await waitFor(() => {
      expect(result.current.messages).toHaveLength(2);
      expect(result.current.messages[1].content).toBe("ok");
      expect(result.current.messages[1].isThinking).toBe(false);
    });

    await act(async () => {
      await result.current.sendMessage("what did I just ask?");
    });

    expect(captured).toHaveLength(2);
    const secondHistory = captured[1].body.context
      .conversation_history as unknown[];
    // History carries turn 1 only — NOT the "what did I just ask?" message
    // (backend appends that itself at stream.py:259).
    expect(secondHistory).toEqual([
      { role: "user", content: "what is RAG?" },
      { role: "assistant", content: "ok" },
    ]);
    // The current user message must not be duplicated in history.
    expect(
      secondHistory.some(
        (t) =>
          typeof t === "object" &&
          t !== null &&
          (t as { content: string }).content === "what did I just ask?",
      ),
    ).toBe(false);
  });

  it("never includes the in-flight placeholder-thinking assistant bubble", async () => {
    const { result } = renderHook(() => useStream({ agentName: "socratic_tutor" }));

    await act(async () => {
      await result.current.sendMessage("first");
    });
    await act(async () => {
      await result.current.sendMessage("second");
    });

    const secondHistory = captured[1].body.context
      .conversation_history as Array<{ role: string; content: string }>;
    // No entry should have empty content (placeholders always start empty).
    expect(secondHistory.every((t) => t.content.length > 0)).toBe(true);
    // Nothing should carry the StreamMessage-only fields.
    for (const t of secondHistory) {
      expect(Object.keys(t).sort()).toEqual(["content", "role"]);
    }
  });
});

// ---------- useStream P2-2 microbenchmark: rAF token batching ----------

function makeManyChunkSSE(tokens: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const token of tokens) {
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify({ chunk: token })}\n\n`),
        );
      }
      controller.enqueue(
        encoder.encode(
          `data: ${JSON.stringify({ done: true, agent_name: "socratic_tutor" })}\n\n`,
        ),
      );
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("useStream — P2-2 rAF token batching", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("produces far fewer content-update renders than token count (< 100 for 500 tokens)", async () => {
    const N = 500;
    const tokens = Array.from({ length: N }, (_, i) =>
      String.fromCharCode(97 + (i % 26)),
    );
    const expectedContent = tokens.join("");

    fetchSpy = vi.fn(async () => makeManyChunkSSE(tokens));
    vi.stubGlobal("fetch", fetchSpy);

    // Count hook renders where the assistant content *grew* — each such
    // render corresponds to a setMessages call that mutated content. The
    // un-batched baseline produces ~N such renders; the batched path
    // coalesces many tokens per flush, producing well under N.
    let contentUpdateRenders = 0;
    let lastSeen = "";
    const { result } = renderHook(() => {
      const s = useStream();
      const assistant = s.messages.find((m) => m.role === "assistant");
      const content = assistant?.content ?? "";
      if (content && content !== lastSeen) {
        contentUpdateRenders += 1;
        lastSeen = content;
      }
      return s;
    });

    await act(async () => {
      await result.current.sendMessage("go");
    });

    await waitFor(() => {
      const last = result.current.messages[result.current.messages.length - 1];
      expect(last?.content.length).toBe(N);
    });

    // Correctness: byte-identical content, correct agent, thinking cleared.
    const assistant = result.current.messages.find((m) => m.role === "assistant");
    expect(assistant).toBeDefined();
    expect(assistant!.content).toBe(expectedContent);
    expect(assistant!.agentName).toBe("socratic_tutor");
    expect(assistant!.isThinking).toBe(false);

    // Performance guardrail: fewer than 100 content-update renders for 500
    // tokens. Catches un-batched regressions (which would produce ~500).
    expect(contentUpdateRenders).toBeLessThan(100);
    expect(contentUpdateRenders).toBeGreaterThan(0);
    console.log(
      `[P2-2] ${N} tokens → ${contentUpdateRenders} content-update renders`,
    );
  });
});

// ---------- useStream P0-5: distinct error kinds (401 / 429 / 5xx / network) ----------

function makeJsonErrorResponse(
  status: number,
  detail?: string,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(detail ? { detail } : {}), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function makeStreamErrorSSE(errorMessage: string): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        encoder.encode(`data: ${JSON.stringify({ chunk: "partial " })}\n\n`),
      );
      controller.enqueue(
        encoder.encode(`data: ${JSON.stringify({ error: errorMessage })}\n\n`),
      );
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function makeDroppingStreamSSE(): Response {
  // Mid-stream reader failure with no server-sent `error` event. Models the
  // "we got an OK response, then the connection dropped" case.
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        encoder.encode(`data: ${JSON.stringify({ chunk: "hi" })}\n\n`),
      );
      // Simulate network interruption by erroring the stream.
      controller.error(new Error("ECONNRESET"));
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("useStream — P0-5 error classification", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    useAuthStore.getState().clearAuth();
  });

  it("401 → error.kind === 'auth', assistant placeholder removed, user bubble kept", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => makeJsonErrorResponse(401, "Not authenticated")),
    );

    // Seed the store so we can observe that the hook's sendMessage surfaces
    // `auth` even when a token existed (the server just rejected it as expired).
    useAuthStore.setState({
      user: null,
      token: "dead-token",
      refreshToken: null,
      isAuthenticated: true,
    });

    const { result } = renderHook(() => useStream());

    await act(async () => {
      await result.current.sendMessage("hi");
    });

    await waitFor(() => {
      expect(result.current.error).not.toBeNull();
    });

    const err = result.current.error as StreamError;
    expect(err.kind).toBe("auth");
    expect(err.message).toMatch(/session expired/i);
    // Assistant placeholder should be gone; only the user bubble remains.
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].role).toBe("user");
    expect(result.current.messages[0].content).toBe("hi");
  });

  it("429 with Retry-After: 15 → error.kind === 'rate_limit' with retryAfterMs === 15000", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        makeJsonErrorResponse(429, "Rate limit exceeded", { "Retry-After": "15" }),
      ),
    );

    const { result } = renderHook(() => useStream());

    await act(async () => {
      await result.current.sendMessage("too fast");
    });

    await waitFor(() => {
      expect(result.current.error).not.toBeNull();
    });

    const err = result.current.error as StreamError;
    expect(err.kind).toBe("rate_limit");
    expect(err.retryAfterMs).toBe(15_000);
    expect(err.message).toMatch(/rate limit exceeded/i);
  });

  it("429 without Retry-After → retryAfterMs falls back to 30000", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => makeJsonErrorResponse(429, "slow down")),
    );

    const { result } = renderHook(() => useStream());
    await act(async () => {
      await result.current.sendMessage("x");
    });
    await waitFor(() => {
      expect(result.current.error?.kind).toBe("rate_limit");
    });
    expect(result.current.error?.retryAfterMs).toBe(30_000);
  });

  it("500 with {detail: 'boom'} → error.kind === 'server', message contains 'boom'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => makeJsonErrorResponse(500, "boom")),
    );

    const { result } = renderHook(() => useStream());

    await act(async () => {
      await result.current.sendMessage("trigger");
    });

    await waitFor(() => {
      expect(result.current.error).not.toBeNull();
    });

    const err = result.current.error as StreamError;
    expect(err.kind).toBe("server");
    expect(err.message).toContain("boom");
  });

  it("500 without body → error.kind === 'server', generic copy", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(null, {
            status: 500,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );

    const { result } = renderHook(() => useStream());
    await act(async () => {
      await result.current.sendMessage("x");
    });
    await waitFor(() => {
      expect(result.current.error?.kind).toBe("server");
    });
    expect(result.current.error?.message).toMatch(/something went wrong/i);
  });

  it("fetch rejects → error.kind === 'network'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    const { result } = renderHook(() => useStream());

    await act(async () => {
      await result.current.sendMessage("are you there?");
    });

    await waitFor(() => {
      expect(result.current.error).not.toBeNull();
    });

    expect(result.current.error?.kind).toBe("network");
    // Assistant placeholder cleaned up; user bubble kept for retry.
    expect(result.current.messages.filter((m) => m.role === "assistant")).toHaveLength(0);
    expect(result.current.messages.filter((m) => m.role === "user")).toHaveLength(1);
  });

  it("mid-stream server-sent error event → error.kind === 'server' (body was present)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => makeStreamErrorSSE("model crashed")));

    const { result } = renderHook(() => useStream());

    await act(async () => {
      await result.current.sendMessage("crash");
    });

    await waitFor(() => {
      expect(result.current.error).not.toBeNull();
    });

    const err = result.current.error as StreamError;
    expect(err.kind).toBe("server");
    expect(err.message).toContain("model crashed");
  });

  it("mid-stream reader failure without server error → error.kind === 'network'", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => makeDroppingStreamSSE()));

    const { result } = renderHook(() => useStream());

    await act(async () => {
      await result.current.sendMessage("please answer");
    });

    await waitFor(() => {
      expect(result.current.error).not.toBeNull();
    });

    expect(result.current.error?.kind).toBe("network");
  });

  it("clearAuthForReauth() clears the auth store — UI invokes this on 401 action", async () => {
    const { clearAuthForReauth } = await import("./use-stream");
    useAuthStore.setState({
      user: { id: "u1", email: "a@b.c", full_name: "A", role: "student" },
      token: "expired",
      refreshToken: "r",
      isAuthenticated: true,
    });
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    clearAuthForReauth();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().token).toBeNull();
  });

  it("retry() is a no-op when error.kind === 'auth'", async () => {
    const fetchSpy = vi.fn(async () => makeJsonErrorResponse(401));
    vi.stubGlobal("fetch", fetchSpy);

    const { result } = renderHook(() => useStream());

    await act(async () => {
      await result.current.sendMessage("hi");
    });
    await waitFor(() => {
      expect(result.current.error?.kind).toBe("auth");
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.retry();
    });

    // retry must not fire a second fetch when the prior error was auth.
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});

// ---------- useStream P0-4: cancel() during streaming ----------

/**
 * Build a never-ending SSE response whose controller is captured so the
 * test can push chunks, then call `cancel()` and close the stream. Models
 * a real in-flight stream the user interrupts.
 */
function makePausedSSE(): {
  response: Response;
  pushChunk: (text: string) => void;
  close: () => void;
} {
  const encoder = new TextEncoder();
  let ctl!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      ctl = controller;
    },
  });
  const response = new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
  return {
    response,
    pushChunk: (text: string) => {
      ctl.enqueue(
        encoder.encode(`data: ${JSON.stringify({ chunk: text })}\n\n`),
      );
    },
    close: () => {
      try {
        ctl.close();
      } catch {
        /* already closed / errored */
      }
    },
  };
}

describe("useStream — P0-4 cancel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  /**
   * Harness that runs a cancel scenario end-to-end against a paused SSE
   * stream. Kicks off `sendMessage` without awaiting (the stream hangs
   * until we close it), lets the test do its setup/act, calls cancel,
   * then closes the stream so the hanging sendMessage promise resolves
   * and the test runner doesn't unmount the hook from under us.
   */
  async function runCancelScenario(fn: (args: {
    result: { current: ReturnType<typeof useStream> };
    pushChunk: (text: string) => void;
    waitUntilStreaming: () => Promise<void>;
  }) => Promise<void>): Promise<void> {
    const { response, pushChunk, close } = makePausedSSE();
    vi.stubGlobal("fetch", vi.fn(async () => response));

    const { result } = renderHook(() => useStream());

    // Kick off sendMessage but keep its promise alive outside act — the
    // stream won't complete until we close it at the end of the scenario.
    // Wrapping the initial call in act ensures the initial setMessages
    // calls (user bubble + placeholder) flush before the test inspects.
    let sendPromise: Promise<void>;
    act(() => {
      sendPromise = result.current.sendMessage("hello");
    });

    const waitUntilStreaming = async () => {
      await waitFor(() => {
        expect(result.current.isStreaming).toBe(true);
      });
    };

    try {
      await fn({ result, pushChunk, waitUntilStreaming });
    } finally {
      // Let the now-aborted reader finish (or close cleanly if the test
      // didn't cancel) so the hanging sendMessage promise resolves and
      // vitest cleanly unmounts the hook.
      close();
      await sendPromise!.catch(() => {});
    }
  }

  it("cancel() while streaming calls AbortController.abort() and sets isStreaming=false", async () => {
    const abortSpy = vi.spyOn(AbortController.prototype, "abort");

    await runCancelScenario(async ({ result, pushChunk, waitUntilStreaming }) => {
      await waitUntilStreaming();

      // Deliver a token so the assistant bubble has partial content.
      await act(async () => {
        pushChunk("partial ");
        await Promise.resolve();
      });

      await act(async () => {
        result.current.cancel();
      });

      expect(abortSpy).toHaveBeenCalled();

      await waitFor(() => {
        expect(result.current.isStreaming).toBe(false);
      });

      // No error set — cancel is user-intent, not a failure.
      expect(result.current.error).toBeNull();
    });
  });

  it("cancel() appends the `_[stopped]_` marker to the assistant message", async () => {
    await runCancelScenario(async ({ result, pushChunk, waitUntilStreaming }) => {
      await waitUntilStreaming();

      await act(async () => {
        pushChunk("tokens-");
        await Promise.resolve();
      });

      await act(async () => {
        result.current.cancel();
      });

      await waitFor(() => {
        const last = result.current.messages[result.current.messages.length - 1];
        expect(last?.content).toMatch(/_\[stopped\]_$/);
      });

      const last = result.current.messages[result.current.messages.length - 1];
      // Partial content preserved AND the marker is appended below it.
      expect(last?.content).toContain("tokens-");
      expect(last?.content).toContain("_[stopped]_");
      expect(last?.isThinking).toBe(false);
    });
  });

  it("cancel() flushes pending rAF-buffered tokens before stamping the marker", async () => {
    // If the buffer isn't drained first, the last chunk would be dropped
    // and `_[stopped]_` would stick onto a stale snapshot of content.
    await runCancelScenario(async ({ result, pushChunk, waitUntilStreaming }) => {
      await waitUntilStreaming();

      // Push several chunks in one tick — they coalesce into a single
      // rAF-scheduled flush. Cancel drains the buffer before stamping.
      await act(async () => {
        pushChunk("a");
        pushChunk("b");
        pushChunk("c");
        await Promise.resolve();
      });

      await act(async () => {
        result.current.cancel();
      });

      await waitFor(() => {
        const last = result.current.messages[result.current.messages.length - 1];
        expect(last?.content).toMatch(/_\[stopped\]_$/);
      });

      const last = result.current.messages[result.current.messages.length - 1];
      // Every chunk made it into the final content — the flush happened.
      expect(last?.content).toContain("a");
      expect(last?.content).toContain("b");
      expect(last?.content).toContain("c");
    });
  });

  it("cancel() does NOT set error", async () => {
    await runCancelScenario(async ({ result, pushChunk, waitUntilStreaming }) => {
      await waitUntilStreaming();

      await act(async () => {
        pushChunk("word ");
        await Promise.resolve();
      });

      await act(async () => {
        result.current.cancel();
      });

      await waitFor(() => expect(result.current.isStreaming).toBe(false));
      expect(result.current.error).toBeNull();
    });
  });

  it("cancel() on a non-streaming hook is a safe no-op (doesn't throw, doesn't stamp)", () => {
    const { result } = renderHook(() => useStream());

    // Fresh hook — nothing streaming, no assistant bubble.
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages).toHaveLength(0);

    expect(() => {
      act(() => {
        result.current.cancel();
      });
    }).not.toThrow();

    // No bubble materialized, no error raised.
    expect(result.current.messages).toHaveLength(0);
    expect(result.current.error).toBeNull();
  });
});

// ---------- useStream P0-3: conversation_id plumbing ----------

function makeSSEWithConversationId(id: string, chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      // First event carries the conversation_id — matches what the backend
      // emits at stream.py when a fresh conversation is created.
      controller.enqueue(
        encoder.encode(
          `data: ${JSON.stringify({ conversation_id: id })}\n\n`,
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

describe("useStream — P0-3 conversation_id plumbing", () => {
  interface ConvCapture {
    body: {
      message: string;
      conversation_id: string | null;
      agent_name: string | null;
    };
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("first send with no initial id posts conversation_id: null", async () => {
    const captured: ConvCapture[] = [];
    const fetchSpy = vi.fn(async (_url: string, init?: RequestInit) => {
      captured.push({
        body: JSON.parse(String(init?.body ?? "{}")),
      });
      return makeSSEWithConversationId("conv-123", ["ok"]);
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { result } = renderHook(() => useStream());

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(captured).toHaveLength(1);
    expect(captured[0].body.conversation_id).toBeNull();
  });

  it("sends the provided conversationId option on the first request", async () => {
    const captured: ConvCapture[] = [];
    const fetchSpy = vi.fn(async (_url: string, init?: RequestInit) => {
      captured.push({ body: JSON.parse(String(init?.body ?? "{}")) });
      return makeSSEResponse(["ok"]);
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { result } = renderHook(() =>
      useStream({ conversationId: "pre-existing-id" }),
    );

    await act(async () => {
      await result.current.sendMessage("hi again");
    });

    expect(captured[0].body.conversation_id).toBe("pre-existing-id");
  });

  it("fires onConversationId exactly once when the first SSE event supplies one", async () => {
    const onConv = vi.fn();
    const fetchSpy = vi.fn(async () =>
      makeSSEWithConversationId("conv-xyz", ["a", "b"]),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const { result } = renderHook(() =>
      useStream({ onConversationId: onConv }),
    );

    await act(async () => {
      await result.current.sendMessage("start");
    });

    await waitFor(() => {
      expect(result.current.conversationId).toBe("conv-xyz");
    });

    expect(onConv).toHaveBeenCalledTimes(1);
    expect(onConv).toHaveBeenCalledWith("conv-xyz");
  });

  it("a subsequent send reuses the conversation_id received on the prior turn", async () => {
    const captured: ConvCapture[] = [];
    let callIdx = 0;
    const fetchSpy = vi.fn(async (_url: string, init?: RequestInit) => {
      captured.push({ body: JSON.parse(String(init?.body ?? "{}")) });
      callIdx += 1;
      // First call: fresh conversation (id assigned by server).
      // Second call: backend would echo the same id — but we only need to
      // verify the outbound body so a plain SSE reply is fine.
      if (callIdx === 1) {
        return makeSSEWithConversationId("conv-echo", ["ok1"]);
      }
      return makeSSEResponse(["ok2"]);
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { result } = renderHook(() => useStream());

    await act(async () => {
      await result.current.sendMessage("first");
    });

    await waitFor(() => {
      expect(result.current.conversationId).toBe("conv-echo");
    });

    await act(async () => {
      await result.current.sendMessage("second");
    });

    expect(captured).toHaveLength(2);
    // First turn was a fresh conversation — outbound id is null.
    expect(captured[0].body.conversation_id).toBeNull();
    // Second turn carries the server-assigned id automatically, without
    // the caller having to plumb it back in.
    expect(captured[1].body.conversation_id).toBe("conv-echo");
  });

  it("onConversationId is NOT re-fired on subsequent events carrying the same id", async () => {
    // A subsequent turn's SSE stream will likely include the same id again
    // (backend may echo it). The hook must only notify once per change.
    const onConv = vi.fn();
    const fetchSpy = vi.fn(async () =>
      makeSSEWithConversationId("conv-stable", ["x"]),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const { result } = renderHook(() =>
      useStream({
        conversationId: "conv-stable",
        onConversationId: onConv,
      }),
    );

    await act(async () => {
      await result.current.sendMessage("yo");
    });

    await waitFor(() => expect(result.current.isStreaming).toBe(false));

    // The id was already set on mount — the event carrying the same id
    // must not refire the callback.
    expect(onConv).not.toHaveBeenCalled();
  });

  it("setConversationId imperatively seeds the id for the next send", async () => {
    const captured: ConvCapture[] = [];
    const fetchSpy = vi.fn(async (_url: string, init?: RequestInit) => {
      captured.push({ body: JSON.parse(String(init?.body ?? "{}")) });
      return makeSSEResponse(["ok"]);
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { result } = renderHook(() => useStream());

    act(() => {
      result.current.setConversationId("manual-id");
    });

    await act(async () => {
      await result.current.sendMessage("hi");
    });

    expect(captured[0].body.conversation_id).toBe("manual-id");
  });

  it("initialMessages seeds the transcript so history is sent on the very first send", async () => {
    const captured: Array<{
      body: { context: { conversation_history: unknown[] } };
    }> = [];
    const fetchSpy = vi.fn(async (_url: string, init?: RequestInit) => {
      captured.push({ body: JSON.parse(String(init?.body ?? "{}")) });
      return makeSSEResponse(["ok"]);
    });
    vi.stubGlobal("fetch", fetchSpy);

    const seeded: StreamMessage[] = [
      mkMsg("user", "earlier question"),
      mkMsg("assistant", "earlier answer"),
    ];

    const { result } = renderHook(() =>
      useStream({
        initialMessages: seeded,
        conversationId: "hydrated",
      }),
    );

    // The hook should render with the seeded transcript in place.
    expect(result.current.messages.map((m) => m.content)).toEqual([
      "earlier question",
      "earlier answer",
    ]);

    await act(async () => {
      await result.current.sendMessage("follow-up");
    });

    // The very first outbound request must include the hydrated history.
    const history = captured[0].body.context.conversation_history as Array<{
      role: string;
      content: string;
    }>;
    expect(history).toEqual([
      { role: "user", content: "earlier question" },
      { role: "assistant", content: "earlier answer" },
    ]);
  });
});
