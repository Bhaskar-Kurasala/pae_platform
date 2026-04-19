"use client";

import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthStore } from "@/stores/auth-store";
import type { ChatFeedbackRead } from "@/lib/chat-api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// P0-1: conversation-history caps. The backend re-slices to the last 6 turns at
// stream.py:251; we send a bit more so it has room to trim, while keeping the
// token budget bounded. Walk backwards from newest; stop when either trips.
const HISTORY_MAX_TURNS = 12;
const HISTORY_MAX_CHARS = 6000;

export interface HistoryTurn {
  role: "user" | "assistant";
  content: string;
}

/**
 * Build the `conversation_history` payload from a snapshot of prior messages.
 * Exported for unit testing; the hook uses it internally.
 *
 * Rules (P0-1):
 *  - Skip placeholder/thinking messages (`isThinking`) and empty-content turns.
 *  - Walk backwards from the newest; stop at 12 turns OR 6000 chars, whichever
 *    hits first. Return in chronological order (oldest → newest).
 *  - Emit only `{ role, content }`.
 *
 * Callers must pass a snapshot that does NOT yet include the current user
 * message — the backend appends it on its own at stream.py:259.
 */
export function buildHistoryPayload(prior: StreamMessage[]): HistoryTurn[] {
  const out: HistoryTurn[] = [];
  let charTotal = 0;
  for (let i = prior.length - 1; i >= 0; i--) {
    const msg = prior[i];
    if (msg.isThinking) continue;
    if (!msg.content) continue;
    if (out.length >= HISTORY_MAX_TURNS) break;
    const nextCharTotal = charTotal + msg.content.length;
    if (nextCharTotal > HISTORY_MAX_CHARS) break;
    out.push({ role: msg.role, content: msg.content });
    charTotal = nextCharTotal;
  }
  return out.reverse();
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("auth-storage");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { state?: { token?: string } };
    return parsed.state?.token ?? null;
  } catch {
    return null;
  }
}

export interface StreamMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  agentName?: string;
  isThinking?: boolean;
  timestamp: Date;
  // P1-5 — the caller's own feedback on an assistant message. Undefined means
  // the message hasn't been rated (or the hook hasn't been hydrated with server
  // state yet). The hook never mutates this — page-level code flips it via
  // `setMessages` after a successful POST to `/messages/{id}/feedback`.
  myFeedback?: ChatFeedbackRead | null;
  // P1-2 — the assistant-sibling id list for the `< 1 / N >` regenerate
  // navigator. Populated server-side on hydration when `parent_id` has
  // more than one assistant child; empty / undefined otherwise. The hook
  // never mutates this — page-level code flips it via `setMessages` after
  // a successful regenerate stream.
  siblingIds?: string[];
}

/**
 * Typed error shape emitted by useStream so the UI can render distinct
 * banners, icons, and retry behavior per failure class (P0-5).
 *
 * - `auth`       → 401 from backend; token expired / missing. UI prompts
 *                  re-login; retry is disabled (the action button clears
 *                  the auth store and navigates to /login instead).
 * - `rate_limit` → 429 from backend; respect `Retry-After` (seconds) when
 *                  present, fallback to 30s. UI disables retry until the
 *                  countdown elapses and shows seconds remaining.
 * - `server`     → 5xx from backend, or an `error` field in a data event
 *                  mid-stream. `message` carries the server's `detail`
 *                  when available; retry is live.
 * - `network`    → fetch rejected, no response arrived, or the reader
 *                  failed mid-stream with no server-sent error. Retry is
 *                  live.
 */
export interface StreamError {
  kind: "auth" | "rate_limit" | "server" | "network";
  message: string;
  retryAfterMs?: number;
}

interface UseStreamOptions {
  agentName?: string;
  initialContext?: Record<string, unknown>;
  /**
   * Called on every sendMessage; lets callers attach up-to-date data
   * (e.g. the Studio's current code). Merged over initialContext.
   */
  contextProvider?: () => Record<string, unknown> | undefined;
  /**
   * P0-3: pre-populate the message list when opening an existing
   * persisted conversation. Callers pass the hydrated `StreamMessage[]`
   * derived from `GET /chat/conversations/{id}`. Used once on mount —
   * changes after mount are ignored by design; switch conversations via
   * component remount (key=) or via `setMessages` semantics on a future
   * iteration. Empty array == fresh conversation.
   */
  initialMessages?: StreamMessage[];
  /**
   * P0-3: when opening an existing persisted conversation, pre-seed the
   * server-side id so subsequent `sendMessage` calls pass it in the
   * request body and the backend appends rather than creates.
   */
  conversationId?: string;
  /**
   * P0-3: fired once, when the FIRST SSE event on a brand-new
   * conversation carries back the server-assigned `conversation_id`.
   * Consumers use it to (a) update the sidebar list optimistically and
   * (b) push `/chat?c={id}` onto the URL.
   */
  onConversationId?: (id: string) => void;
}

interface UseStreamReturn {
  messages: StreamMessage[];
  isStreaming: boolean;
  error: StreamError | null;
  /**
   * Send a new user turn. `attachmentIds` (P1-6) are pre-uploaded attachment
   * rows returned by `POST /api/v1/chat/attachments`; the backend binds each
   * to the persisted user message and injects their bytes into the Claude
   * content blocks.
   */
  sendMessage: (text: string, attachmentIds?: string[]) => Promise<void>;
  retry: () => Promise<void>;
  clearMessages: () => void;
  /**
   * P0-4: Stop an in-flight stream. Aborts the underlying fetch, flushes
   * any pending rAF-buffered tokens so partial content is preserved, and
   * stamps a subtle `_[stopped]_` markdown marker onto the assistant
   * message so the student knows the reply was cut short. Does NOT set
   * `error` — cancellation is intentional. No-op when not streaming.
   */
  cancel: () => void;
  /**
   * P0-3: current server-side conversation id. `null` before the first
   * turn on a fresh conversation (backend auto-creates on first send).
   */
  conversationId: string | null;
  /**
   * P0-3: imperative setter — lets the page seed the id when opening an
   * existing conversation without going through a remount. Using the
   * `initialMessages` + `conversationId` option is preferred; this is the
   * escape hatch for edge cases.
   */
  setConversationId: (id: string | null) => void;
  /**
   * P1-5: imperative messages setter — lets the page apply optimistic
   * updates (e.g. flipping `myFeedback` after POST `/messages/{id}/feedback`)
   * without copying the entire message-array state out of the hook. Same
   * signature as React's `setState` so callers can pass either a value or
   * an updater function.
   */
  setMessages: React.Dispatch<React.SetStateAction<StreamMessage[]>>;
}

// P0-5 — parse Retry-After per RFC 7231 §7.1.3. slowapi doesn't currently set
// this header on our 429 response, but we still honor it when any proxy or
// future version emits it. Accepts delta-seconds or an HTTP-date; falls back
// to 30s when absent or malformed.
function parseRetryAfter(header: string | null): number {
  if (!header) return 30_000;
  const asInt = Number.parseInt(header, 10);
  if (Number.isFinite(asInt) && asInt >= 0) return asInt * 1000;
  const asDate = Date.parse(header);
  if (Number.isFinite(asDate)) {
    const delta = asDate - Date.now();
    return delta > 0 ? delta : 30_000;
  }
  return 30_000;
}

// P2-2 — requestAnimationFrame may be undefined during SSR or in some test
// environments. Guard defensively so the hook can be imported server-side
// (though it's marked "use client") and falls back to a microtask flush when
// rAF is missing (e.g. jsdom without a polyfill).
const scheduleFrame: (cb: FrameRequestCallback) => number =
  typeof window !== "undefined" && typeof window.requestAnimationFrame === "function"
    ? window.requestAnimationFrame.bind(window)
    : (cb: FrameRequestCallback) => {
        // Fallback: run on next microtask. Return a non-zero handle so the
        // "scheduled?" check reads consistently; cancelFrame below is a no-op
        // in this path and flush() is idempotent on an empty buffer anyway.
        queueMicrotask(() => cb(performance.now()));
        return 1;
      };
const cancelFrame: (handle: number) => void =
  typeof window !== "undefined" && typeof window.cancelAnimationFrame === "function"
    ? window.cancelAnimationFrame.bind(window)
    : () => {};

export function useStream(options: UseStreamOptions = {}): UseStreamReturn {
  const {
    agentName,
    initialContext,
    contextProvider,
    initialMessages,
    conversationId: initialConversationId,
    onConversationId,
  } = options;
  const contextProviderRef = useRef(contextProvider);
  contextProviderRef.current = contextProvider;
  // P0-3: `initialMessages` is intentionally read once on mount — re-hydrating
  // mid-stream would clobber in-flight state. Switch conversations by
  // remounting via a `key=` prop at the caller.
  const [messages, setMessages] = useState<StreamMessage[]>(initialMessages ?? []);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<StreamError | null>(null);
  // P0-3: conversationId lives in state so callers re-render on change, but
  // sendMessage needs a synchronous read — mirror into a ref the same way
  // messagesRef does for history.
  const [conversationId, setConversationIdState] = useState<string | null>(
    initialConversationId ?? null,
  );
  const conversationIdRef = useRef<string | null>(initialConversationId ?? null);
  useEffect(() => {
    conversationIdRef.current = conversationId;
  }, [conversationId]);
  const onConversationIdRef = useRef(onConversationId);
  onConversationIdRef.current = onConversationId;
  const setConversationId = useCallback((id: string | null) => {
    conversationIdRef.current = id;
    setConversationIdState(id);
  }, []);
  const abortControllerRef = useRef<AbortController | null>(null);
  const lastUserMessageRef = useRef<string | null>(null);
  // P2-2 — token batching state. Chunks accumulate in `bufferRef` and are
  // flushed at most once per animation frame via `rafIdRef`. A 2k-token reply
  // drops from ~2k setMessages calls to ~N frames where N ≈ stream-duration * 60.
  const bufferRef = useRef<string>("");
  const rafIdRef = useRef<number | null>(null);
  // P0-4 — id of the assistant bubble for the in-flight stream, so `cancel()`
  // can stamp the `_[stopped]_` marker on the right message. Set by
  // `sendMessage` on every new stream; cleared in its `finally:` block.
  const currentAssistantIdRef = useRef<string | null>(null);
  // P0-4 — ref-scoped flush so `cancel()` (defined at hook level) can drain
  // any rAF-buffered tokens that were in flight at cancel time. The
  // underlying flush closure lives inside `sendMessage` where it has the
  // assistantId in scope; we publish it here on every stream start so
  // `cancel` doesn't need to reach into `sendMessage`'s closure.
  const flushNowRef = useRef<() => void>(() => {});
  // P0-1: synchronous snapshot of prior messages for request-body construction.
  // `setMessages` is async, so we cannot read the latest state directly inside
  // `sendMessage`; this ref is updated on every render to mirror `messages`.
  const messagesRef = useRef<StreamMessage[]>(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // P2-2 — cancel any pending animation frame on unmount so we don't call
  // setState after the component is gone.
  useEffect(() => {
    return () => {
      if (rafIdRef.current != null) {
        cancelFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
    };
  }, []);

  const sendMessage = useCallback(
    async (text: string, attachmentIds?: string[]): Promise<void> => {
      if (isStreaming) return;

      const token = getToken();
      setError(null);

      // P0-1: snapshot prior messages BEFORE we append the new user bubble, so
      // the payload's `conversation_history` excludes the message the backend
      // is about to append itself (stream.py:259) and any in-flight placeholder.
      const historyPayload = buildHistoryPayload(messagesRef.current);

      // Add user message immediately
      const userMessage: StreamMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: text,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMessage]);
      lastUserMessageRef.current = text;

      // Placeholder assistant message — shown as typing indicator until first token
      const assistantId = crypto.randomUUID();
      // P0-4: remember the in-flight assistant id so `cancel()` can stamp the
      // `_[stopped]_` marker on the right bubble even though it lives outside
      // this closure.
      currentAssistantIdRef.current = assistantId;
      const assistantMessage: StreamMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        agentName: agentName,
        isThinking: true,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
      setIsStreaming(true);

      abortControllerRef.current = new AbortController();

      // P0-5 — track whether fetch() actually resolved (i.e., any response
      // headers arrived) and whether the SSE stream itself surfaced an
      // in-band `error` event. Together these let the catch block
      // classify the failure correctly.
      let responseReceived = false;
      let serverErrorFromStream: string | null = null;

      // P2-2 — reset batching state for this request and define the flush
      // closures. `detectedAgentNameRef` lets flush() pick up the agent name
      // even if the last chunk arrived before the agent_name event; it is
      // updated alongside `detectedAgentName` in the SSE loop below.
      bufferRef.current = "";
      if (rafIdRef.current != null) {
        cancelFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      const detectedAgentNameRef = { current: agentName as string | undefined };

      const flush = (): void => {
        rafIdRef.current = null;
        const chunk = bufferRef.current;
        if (!chunk) return;
        bufferRef.current = "";
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantId
              ? {
                  ...msg,
                  content: msg.content + chunk,
                  agentName: detectedAgentNameRef.current,
                  isThinking: false,
                }
              : msg,
          ),
        );
      };

      const flushNow = (): void => {
        // Synchronous flush used on stream completion, error, or abort so no
        // buffered tokens are dropped from the final rendered content.
        if (rafIdRef.current != null) {
          cancelFrame(rafIdRef.current);
          rafIdRef.current = null;
        }
        flush();
      };
      // P0-4: publish the closure-scoped flushNow so `cancel()` (defined
      // at hook scope, outside this closure) can drain the rAF buffer for
      // the current stream. Reset to a no-op in the finally: block.
      flushNowRef.current = flushNow;

      try {
        const res = await fetch(`${API_BASE}/api/v1/agents/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            message: text,
            agent_name: agentName ?? null,
            // P0-3: pass the server-side conversation id once we know it so
            // the backend appends to the existing row instead of creating a
            // new one. First turn on a fresh conversation sends `null` and
            // the backend auto-creates + returns the id via the first SSE
            // event + X-Conversation-Id header.
            conversation_id: conversationIdRef.current,
            // P1-6 — optional list of pre-uploaded attachment ids. Omitted
            // when empty so the existing JSON shape stays byte-identical for
            // the majority of turns.
            ...(attachmentIds && attachmentIds.length > 0
              ? { attachment_ids: attachmentIds }
              : {}),
            context: {
              ...(initialContext ?? {}),
              ...(contextProviderRef.current?.() ?? {}),
              // P0-1: prior turns only; backend appends the current `message`
              // itself and re-slices to its own cap at stream.py:251.
              conversation_history: historyPayload,
            },
          }),
          signal: abortControllerRef.current.signal,
        });
        responseReceived = true;

        if (!res.ok) {
          // P0-5 — branch on status code so the UI can pick the right
          // copy, icon, and retry behavior. Each branch clears the
          // thinking-placeholder bubble before setting `error`.
          // P2-2 — drain any (unlikely) buffered tokens here too, so the
          // exit-path invariant holds uniformly across all error branches.
          flushNow();
          const body = await res.json().catch(() => null);
          const detail = (body as { detail?: string } | null)?.detail;

          if (res.status === 401) {
            setMessages((prev) => prev.filter((m) => m.id !== assistantId));
            setError({
              kind: "auth",
              message: "Session expired — please sign in again.",
            });
            return;
          }

          if (res.status === 429) {
            const retryAfterMs = parseRetryAfter(res.headers.get("Retry-After"));
            setMessages((prev) => prev.filter((m) => m.id !== assistantId));
            setError({
              kind: "rate_limit",
              message: detail ?? "Too many requests — please slow down.",
              retryAfterMs,
            });
            return;
          }

          if (res.status >= 500 && res.status <= 599) {
            setMessages((prev) => prev.filter((m) => m.id !== assistantId));
            setError({
              kind: "server",
              message: detail
                ? `Server error: ${detail}`
                : "Something went wrong on our side.",
            });
            return;
          }

          // 4xx other than 401/429 — treat as server-side with the detail.
          setMessages((prev) => prev.filter((m) => m.id !== assistantId));
          setError({
            kind: "server",
            message: detail
              ? `Server error: ${detail}`
              : `Request failed (HTTP ${res.status}).`,
          });
          return;
        }

        const reader = res.body?.getReader();
        if (!reader) throw new Error("No response body");

        const decoder = new TextDecoder();
        let buffer = "";
        let detectedAgentName: string | undefined = agentName;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // SSE format: each event is separated by double newline
          // Lines are "data: <json>\n"
          const lines = buffer.split("\n");
          // Keep the last incomplete line in buffer
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith("data: ")) continue;
            const jsonStr = trimmed.slice(6); // Remove "data: " prefix
            if (jsonStr === "[DONE]") continue;

            try {
              const parsed = JSON.parse(jsonStr) as {
                chunk?: string;
                done?: boolean;
                agent_name?: string;
                conversation_id?: string;
                error?: string;
              };

              // P0-3: capture the server-assigned conversation id from the
              // first SSE event when we didn't have one going in (fresh
              // conversation). We notify the caller via the callback exactly
              // once per stream so the page can update the sidebar + URL.
              if (
                parsed.conversation_id &&
                conversationIdRef.current !== parsed.conversation_id
              ) {
                const newId = parsed.conversation_id;
                conversationIdRef.current = newId;
                setConversationIdState(newId);
                onConversationIdRef.current?.(newId);
              }

              if (parsed.error) {
                // P0-5 — in-band stream error. Remember it so the catch
                // block classifies the failure as `server` rather than
                // `network` (the connection was fine; the model wasn't).
                serverErrorFromStream = parsed.error;
                throw new Error(parsed.error);
              }

              if (parsed.agent_name) {
                detectedAgentName = parsed.agent_name;
                detectedAgentNameRef.current = parsed.agent_name;
              }

              if (parsed.chunk !== undefined && parsed.chunk !== "") {
                // P2-2 — buffer the token and schedule a single flush per
                // animation frame. The flush closure reads the latest
                // detectedAgentName via ref and clears isThinking on its
                // first setMessages call, preserving the pre-batching
                // contract that the thinking indicator disappears on the
                // first token.
                bufferRef.current += parsed.chunk;
                if (rafIdRef.current == null) {
                  rafIdRef.current = scheduleFrame(flush);
                }
              } else if (parsed.agent_name) {
                // Agent name arrived before first token — update without clearing thinking
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantId ? { ...msg, agentName: detectedAgentName } : msg,
                  ),
                );
              }

              if (parsed.done === true) {
                // P2-2 — final synchronous flush so no buffered tokens are
                // lost; then apply any final agent-name update on top of the
                // flushed content.
                flushNow();
                if (parsed.agent_name) {
                  setMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === assistantId
                        ? { ...msg, agentName: parsed.agent_name }
                        : msg,
                    ),
                  );
                }
                break;
              }
            } catch (parseErr) {
              // P0-5 — a server-sent in-band error must propagate so the
              // outer catch can classify it; everything else is best-effort
              // SSE parsing and is safe to skip.
              if (serverErrorFromStream) throw parseErr;
              if (parseErr instanceof Error && parseErr.message !== "Malformed JSON") {
                continue;
              }
            }
          }
        }
      } catch (err) {
        // P2-2 — flush any buffered tokens before we mutate error/message
        // state so partial content is never lost (even though the current
        // DISC-44 behavior removes the placeholder bubble, this keeps the
        // invariant that the buffer is drained on every exit path and
        // survives future UX changes).
        flushNow();

        if (err instanceof Error && err.name === "AbortError") {
          // User cancelled — that's fine.
          return;
        }

        const rawMessage =
          err instanceof Error ? err.message : "Failed to reach the AI agents.";

        // P0-5 — classify the caught error:
        //   • in-band `error` data event mid-stream → `server`
        //   • response arrived then reader failed → `network`
        //     (the connection dropped mid-stream with no server-sent error)
        //   • fetch rejected with no response → `network`
        let nextError: StreamError;
        if (serverErrorFromStream) {
          nextError = {
            kind: "server",
            message: `Server error: ${serverErrorFromStream}`,
          };
        } else if (responseReceived) {
          nextError = { kind: "network", message: rawMessage };
        } else {
          nextError = { kind: "network", message: rawMessage };
        }
        setError(nextError);

        // DISC-44 — drop the developer-string placeholder so the UI shows a
        // user-friendly banner sourced from `error` instead of an empty
        // assistant bubble.
        setMessages((prev) => prev.filter((msg) => msg.id !== assistantId));
      } finally {
        // P2-2 — belt-and-suspenders: ensure no scheduled frame outlives the
        // request (would mutate state after unmount or after a new stream).
        if (rafIdRef.current != null) {
          cancelFrame(rafIdRef.current);
          rafIdRef.current = null;
        }
        bufferRef.current = "";
        setIsStreaming(false);
        abortControllerRef.current = null;
        // P0-4: release cancel-related refs so a late `cancel()` call (e.g.
        // a click that lands just after natural completion) is a no-op
        // instead of stamping `_[stopped]_` onto a finished message.
        currentAssistantIdRef.current = null;
        flushNowRef.current = () => {};
      }
    },
    [isStreaming, agentName, initialContext],
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
    lastUserMessageRef.current = null;
  }, []);

  // P0-4 — Stop an in-flight stream. Ordering matters:
  //   1) flush any rAF-buffered tokens first so the partial content visible
  //      to the user is preserved (otherwise the `_[stopped]_` stamp would
  //      append to stale content),
  //   2) abort the fetch so the backend reader exits and its `finally:`
  //      block persists the partial assistant message (P0-2),
  //   3) stamp `_[stopped]_` on the assistant bubble so the student sees
  //      the reply was cut short,
  //   4) flip isStreaming off.
  // The existing AbortError catch in `sendMessage` is a no-op; this path
  // is the sole source of the `[stopped]` stamp so we never double-stamp.
  // Cancellation is user-intent — not an error state — so `error` is NOT
  // set here. No-op when not streaming so a stray Esc press or a late
  // button click never mutates a finished message.
  const cancel = useCallback((): void => {
    if (!isStreaming) return;
    flushNowRef.current();
    abortControllerRef.current?.abort();
    const assistantId = currentAssistantIdRef.current;
    if (assistantId) {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantId
            ? {
                ...msg,
                content: msg.content + "\n\n_[stopped]_",
                isThinking: false,
              }
            : msg,
        ),
      );
    }
    setIsStreaming(false);
  }, [isStreaming]);

  const retry = useCallback(async (): Promise<void> => {
    const last = lastUserMessageRef.current;
    if (!last || isStreaming) return;
    // P0-5 — auth errors are not retriable: the UI action clears the auth
    // store and routes the user to /login. Guard here so any programmatic
    // caller can't loop on a dead token.
    if (error?.kind === "auth") return;
    // Strip the previously-sent user message so sendMessage doesn't duplicate
    // it — the user's intent is to re-send the same prompt, not double it.
    setMessages((prev) => {
      // Remove the last user message (the one we're about to re-send).
      let removed = false;
      const copy = [...prev].reverse();
      const filtered = copy.filter((m) => {
        if (!removed && m.role === "user" && m.content === last) {
          removed = true;
          return false;
        }
        return true;
      });
      return filtered.reverse();
    });
    await sendMessage(last);
  }, [isStreaming, sendMessage, error]);

  return {
    messages,
    isStreaming,
    error,
    sendMessage,
    retry,
    clearMessages,
    cancel,
    conversationId,
    setConversationId,
    setMessages,
  };
}

/**
 * P0-5 — helper for page-level auth-banner action buttons. Clears the auth
 * store so the portal's guard / middleware can redirect to /login. Exposed
 * from the hook module so consumers don't have to import the zustand store
 * directly just to reset auth after a 401.
 */
export function clearAuthForReauth(): void {
  useAuthStore.getState().clearAuth();
}
