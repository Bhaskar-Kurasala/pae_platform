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

// P1-7 — context picker types. Mirror the schemas in
// backend/app/schemas/context.py.
export interface ContextSuggestionSubmission {
  id: string;
  exercise_title: string;
  submitted_at: string;
}

export interface ContextSuggestionLesson {
  id: string;
  title: string;
}

export interface ContextSuggestionExercise {
  id: string;
  title: string;
}

export interface ContextSuggestionsResponse {
  submissions: ContextSuggestionSubmission[];
  lessons: ContextSuggestionLesson[];
  exercises: ContextSuggestionExercise[];
}

export interface ChatContextRef {
  kind: "submission" | "lesson" | "exercise";
  id: string;
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
  // P2-5 — hover-panel metadata. All nullable: historical rows + stream
  // error paths render as "—" in the popover.
  first_token_ms?: number | null;
  total_duration_ms?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  model?: string | null;
  // P1-5 — inlined by the backend on `GET /conversations/{id}` so the UI can
  // hydrate thumb state without an N+1 round trip.
  my_feedback?: ChatFeedbackRead | null;
  // P1-2 / P1-3 — sibling ids for the <1/N> navigator.
  //  · Assistant rows: regenerated variants of a reply.
  //  · User rows: branches created by editing the turn (P1-3); the original
  //    user row + each subsequent edit are siblings of each other.
  // Empty (or absent) when the message has no siblings; populated (length
  // >= 2) when the row belongs to a chain. Includes the current message's
  // own id, ordered by created_at ascending.
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

// P3-3 — quiz question shape returned by POST /chat/quiz.
export type QuizQuestion = {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
  selected_index?: number;
  // Neuroscience-informed fields (optional — backend may not return these yet)
  bloom_level?: string;        // "recall" | "comprehension" | "application" | "analysis"
  question_type?: string;      // "foundation" | "application" | "analysis" | "misconception_trap"
  concept?: string;            // atomic concept this question tests
  distractor_rationales?: string[]; // 3 items, one per wrong option
  misconception_tag?: string | null;
};

export interface QuizGenerateResponse {
  questions: QuizQuestion[];
  concepts_covered?: string[];
}

// P3-4 — notebook entry shape returned by the backend.
export type NotebookGraduatedFilter = "all" | "graduated" | "in_review";
export type NotebookSourceFilter = string | null;

export interface NotebookSourceCount {
  source: string;
  count: number;
}

export interface NotebookSummaryResponse {
  total: number;
  graduated: number;
  in_review: number;
  graduation_percentage: number;
  latest_graduated_at: string | null;
  by_source: NotebookSourceCount[];
  tags: string[];
}

export type WelcomePromptKind = "tutor" | "code" | "quiz" | "career" | "auto";
export type ChatMode = "auto" | "tutor" | "code" | "career" | "quiz";

export interface WelcomePromptItem {
  text: string;
  icon: string;
  kind: WelcomePromptKind;
  rationale: string;
}

export interface WelcomePromptsResponse {
  mode: ChatMode;
  prompts: WelcomePromptItem[];
}

export interface NotebookEntryOut {
  id: string;
  message_id: string;
  conversation_id: string;
  content: string;
  title: string | null;
  user_note: string | null;
  source_type: string | null;
  topic: string | null;
  tags: string[];
  last_reviewed_at: string | null;
  graduated_at: string | null;
  created_at: string;
}

// P-Today2 — `POST /chat/notebook/summarize` shape.
export interface NoteSummarizeResponse {
  summary: string;
  suggested_tags: string[];
  cached: boolean;
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
  // P1-1 / P1-3 — rewrite a user turn. Server forks a new user row (the
  // original is preserved for the branch navigator) and soft-deletes every
  // message strictly downstream. Response is the freshly-inserted row with
  // `sibling_ids` populated with the full edit chain. Caller is expected to
  // drop trailing messages from local state and re-stream.
  editMessage: (messageId: string, payload: ChatMessageEditRequest) =>
    api.post<ChatMessageRead>(
      `/api/v1/chat/messages/${messageId}/edit`,
      payload,
    ),
  // P1-2 — fetch a single message by id. Used by the sibling navigator to
  // load a specific variant when the student clicks `< / >`.
  getMessage: (messageId: string) =>
    api.get<ChatMessageRead>(`/api/v1/chat/messages/${messageId}`),
  // P1-7 — payload for the one-click context picker. Returns the caller's
  // recent submissions, their current lesson (heuristic), and any exercises
  // attached to that lesson. `lessonId` is an explicit override so the
  // Studio / lesson pages can scope the picker to what the user is looking
  // at; omit for the default heuristic.
  getContextSuggestions: (lessonId?: string) => {
    const qs = lessonId
      ? `?lesson_id=${encodeURIComponent(lessonId)}`
      : "";
    return api.get<ContextSuggestionsResponse>(
      `/api/v1/chat/context-suggestions${qs}`,
    );
  },
  // P3-4 — notebook: save / list / patch / delete / mark-reviewed bookmarked messages.
  // P-Today2 — accepts an optional `userNote` (the rewritten note from
  // SaveNoteModal) and `tags`. The raw assistant `content` is still saved
  // alongside the rewrite so the detail drawer can show "Original".
  saveToNotebook: (entry: {
    messageId: string;
    conversationId: string;
    content: string;
    title?: string;
    sourceType?: string;
    topic?: string;
    userNote?: string;
    tags?: string[];
  }) =>
    api.post<NotebookEntryOut>("/api/v1/chat/notebook", {
      message_id: entry.messageId,
      conversation_id: entry.conversationId,
      content: entry.content,
      title: entry.title ?? null,
      source_type: entry.sourceType ?? "chat",
      topic: entry.topic ?? null,
      user_note: entry.userNote ?? null,
      tags: entry.tags ?? [],
    }),
  // P-Today2 — LLM summarization for the SaveNoteModal preview. Backend caches
  // by (message_id, content_len) for 1h, so re-opening the modal on the same
  // bubble is effectively free. Degrades to a head-of-text fallback on LLM
  // failure — never throws so the modal can always render *something*.
  summarizeForNotebook: (params: {
    messageId: string;
    content: string;
    userQuestion?: string;
  }) =>
    api.post<NoteSummarizeResponse>("/api/v1/chat/notebook/summarize", {
      message_id: params.messageId,
      content: params.content,
      user_question: params.userQuestion ?? null,
    }),
  listNotebook: (opts?: {
    source?: string;
    graduated?: NotebookGraduatedFilter;
    tag?: string;
    limit?: number;
  }) => {
    const params = new URLSearchParams();
    if (opts?.source) params.set("source", opts.source);
    if (opts?.graduated) params.set("graduated", opts.graduated);
    if (opts?.tag) params.set("tag", opts.tag);
    if (opts?.limit) params.set("limit", String(opts.limit));
    const qs = params.toString();
    return api.get<NotebookEntryOut[]>(
      `/api/v1/chat/notebook${qs ? `?${qs}` : ""}`,
    );
  },
  notebookSummary: () =>
    api.get<NotebookSummaryResponse>("/api/v1/chat/notebook/summary"),
  welcomePrompts: (mode: ChatMode = "auto") =>
    api.get<WelcomePromptsResponse>(
      `/api/v1/chat/welcome-prompts?mode=${encodeURIComponent(mode)}`,
    ),
  patchNotebookEntry: (
    entryId: string,
    patch: {
      user_note?: string | null;
      title?: string | null;
      topic?: string | null;
      tags?: string[] | null;
    },
  ) => api.patch<NotebookEntryOut>(`/api/v1/chat/notebook/${entryId}`, patch),
  markNotebookReviewed: (entryId: string) =>
    api.post<NotebookEntryOut>(`/api/v1/chat/notebook/${entryId}/review`, {}),
  deleteNotebookEntry: (entryId: string) =>
    api.del(`/api/v1/chat/notebook/${entryId}`),
  // P3-2 — send an assistant message to the spaced_repetition agent and
  // get back a count of extracted Q/A flashcards.
  addFlashcards: (
    messageId: string,
    content: string,
  ): Promise<{ cards_added: number }> =>
    api.post<{ cards_added: number }>("/api/v1/chat/flashcards", {
      message_id: messageId,
      content,
    }),
  // P3-3 — generate 5 MCQ questions based on an assistant message's content.
  // The backend calls the mcq_factory agent scoped to the provided text and
  // returns a structured array ready for the quiz panel to render.
  generateQuiz: (
    messageId: string,
    content: string,
  ): Promise<QuizGenerateResponse> =>
    api.post<QuizGenerateResponse>("/api/v1/chat/quiz", {
      message_id: messageId,
      content,
    }),
  // Serve a pre-generated quiz from Redis cache (rotates v1→v2→v3→v1).
  // Returns null on cache miss (404) so the caller falls back to live generation.
  getCachedQuiz: async (messageId: string): Promise<QuizGenerateResponse | null> => {
    try {
      return await api.get<QuizGenerateResponse>(`/api/v1/chat/quiz/${messageId}`);
    } catch {
      return null;
    }
  },
  // Enqueue background pre-generation of 3 quiz versions for a message (fire-and-forget).
  triggerQuizPregenerate: (messageId: string, content: string): void => {
    void api.post(`/api/v1/chat/quiz/${messageId}/pregenerate`, {
      message_id: messageId,
      content,
    }).catch(() => {/* non-critical, swallow silently */});
  },
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
export interface RegenerateOptions {
  /**
   * P2-4 — override the agent chosen by the original routing. When set,
   * the backend runs this regenerate under the named agent instead of
   * re-using the original assistant's `agent_name`. Validated server-
   * side; unknown names are ignored (fall back to original behavior).
   */
  agentOverride?: string;
  /**
   * P3-1 — "Explain differently" style hint. When set, the backend
   * appends an [EXPLAIN_STYLE: <value>] hint to the task so the agent
   * reshapes its response accordingly.
   * Valid values: "simpler" | "more_rigorous" | "via_analogy" | "show_code"
   */
  explainStyle?: string;
  signal?: AbortSignal;
}

export async function regenerateMessage(
  messageId: string,
  options: RegenerateOptions | AbortSignal = {},
): Promise<Response> {
  // Back-compat: the original signature was `(id, signal?)`. Preserve
  // that by branching on whether the second arg is an AbortSignal or a
  // structured options object.
  const opts: RegenerateOptions =
    typeof AbortSignal !== "undefined" && options instanceof AbortSignal
      ? { signal: options }
      : (options as RegenerateOptions);
  const token = readAccessToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const init: RequestInit = {
    method: "POST",
    headers,
    signal: opts.signal,
  };
  if (opts.agentOverride || opts.explainStyle) {
    headers["Content-Type"] = "application/json";
    const bodyObj: Record<string, string> = {};
    if (opts.agentOverride) bodyObj.agent_override = opts.agentOverride;
    if (opts.explainStyle) bodyObj.explain_style = opts.explainStyle;
    init.body = JSON.stringify(bodyObj);
  }
  return fetch(
    `${API_BASE}/api/v1/chat/messages/${messageId}/regenerate`,
    init,
  );
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
