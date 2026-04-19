"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import type { StreamMessage } from "@/hooks/use-stream";

// P2-1: IntersectionObserver-based near-bottom detection. "Near" is 80px —
// if the sentinel is within this distance of the viewport bottom the user
// counts as "at bottom" and we auto-scroll on new messages. Anything further
// up is a deliberate scroll-back and we leave the student in peace.
const NEAR_BOTTOM_ROOT_MARGIN = "0px 0px 80px 0px";

export interface UseSmartAutoScrollArgs {
  messages: StreamMessage[];
  isStreaming: boolean;
  containerRef: RefObject<HTMLElement | null>;
  sentinelRef: RefObject<HTMLElement | null>;
}

export interface UseSmartAutoScrollResult {
  /** True when the sentinel is within 80px of the viewport bottom. */
  isAtBottom: boolean;
  /** Smooth-scroll the sentinel into view and force `isAtBottom` back to true. */
  jumpToBottom: () => void;
}

/**
 * Smart auto-scroll for chat transcripts.
 *
 * Behavior (spec: P2-1 in docs/CHAT-FIX-TRACKER.md):
 *  - Tracks `isAtBottom` via IntersectionObserver on a sentinel element at the
 *    end of the message list. "At bottom" = within 80px of viewport bottom.
 *  - Auto-scrolls on new messages ONLY when the user was already at/near the
 *    bottom — never yanks a scrolled-up reader back down.
 *  - Always scrolls when the last message is a FRESH user message (comparing
 *    last-id against a ref). Sending is the user's own intent, so we snap
 *    instantly ("auto") to keep the send feel snappy.
 *  - Initial mount with messages present → jump to bottom (no animation).
 *  - `jumpToBottom()` smooth-scrolls and optimistically flips `isAtBottom=true`
 *    so the "Jump to bottom" pill hides immediately (observer catches up next
 *    tick).
 */
export function useSmartAutoScroll({
  messages,
  isStreaming,
  containerRef,
  sentinelRef,
}: UseSmartAutoScrollArgs): UseSmartAutoScrollResult {
  const [isAtBottom, setIsAtBottom] = useState(true);

  // Track the id of the last message we saw so we can detect the user's own
  // fresh send (role==='user' and id changed) separately from ongoing token
  // streaming of an existing assistant message.
  const lastMessageIdRef = useRef<string | null>(null);
  const hasMountedRef = useRef(false);

  // Wire the IntersectionObserver. Observer + sentinel live on refs so it
  // survives re-renders without being recreated on every message tick.
  useEffect(() => {
    const sentinel = sentinelRef.current;
    const container = containerRef.current;
    if (!sentinel || !container) return;
    // jsdom or very old browsers — bail gracefully and assume at-bottom.
    if (typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry) setIsAtBottom(entry.isIntersecting);
      },
      {
        root: container,
        rootMargin: NEAR_BOTTOM_ROOT_MARGIN,
        threshold: 0,
      },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [containerRef, sentinelRef]);

  // Drive the actual scrolling. Runs on messages change OR streaming toggle.
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const last = messages[messages.length - 1];
    const lastId = last?.id ?? null;
    const prevLastId = lastMessageIdRef.current;
    const idChanged = lastId !== prevLastId;
    lastMessageIdRef.current = lastId;

    // Initial mount: if there are already messages (e.g. loaded from server),
    // jump to bottom with no animation so the user starts at the live edge.
    if (!hasMountedRef.current) {
      hasMountedRef.current = true;
      if (messages.length > 0) {
        sentinel.scrollIntoView({ behavior: "auto", block: "end" });
      }
      return;
    }

    // Fresh user message: always snap to bottom (user's own send intent).
    if (idChanged && last?.role === "user") {
      sentinel.scrollIntoView({ behavior: "auto", block: "end" });
      return;
    }

    // All other changes (assistant tokens, new assistant message): only
    // scroll if we were already at/near the bottom.
    if (isAtBottom) {
      sentinel.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages, isStreaming, isAtBottom, sentinelRef]);

  const jumpToBottom = useCallback(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    sentinel.scrollIntoView({ behavior: "smooth", block: "end" });
    // Optimistically mark at-bottom so the pill hides immediately; the
    // observer will reconcile on the next intersection tick.
    setIsAtBottom(true);
  }, [sentinelRef]);

  return { isAtBottom, jumpToBottom };
}
