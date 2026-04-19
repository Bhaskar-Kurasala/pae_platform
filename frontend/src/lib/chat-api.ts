/**
 * P0-3 — typed wrappers for the `/api/v1/chat/*` endpoints backing the
 * sidebar. Kept in its own module rather than touching the auto-generated
 * `api-client.ts` so the next OpenAPI regen doesn't clobber these. Shapes
 * mirror `backend/app/schemas/chat.py` (keep in sync).
 */
import { api, API_BASE } from "@/lib/api-client";

export interface ChatFeedbackRead {
  id: string;
  message_id: string;
  rating: "up" | "down";
  reasons: string[] | null;
  comment: string | null;
  created_at: string;
}

export interface ChatFeedbackCreate {
  rating: "up" | "down";
  reasons?: string[];
  comment?: string;
}

// P1-1 — body for `POST /chat/messages/{id}/edit`. Mirrors
// `ChatMessageEditRequest` in backend/app/schemas/chat.py.
export interface ChatMessageEditRequest {
  content: string;
}

// P1-6 — slim projection returned by `POST /chat/attachments`. Mirrors
// `ChatAttachmentRead` in backend/app/schemas/chat.py.
export interface ChatAttachmentRead {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
}

export interface ChatMessageRead {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  agent_name: string | null;
  token_count: number | null;
  parent_id: string | null;
  created_at: string;
  // P1-5 — inlined by the backend on `GET /conversations/{id}` so the UI can
  // hydrate thumb state without an N+1 round trip.
  my_feedback?: ChatFeedbackRead | null;
  // P1-2 — assistant sibling ids for the <1/N> regenerate navigator.
  // Empty (or absent) when the message has no siblings; populated (length
  // >= 2) when the student has regenerated this turn. Includes the current
  // message's own id, ordered by created_at ascending.
  sibling_ids?: string[];
}

export interface ConversationRead {
  id: string;
  user_id: string;
  agent_name: string | null;
  title: string | null;
  archived_at: string | null;
  // P1-8 — nullable pin timestamp; non-null means pinned.
  pinned_at: string | null;
  created_at: string;
  updated_at: string;
  messages: ChatMessageRead[];
}

export interface ConversationListItem {
  id: string;
  title: string | null;
  agent_name: string | null;
  updated_at: string;
  archived_at: string | null;
  // P1-8 — backend floats pinned rows to the top of the list; the UI
  // renders them in a dedicated section above a divider.
  pinned_at: string | null;
  message_count: number;
}

export const chatApi = {
  listConversations: (opts?: { includeArchived?: boolean; q?: string }) => {
    const params = new URLSearchParams();
    if (opts?.includeArchived) params.set("include_archived", "true");
    if (opts?.q) params.set("q", opts.q);
    const qs = params.toString();
    return api.get<ConversationListItem[]>(
      `/api/v1/chat/conversations${qs ? `?${qs}` : ""}`,
    );
  },
  getConversation: (id: string) =>
    api.get<ConversationRead>(`/api/v1/chat/conversations/${id}`),
  renameConversation: (id: string, title: string) =>
    api.patch<ConversationRead>(`/api/v1/chat/conversations/${id}`, { title }),
  archiveConversation: (id: string, archived = true) =>
    api.patch<ConversationRead>(`/api/v1/chat/conversations/${id}`, { archived }),
  // P1-8 — toggle pin. Backend stamps `pinned_at=now()` on true, NULL on false.
  pinConversation: (id: string, pinned = true) =>
    api.patch<ConversationRead>(`/api/v1/chat/conversations/${id}`, { pinned }),
  deleteConversation: (id: string) =>
    api.del(`/api/v1/chat/conversations/${id}`),
  // P1-5 — thumbs up/down + optional reason chips + freeform comment. Upsert
  // semantics: a second POST from the same user on the same message
  // replaces the earlier row.
  postFeedback: (messageId: string, payload: ChatFeedbackCreate) =>
    api.post<ChatFeedbackRead>(
      `/api/v1/chat/messages/${messageId}/feedback`,
      payload,
    ),
  getFeedback: (messageId: string) =>
    api.get<ChatFeedbackRead | null>(
      `/api/v1/chat/messages/${messageId}/feedback`,
    ),
  // P1-1 — rewrite a user turn. Server soft-deletes the target + every
  // downstream message and returns the freshly-inserted user row. Caller is
  // expected to drop trailing messages from local state and re-stream.
  editMessage: (messageId: string, payload: ChatMessageEditRequest) =>
    api.post<ChatMessageRead>(
      `/api/v1/chat/messages/${messageId}/edit`,
      payload,
    ),
  // P1-2 — fetch a single message by id. Used by the sibling navigator to
  // load a specific variant when the student clicks `< / >`.
  getMessage: (messageId: string) =>
    api.get<ChatMessageRead>(`/api/v1/chat/messages/${messageId}`),
};

// ---------- Export (P1-9) ----------

interface StoredAuthForExport {
  state?: { token?: string };
}

function readAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem("auth-storage");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredAuthForExport;
    return parsed.state?.token ?? null;
  } catch {
    return null;
  }
}

// ---------- Regenerate (P1-2) ----------

/**
 * Kick off a regenerate stream for the given assistant message. Returns the
 * raw `fetch` Response so the caller can drain the SSE body with the same
 * parser that `useStream.sendMessage` uses (data: <json>\n\n framing).
 *
 * The backend:
 *   - validates ownership (404 on missing / foreign / soft-deleted)
 *   - rejects non-assistant targets with 400
 *   - creates a brand-new assistant row with the SAME `parent_id` as the
 *     original, keeping the original in the DB so the `< 1 / N >` navigator
 *     can flip between siblings
 *   - emits `regenerated_from: <original_id>` on the first SSE event and an
 *     `X-Regenerated-From` response header
 *
 * Used by the RegenerateButton flow in `app/(portal)/chat/page.tsx`. Errors
 * are surfaced by the caller via the response status — we don't throw here
 * because the caller needs to distinguish 401/404/429/5xx for UX.
 */
export async function regenerateMessage(
  messageId: string,
  signal?: AbortSignal,
): Promise<Response> {
  const token = readAccessToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return fetch(`${API_BASE}/api/v1/chat/messages/${messageId}/regenerate`, {
    method: "POST",
    headers,
    signal,
  });
}

// ---------- Attachments (P1-6) ----------

/**
 * Upload a single file/image to `POST /api/v1/chat/attachments`. Uses a
 * manual `fetch` path rather than `api.post` because that helper assumes JSON
 * request bodies — attachments are `multipart/form-data`.
 *
 * Returns the slim attachment row (id + filename + mime + size). The caller
 * passes `id` to the next `/api/v1/agents/stream` call via `attachment_ids`
 * and the backend binds the row to the persisted user message.
 *
 * Errors are surfaced as thrown `Error`s with the backend's detail string so
 * the composer can show 415/413 messages inline.
 */
export async function uploadAttachment(
  file: File,
): Promise<ChatAttachmentRead> {
  const token = readAccessToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const form = new FormData();
  form.append("file", file, file.name);

  const res = await fetch(`${API_BASE}/api/v1/chat/attachments`, {
    method: "POST",
    headers,
    body: form,
  });
  if (!res.ok) {
    // Surface the backend's detail message so the composer can show
    // "Unsupported attachment type" / "exceeds limit" etc. as-is.
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // no-op — non-JSON error body
    }
    throw new Error(detail);
  }
  return (await res.json()) as ChatAttachmentRead;
}

/**
 * Parse the filename from a `Content-Disposition: attachment; filename="..."`
 * header. Falls back to a sensible default if the server didn't send one.
 */
export function filenameFromDisposition(
  header: string | null,
  fallback = "conversation.md",
): string {
  if (!header) return fallback;
  // Naive but sufficient for our server's single-line `filename="..."` shape.
  const match = /filename="?([^";]+)"?/i.exec(header);
  return match?.[1] ?? fallback;
}

/**
 * Fetches the Markdown export of a conversation and triggers a browser
 * download. Resolves to the downloaded filename (for tests + logging).
 *
 * Keeps a manual `fetch` path rather than going through `api.get` because
 * the API helper assumes JSON response bodies.
 */
export async function exportConversationMarkdown(
  conversationId: string,
): Promise<string> {
  if (!conversationId) {
    throw new Error("exportConversationMarkdown: conversationId is required");
  }
  const token = readAccessToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(
    `${API_BASE}/api/v1/chat/conversations/${conversationId}/export?format=md`,
    { headers },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Export failed: ${res.status} ${res.statusText}${text ? ` — ${text}` : ""}`,
    );
  }
  const blob = await res.blob();
  const filename = filenameFromDisposition(res.headers.get("Content-Disposition"));

  // Trigger the download via a temporary anchor. `document` guard keeps
  // this module importable in SSR / test environments that lack a DOM.
  if (typeof document !== "undefined" && typeof URL !== "undefined") {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }
  return filename;
}
