import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { createRef } from "react";
import { useSmartAutoScroll } from "./use-smart-auto-scroll";
import type { StreamMessage } from "./use-stream";

// ---------- IntersectionObserver mock ----------

type IOCallback = IntersectionObserverCallback;

class MockIntersectionObserver {
  readonly root: Element | Document | null = null;
  readonly rootMargin: string = "";
  readonly thresholds: ReadonlyArray<number> = [];
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  takeRecords = (): IntersectionObserverEntry[] => [];
  cb: IOCallback;

  constructor(cb: IOCallback) {
    this.cb = cb;
    instances.push(this);
  }

  trigger(isIntersecting: boolean) {
    const entry = { isIntersecting } as IntersectionObserverEntry;
    this.cb([entry], this as unknown as IntersectionObserver);
  }
}

const instances: MockIntersectionObserver[] = [];

beforeEach(() => {
  instances.length = 0;
  (globalThis as unknown as { IntersectionObserver: typeof MockIntersectionObserver }).IntersectionObserver =
    MockIntersectionObserver;
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------- helpers ----------

function mkMsg(
  role: "user" | "assistant",
  content: string,
  id = crypto.randomUUID(),
): StreamMessage {
  return { id, role, content, timestamp: new Date() };
}

/**
 * Build a pair of refs with jsdom elements and a spy on scrollIntoView.
 * scrollIntoView isn't implemented in jsdom, so we mock it on the prototype.
 */
function makeRefsWithScrollSpy() {
  const container = document.createElement("div");
  const sentinel = document.createElement("div");
  container.appendChild(sentinel);
  document.body.appendChild(container);

  const scrollIntoView = vi.fn();
  sentinel.scrollIntoView = scrollIntoView;

  const containerRef = createRef<HTMLElement>();
  const sentinelRef = createRef<HTMLElement>();
  // Assign the refs directly — createRef gives us a mutable `{ current }`.
  (containerRef as { current: HTMLElement | null }).current = container;
  (sentinelRef as { current: HTMLElement | null }).current = sentinel;

  return { containerRef, sentinelRef, scrollIntoView };
}

// ---------- tests ----------

describe("useSmartAutoScroll", () => {
  it("initial mount with messages already present jumps to bottom (auto, not smooth)", () => {
    const { sentinelRef, containerRef, scrollIntoView } = makeRefsWithScrollSpy();
    const messages = [mkMsg("user", "hi"), mkMsg("assistant", "hello there")];

    renderHook(() =>
      useSmartAutoScroll({ messages, isStreaming: false, containerRef, sentinelRef }),
    );

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "auto", block: "end" });
  });

  it("observer reports at-bottom by default (isIntersecting=true)", () => {
    const { sentinelRef, containerRef } = makeRefsWithScrollSpy();

    const { result } = renderHook(() =>
      useSmartAutoScroll({
        messages: [],
        isStreaming: false,
        containerRef,
        sentinelRef,
      }),
    );

    // Before the observer fires, the hook's default optimistic state is true.
    expect(result.current.isAtBottom).toBe(true);

    // Even if the observer fires true, state stays true.
    act(() => instances[0]?.trigger(true));
    expect(result.current.isAtBottom).toBe(true);
  });

  it("scrolls smoothly when a new assistant message arrives and user is at bottom", () => {
    const { sentinelRef, containerRef, scrollIntoView } = makeRefsWithScrollSpy();

    const userMsg = mkMsg("user", "hello");
    const { rerender } = renderHook(
      ({ messages }: { messages: StreamMessage[] }) =>
        useSmartAutoScroll({
          messages,
          isStreaming: false,
          containerRef,
          sentinelRef,
        }),
      { initialProps: { messages: [userMsg] } },
    );

    // Initial mount fired once with behavior: "auto".
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    scrollIntoView.mockClear();

    // Observer confirms at-bottom.
    act(() => instances[0]?.trigger(true));

    // New assistant message appears; should smooth-scroll because we're at bottom.
    const assistantMsg = mkMsg("assistant", "world");
    rerender({ messages: [userMsg, assistantMsg] });

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenLastCalledWith({
      behavior: "smooth",
      block: "end",
    });
  });

  it("does NOT scroll when the user is scrolled up and a new assistant message arrives", () => {
    const { sentinelRef, containerRef, scrollIntoView } = makeRefsWithScrollSpy();

    const userMsg = mkMsg("user", "hello");
    const { rerender, result } = renderHook(
      ({ messages }: { messages: StreamMessage[] }) =>
        useSmartAutoScroll({
          messages,
          isStreaming: true,
          containerRef,
          sentinelRef,
        }),
      { initialProps: { messages: [userMsg] } },
    );

    scrollIntoView.mockClear();

    // Observer says: user scrolled up (not intersecting).
    act(() => instances[0]?.trigger(false));
    expect(result.current.isAtBottom).toBe(false);

    // Assistant token arrives — should NOT scroll.
    const assistantMsg = mkMsg("assistant", "streaming...");
    rerender({ messages: [userMsg, assistantMsg] });

    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("always scrolls (auto, not smooth) when the user sends a fresh message — even if scrolled up", () => {
    const { sentinelRef, containerRef, scrollIntoView } = makeRefsWithScrollSpy();

    const firstUser = mkMsg("user", "first");
    const firstAssistant = mkMsg("assistant", "answer");
    const { rerender } = renderHook(
      ({ messages }: { messages: StreamMessage[] }) =>
        useSmartAutoScroll({
          messages,
          isStreaming: false,
          containerRef,
          sentinelRef,
        }),
      { initialProps: { messages: [firstUser, firstAssistant] } },
    );

    scrollIntoView.mockClear();

    // User scrolls up.
    act(() => instances[0]?.trigger(false));

    // User sends a second message — last id changes, role is 'user' → snap.
    const secondUser = mkMsg("user", "follow-up");
    rerender({ messages: [firstUser, firstAssistant, secondUser] });

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenLastCalledWith({
      behavior: "auto",
      block: "end",
    });
  });

  it("jumpToBottom smooth-scrolls and flips isAtBottom back to true", () => {
    const { sentinelRef, containerRef, scrollIntoView } = makeRefsWithScrollSpy();

    const { result } = renderHook(() =>
      useSmartAutoScroll({
        messages: [mkMsg("user", "hi")],
        isStreaming: true,
        containerRef,
        sentinelRef,
      }),
    );

    // Simulate user scrolled up.
    act(() => instances[0]?.trigger(false));
    expect(result.current.isAtBottom).toBe(false);

    scrollIntoView.mockClear();

    act(() => result.current.jumpToBottom());

    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "end",
    });
    expect(result.current.isAtBottom).toBe(true);
  });

  it("does not scroll on streaming-only ref changes (token updates) when user is scrolled up", () => {
    const { sentinelRef, containerRef, scrollIntoView } = makeRefsWithScrollSpy();

    const userMsg = mkMsg("user", "hello");
    const assistantId = "assistant-1";
    const assistantMsg: StreamMessage = {
      id: assistantId,
      role: "assistant",
      content: "he",
      timestamp: new Date(),
    };
    const { rerender } = renderHook(
      ({ messages }: { messages: StreamMessage[] }) =>
        useSmartAutoScroll({
          messages,
          isStreaming: true,
          containerRef,
          sentinelRef,
        }),
      { initialProps: { messages: [userMsg, assistantMsg] } },
    );

    scrollIntoView.mockClear();
    act(() => instances[0]?.trigger(false));

    // Token accumulation — same assistant id, content grows.
    rerender({
      messages: [
        userMsg,
        { ...assistantMsg, content: "hello" },
      ],
    });
    rerender({
      messages: [
        userMsg,
        { ...assistantMsg, content: "hello world" },
      ],
    });

    expect(scrollIntoView).not.toHaveBeenCalled();
  });
});
