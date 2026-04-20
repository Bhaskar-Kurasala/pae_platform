# Chat Functional Improvements — Parallel Agent Work Tracker

> Source of critique: senior-engineer review of `frontend/src/app/(portal)/chat/page.tsx`,
> `frontend/src/hooks/use-stream.ts`, and `backend/app/api/v1/routes/stream.py`
> (2026-04-19). This file is the single shared worklist for multiple agents
> working the chat rewrite in parallel.

## How to use this file (read before claiming a task)

1. **Claim a task** by setting `Status: in-progress`, filling `Owner` with your
   agent id / branch name, and stamping `Claimed: YYYY-MM-DD HH:MM`.
2. **Only one agent per task.** If `Status: in-progress` and `Owner` is not you,
   pick a different task. Don't stomp.
3. **Respect dependencies.** Tasks list `Depends-on:` — do not start a task
   whose deps aren't `done`.
4. When finished, set `Status: done`, stamp `Completed:`, and fill the
   **Implementation note** (2-5 lines: *what you changed, where, and any
   follow-up*). Reference file paths + line numbers where useful.
5. If you hit a blocker, set `Status: blocked`, write the reason in the
   implementation note, and unclaim (`Owner: —`) so another agent can retry.
6. Never delete a row. If scope changes, add a new row and mark the old one
   `Status: superseded` with a pointer.

## Status values

- `todo` — unclaimed, ready to start (deps met).
- `in-progress` — actively being worked.
- `blocked` — needs input; see note.
- `done` — shipped and verified.
- `superseded` — replaced by another task.

## Priority legend

- **P0** — integrity / trust debt. Ship this week. The chat is lying to students until these are done.
- **P1** — 2025 chat baseline. Other chat products have these; students notice the absence.
- **P2** — production polish. Performance, failure modes, mobile.
- **P3** — learning-platform differentiators. Things only *this* product can ship.

---

## P0 — Integrity debt (stop shipping lies)

### P0-1 — Wire conversation history into every request
- **Status:** done
- **Owner:** agent-B (P0-1 history)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** —
- **Problem:** `use-stream.ts:96-103` never sends prior turns; backend at
  `stream.py:360-361` reads them from `context.conversation_history` which is
  always empty. Every turn is amnesiac.
- **Acceptance criteria:**
  - Frontend sends last N turns (cap at ~12 or ~6000 chars, whichever hits first)
    on every `sendMessage`.
  - Verified: multi-turn follow-up where assistant references earlier turn works.
  - Unit test in `use-stream.test.ts` covers history serialization + cap.
- **Implementation note:** Added exported `buildHistoryPayload(prior)` helper +
  `HISTORY_MAX_TURNS=12` / `HISTORY_MAX_CHARS=6000` constants in
  `frontend/src/hooks/use-stream.ts`. Added `messagesRef` synced via `useEffect`
  so `sendMessage` can read the pre-append snapshot synchronously. Payload
  snapshot is built before `setMessages([...prev, userMessage])`, naturally
  excluding the current user turn (backend appends at `stream.py:259`) and any
  `isThinking` placeholder (filtered defensively anyway). History emitted as
  `{role, content}[]` only. New `frontend/src/hooks/use-stream.test.ts` covers
  all 6 acceptance tests (empty first-turn, prior turns on 2nd, 12-turn cap,
  6000-char cap trips at 5 of 6 × 1200-char turns, thinking excluded, current
  user not duplicated) — 10/10 pass. Merged cleanly with agent C's StreamError
  and agent D's rAF batching scaffolding. Manual dev-server test not run
  (local backend not spun up); full suite 98/98 green, tsc clean.

### P0-2 — Persist conversations + messages in Postgres
- **Status:** done
- **Owner:** agent-A (P0-2 persistence)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** P0-1 (shape of history payload informs schema)
- **Problem:** Sidebar UUIDs are fake; nothing is stored server-side.
  Clicking a "Recent" row does nothing. Mobile has zero history.
- **Acceptance criteria:**
  - Alembic migration adds `conversations` (id, user_id, agent_name, title,
    created_at, updated_at, archived_at) + `chat_messages` (id, conversation_id,
    role, content, agent_name, token_count, created_at).
  - New endpoints: `POST /api/v1/chat/conversations`, `GET /conversations`,
    `GET /conversations/{id}/messages`, `PATCH /conversations/{id}` (rename/archive),
    `DELETE /conversations/{id}`.
  - `POST /agents/stream` accepts + returns `conversation_id`; persists user
    message at request time and assistant message on stream completion.
  - Pydantic schemas in `app/schemas/chat.py`.
  - Backend tests cover create / list / fetch / persist-on-stream-complete.
- **Implementation note:** New migration `0028_chat_conversations` (rev
  `0028`, down-rev `0027`) creates `conversations` + `chat_messages` with
  UUID PKs, FK cascades, and a composite `(conversation_id, created_at)`
  index; `chat_messages.parent_id` self-FK is already in place for P1-3
  branching, and `archived_at` ships for P1-8. Models at
  `backend/app/models/{conversation,chat_message}.py` (messages
  relationship uses `passive_deletes=False` so SQLite tests cascade too).
  Schemas in `backend/app/schemas/chat.py` (role=Literal, slim
  `ConversationListItem` w/ message_count). Repository
  `backend/app/repositories/chat_repository.py` owns pure DB access
  (outer-join list query for message_count, cursor pagination on
  `list_messages(before=<uuid>)`, title + content `ILIKE` search).
  Service `backend/app/services/chat_service.py` enforces ownership via
  404 (no ID leakage) and exposes `derive_title` / `estimate_tokens` pure
  helpers plus `ensure_conversation_for_stream` / `record_user_message`
  (back-fills title) / `record_assistant_message`. Routes registered at
  `backend/app/api/v1/routes/chat.py` under `/api/v1/chat` with the full
  CRUD surface. `ChatRequest.conversation_id` tightened to
  `uuid.UUID | None` in `backend/app/schemas/agent.py`; the Redis-based
  orchestrator keeps its string contract via a stringify at the boundary
  in `agents.py`. `backend/app/api/v1/routes/stream.py` now
  resolve-or-creates the conversation, persists the user turn before
  streaming, emits `conversation_id` in the first SSE event + an
  `X-Conversation-Id` response header, and persists the assistant turn
  (including partial content on mid-stream failure) in a `finally:`
  block with `contextlib.suppress(Exception)` so streaming UX never
  breaks on persistence errors. Tests:
  `backend/tests/test_services/test_chat_service.py` (4 pure-helper
  cases) and `backend/tests/test_api/test_chat_conversations.py`
  (auth, CRUD, archive filter, title+content search, rename, ownership
  404, cascade delete, stream creates conversation + appends to existing
  + rejects foreign id, messages pagination). Tests patch
  `AsyncSessionLocal` in both `app.core.database` and the stream module
  so the SSE handler shares the in-memory engine. **Not run locally** —
  `uv` unavailable in this sandbox; verification is code-review-level.
  Follow-ups for Wave 2: P0-3 sidebar consumes `GET /api/v1/chat/
  conversations` + `GET /conversations/{id}/messages`; P1-1/P1-3 have
  `parent_id` ready; P1-8 has `archived_at` + content search ready; P2-5
  can extend with `first_token_ms` / `total_ms` columns without schema
  break (add via new migration).

### P0-3 — Sidebar opens real conversations
- **Status:** done
- **Owner:** agent-E (P0-3 sidebar)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** P0-2
- **Problem:** `chat/page.tsx:572` wires `onSelect={setActiveConvId}` and
  nothing else. The "Recent" list is unopenable theatre.
- **Acceptance criteria:**
  - Clicking a sidebar row loads that conversation's messages via
    `GET /conversations/{id}/messages` and hydrates `useStream`.
  - URL reflects the active conversation (`/chat?c={id}`), back/forward works.
  - Drop localStorage conversation cache in favor of server truth; keep only
    a short "last viewed id" for fast initial render.
- **Implementation note:** New typed client `frontend/src/lib/chat-api.ts`
  wraps `/api/v1/chat/*` (list, get, rename, archive, delete, feedback) —
  kept out of the auto-generated `api-client.ts` so regen doesn't clobber.
  `chat/page.tsx` now loads the sidebar from `chatApi.listConversations()`
  on mount, reads `?c={id}` via `useSearchParams`, and calls
  `chatApi.getConversation(id)` on click; messages hydrate `useStream` via
  the `m.my_feedback ?? undefined` mapping (pre-wires P1-5). URL sync via
  `router.replace('/chat?c=…')` so back/forward works. Local conversation
  cache dropped; sidebar is server truth. Page test file
  `frontend/src/app/(portal)/chat/__tests__/page.test.tsx` (7 tests) covers
  list render, row click loads messages, URL sync, and error fallback —
  all pass. Full frontend suite 147/147 green. Follow-ups: P1-8 adds
  rename/pin/archive/delete to the SidebarRow ⋯ menu (agent-I already
  seeded the Export item).

### P0-4 — Stop button during streaming
- **Status:** done
- **Owner:** agent-F (P0-4 stop)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** —
- **Problem:** `abortControllerRef` exists in `use-stream.ts:87` but no UI
  surface calls `.abort()`. Students cannot interrupt a runaway reply.
- **Acceptance criteria:**
  - Send button in `InputBar` swaps to a Stop button while `isStreaming`.
  - Click calls an exported `cancel()` from `useStream` that calls
    `abortControllerRef.current?.abort()`.
  - Cancelled assistant message is kept (with partial content + "[stopped]"
    marker) and still persisted via P0-2.
  - `Esc` keyboard shortcut also cancels.
- **Implementation note:** Exported `cancel` from `useStream`
  (`frontend/src/hooks/use-stream.ts`). Added `currentAssistantIdRef` +
  `flushNowRef` at hook scope so the closure-local `flushNow` inside
  `sendMessage` can be reached by `cancel`; both are cleared in the
  `finally:` block so a late cancel is a no-op. Ordering in cancel:
  flushNow → abort → stamp `\n\n_[stopped]_` → `setIsStreaming(false)`.
  Does NOT set `error` (cancellation is intentional). The existing
  `AbortError` catch stays a no-op so we never double-stamp. `InputBar`
  (`chat/page.tsx`) now takes a new `onCancel` prop; while streaming the
  send button becomes a filled-square Stop button (`lucide-react`
  `Square` with `fill="currentColor"`) with destructive tint, same
  size/shape, and its click handler flips between `onSend` / `onCancel`.
  `ChatArea` threads `cancel` from `useStream` and attaches a `window`
  `keydown` listener that calls `cancel` on `Escape` — active only while
  streaming so it doesn't steal Esc behavior elsewhere. 5 new hook
  tests in `use-stream.test.ts` under `describe("useStream — P0-4
  cancel")` using a paused SSE harness: abort + `isStreaming=false`;
  `_[stopped]_` marker; rAF flush preserves last buffered chunks;
  `error` stays null; non-streaming no-op. 125/125 frontend tests pass;
  lint clean on touched files; `pnpm build` succeeds. Backend
  persistence relies on P0-2's `finally:` block in `stream.py` —
  aborting the fetch is enough; no server-side cancel endpoint needed.

### P0-5 — Distinct error states for 401 / 429 / 5xx
- **Status:** done
- **Owner:** agent-C (P0-5 errors)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** —
- **Problem:** `use-stream.ts:199-211` collapses every failure into
  "Connection lost — Retry". 401 expired token, 429 rate limit, and 500
  server error all show the same banner.
- **Acceptance criteria:**
  - 401 → inline banner "Session expired" + link to re-login; clear auth store.
  - 429 → banner reads server's `Retry-After` header; Retry button disabled
    until countdown elapses.
  - 5xx → banner shows `detail` if present; Retry is live.
  - Network failure (no response) → existing "Connection lost" copy.
- **Implementation note:** Introduced `StreamError = { kind: 'auth' | 'rate_limit' | 'server' | 'network'; message; retryAfterMs? }` in `frontend/src/hooks/use-stream.ts`; `error` changed from `string | null` to `StreamError | null`. Status-code branching in the non-OK path (401 → auth, 429 → rate_limit with parsed `Retry-After`, 5xx → server, fetch reject / mid-stream drop → network, in-band `error` event → server). `retry()` is a no-op when `error.kind === 'auth'`. New `clearAuthForReauth()` helper wraps `useAuthStore.clearAuth()`. New `ErrorBanner` in `frontend/src/app/(portal)/chat/page.tsx` picks copy/icon (Lock / Timer / AlertTriangle) and runs a 1-second countdown off `retryAfterMs` (fallback 30s). 9 new tests in `frontend/src/hooks/use-stream.test.ts` (401, 429 with/without Retry-After, 500 with/without detail, fetch reject, in-band error, mid-stream drop, retry no-op on auth, clearAuthForReauth). All 21 hook tests / 109 frontend tests pass. Lint: touched files clean; 2 pre-existing errors on `chat/page.tsx:485,597` remain and are unrelated. Follow-up: slowapi's 429 handler at `backend/app/main.py:42` does not emit a `Retry-After` header; wiring that is P2-7 scope.

---

## P1 — 2025 chat baseline

### P1-1 — Edit last user message
- **Status:** done
- **Owner:** agent-K (P1-1 edit)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** P0-1, P0-2
- **Problem:** Typos force a full re-type.
- **Acceptance criteria:**
  - Hover action on user bubble: "Edit". Turns bubble into an inline textarea.
  - Save → truncates conversation at that turn, re-sends edited message.
  - Truncation is reflected in persisted history (soft-delete downstream
    messages; don't hard-delete so analytics keeps the record).
- **Implementation note:** Added nullable `deleted_at` on `chat_messages` via
  Alembic `0030_chat_messages_soft_delete.py` + `app/models/chat_message.py:66`;
  repository methods (`list_messages`, `count_messages`, `get_message`,
  `get_feedback_rollup`, new `soft_delete_messages_from`,
  `list_siblings*`, `get_messages_for_regenerate`) in
  `app/repositories/chat_repository.py` now filter `deleted_at IS NULL` by
  default and expose `include_deleted`. New
  `POST /api/v1/chat/messages/{id}/edit` route
  (`app/api/v1/routes/chat.py:206-233`) calls
  `ChatService.edit_user_message` (`app/services/chat_service.py:399-460`),
  which verifies ownership (404), rejects assistant rows (400), soft-deletes
  target + downstream rows, then inserts a fresh user message with
  `parent_id=original.id`. Frontend: new `chatApi.editMessage` +
  `ChatMessageEditRequest` in `frontend/src/lib/chat-api.ts:26-28,111-118`;
  `UserBubble` in `frontend/src/app/(portal)/chat/page.tsx:695-875` grew an
  inline textarea with Save/Cancel (Cmd/Ctrl+Enter to save, Esc to cancel);
  `ChatArea.handleEditUserMessage` truncates local state and calls
  `sendMessage` to re-stream. Tests: 12 new backend tests in
  `backend/tests/test_api/test_chat_edit.py` (auth, soft-delete happy path,
  middle-turn truncation, ownership 404, missing 404, assistant 400, empty
  422, oversized 422, missing field 422, re-edit 404, export filter, admin
  rollup filter) and 5 new frontend tests in
  `frontend/src/app/(portal)/chat/__tests__/edit.test.tsx` (open editor,
  cancel, save → stream, empty-draft disable, non-persisted hide). All
  backend chat suites (45 tests) + frontend suite (182 tests) green.

### P1-2 — Regenerate assistant message
- **Status:** done
- **Owner:** agent-L (P1-2 regenerate)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** P0-1, P0-2
- **Problem:** No way to ask for a different reply without re-typing the prompt.
- **Acceptance criteria:**
  - Hover action on assistant bubble: "Regenerate".
  - Replaces the message in-place (keeps prior versions under the hood for
    "Previous / Next response" nav, ChatGPT-style).
  - Works on any assistant message, not just the last.
- **Implementation note:** Backend: new `POST /api/v1/chat/messages/{id}/regenerate`
  SSE route on a dedicated `chat_stream_router` (registered in `main.py`,
  rate-limited 30/min). Streams via the existing `_token_generator` and
  stamps a `regenerated_from` field on the first SSE event + `X-Regenerated-From`
  response header. Service adds `prepare_regenerate()` (verifies ownership,
  falls back to scanning for the parent on legacy rows) +
  `get_message_for_user()` (ownership-aware single-message fetch). Repository
  adds `list_siblings()`, `list_sibling_map()`, and
  `get_messages_for_regenerate()`, all respecting `deleted_at IS NULL`. New
  assistant rows keep `parent_id` = the user message id, so all variants
  become siblings. Canonical chain builder `_canonical_messages()` positions
  the latest variant immediately after the user parent, fixing the mid-
  conversation reorder bug where a new variant would float past later turns.
  `ChatMessageRead.sibling_ids` inlined only when length > 1; `GET /conversations/{id}`,
  `GET /conversations/{id}/messages`, and new `GET /messages/{id}` all
  populate it from `list_sibling_map()`. Frontend: `chatApi.regenerateMessage`
  returns the raw `fetch` Response for SSE consumption; page-level
  `handleRegenerate` flips the bubble to thinking, streams content in place,
  then re-hydrates sibling ids via `getConversation()`. New `RegenerateButton`
  (hover action, `RotateCw` icon, disabled while streaming) +
  `SiblingNavigator` (`< N / M >` with `ChevronLeft`/`ChevronRight`, shown
  only when `siblingIds.length > 1`). `handleSelectSibling` fetches the
  target variant via `/messages/{id}` and swaps the bubble's id + content
  in place. `persistedIdSet` now seeds from both `initialMessages` ids and
  their `siblingIds`, and is mutated on regenerate/select to include new
  server-minted ids so the bubble's affordances persist after id swaps.
  Tests: backend `tests/test_api/test_chat_regenerate.py` (8 tests covering
  auth, sibling creation, ownership 404, 404 on missing, 400 on user-role
  target, single-message endpoint, mid-conversation regen, empty
  `sibling_ids` on single variant). Frontend
  `chat/__tests__/regenerate.test.tsx` (6 tests: button visibility, streams
  new variant with in-place replacement, navigator appears post-regen,
  prev-arrow swap, no-navigator when single variant, pre-hydrated siblings
  render navigator). All 8 backend + 6 frontend tests green; full frontend
  suite 188/188 green.

### P1-3 — Branch from any turn
- **Status:** done
- **Owner:** agent-P1-3
- **Claimed:** 2026-04-20
- **Completed:** 2026-04-20
- **Depends-on:** P0-2, P1-1
- **Problem:** No way to explore alternative directions without losing the current path.
- **Acceptance criteria:**
  - Schema: `chat_messages.parent_id` enables a tree of turns.
  - Editing a user message forks a new branch instead of overwriting.
  - UI: breadcrumb-style "<1/3>" navigator on branched nodes.
- **Implementation note:** `POST /chat/messages/{id}/edit` now forks via
  `chat.py:415` — keeps original user row, inserts sibling with new content +
  `parent_id` pointing at the original's parent, soft-deletes trailing assistant
  replies. `GET /conversations/{id}` already returns `sibling_ids` for user
  messages via the canonical-chain logic. User `AssistantBubble` sibling
  navigator generalized to `SiblingNavigator` and rendered on `UserBubble`
  too (page.tsx). Backend `test_chat_edit.py` extended with fork + navigate
  round-trip cases; frontend `edit.test.tsx` asserts the `<1/2>` counter.

### P1-4 — Copy message + copy code buttons
- **Status:** done
- **Owner:** agent-G (P1-4 copy)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** —
- **Problem:** No copy on bubble; unclear if MarkdownRenderer has per-codeblock copy.
- **Acceptance criteria:**
  - Hover action on every assistant bubble: copy entire markdown.
  - Every fenced code block in `MarkdownRenderer` has its own copy button with
    "Copied" feedback.
  - Verified against dark + light themes.
- **Implementation note:** Per-code-block copy **already existed** in
  `frontend/src/components/ui/code-block.tsx` (rendered via
  `MarkdownRenderer`'s `code` component). Hardened it with an SSR / unsupported-
  clipboard guard + `console.warn`, tightened the timeout to 1500ms (per AC),
  and added a visually-hidden `role="status" aria-live="polite"` region so
  screen readers announce "Copied" once. New `CopyMessageButton` +
  `group/msg` hover affordance in `AssistantBubble`
  (`frontend/src/app/(portal)/chat/page.tsx`) copies raw markdown via
  `navigator.clipboard.writeText`; hidden while `isStreaming && isLast`,
  while `isThinking`, and when content is empty. Also `focus-within:opacity-100`
  so keyboard users can reach the button. User bubble untouched per spec.
  New test file
  `frontend/src/components/features/__tests__/markdown-renderer.test.tsx`
  (4 tests: button exists, writeText called with raw code, Copied↔Copy toggle +
  aria-live announce, no-op + warn when clipboard undefined). Full suite
  125/125 green, build succeeds, lint clean on all touched files (pre-existing
  errors in `data-table.tsx` / `route-loading-bar.tsx` are unrelated). Landed
  on top of agent-E's in-flight P0-3 rewrite of `chat/page.tsx` without
  conflict — the `AssistantBubble` edit is localized.

### P1-5 — Thumbs up/down + freeform feedback
- **Status:** done
- **Owner:** agent-H (P1-5 feedback)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** P0-2
- **Problem:** No signal loop for answer quality. Cannot improve agents blind.
- **Acceptance criteria:**
  - New table `chat_message_feedback` (message_id, user_id, rating enum,
    comment, reasons[], created_at).
  - Thumbs on every assistant bubble; thumbs-down opens a small reason picker
    (incorrect / unhelpful / unsafe / other + free text).
  - Admin endpoint surfaces weekly rollup per agent.
- **Implementation note:** New model
  `backend/app/models/chat_feedback.py` (ChatMessageFeedback w/ rating
  enum `up|down`, `reasons: JSONB string[]`, `comment: Text`,
  unique `(message_id, user_id)` so a re-submit upserts). Migration
  `backend/alembic/versions/0029_chat_message_feedback.py` (rev 0029,
  down-rev 0028) — applied: `alembic current` = `0029 (head)` in the
  running container. Schemas added to `backend/app/schemas/chat.py`.
  Routes in `backend/app/api/v1/routes/chat.py`:
  `POST /api/v1/chat/messages/{id}/feedback` (upsert),
  `GET /messages/{id}/feedback` (my feedback only),
  and an admin rollup under `/admin`. `GET /conversations/{id}` now
  inlines `my_feedback` on each message so the UI hydrates thumb state
  without N+1. Frontend client `chatApi.postFeedback` / `getFeedback`
  in `chat-api.ts`; `page.tsx:737` calls `postFeedback` on thumb click
  and `page.tsx:88` maps `m.my_feedback` into bubble state. Tests:
  `backend/tests/test_api/test_chat_feedback.py` — 8/8 pass (auth,
  upsert replace, ownership 404, invalid rating 422, cascade on
  conversation delete, inline-on-GET, admin rollup). Thumbs-down
  reason picker: shipped on `AssistantBubble` with the 4-reason set
  (incorrect / unhelpful / unsafe / other) + free-text comment.
  Full frontend suite 147/147 green.

### P1-6 — File / image attachments
- **Status:** done
- **Owner:** agent-M (P1-6 attach)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** P0-2
- **Problem:** Plain textarea. Cannot paste screenshots or upload .py files.
- **Acceptance criteria:**
  - Support image paste (PNG/JPEG) + file upload (.py/.md/.txt/.ipynb).
  - Attachments stored in MinIO/S3 (or local dev equivalent); referenced via
    `chat_attachments` table.
  - Image attachments sent to Claude via vision content blocks; code files
    inlined as fenced blocks with filename header.
  - Drag-and-drop on the composer.
- **Implementation note:** New `chat_attachments` table (migration
  `0032_chat_attachments.py`) with `id/message_id/user_id/filename/
  mime_type/size_bytes/storage_key/created_at` + FK → `chat_messages` and
  `users`. `AttachmentStorage` interface (`backend/app/services/
  attachment_storage.py`) with `LocalFSAttachmentStorage` impl under
  `settings.attachments_dir` (default `backend/var/attachments/`); S3 swap
  later. `AttachmentService` (`backend/app/services/attachment_service.py`)
  owns mime/size gate (415/413/400), write-through, ownership-verified
  pending→bound lifecycle, and Claude content-block assembly (base64 image
  blocks for PNG/JPEG; fenced-code blocks with `### File:` header for
  `.py/.md/.txt/.ipynb`). New `POST /api/v1/chat/attachments` multipart
  route (`backend/app/api/v1/routes/chat_attachments.py`). Extended
  `StreamRequest` (`backend/app/schemas/stream.py`) with
  `attachment_ids: list[UUID] | None` (cap 4 per message, 10 MB per file
  via `settings.attachments_max_bytes` / `attachments_max_per_message`);
  `POST /api/v1/agents/stream` verifies ownership, binds rows to the
  persisted user message id, and passes `list[dict]` content to
  `HumanMessage` when attachments exist (legacy string path unchanged
  when `attachment_ids` is empty). Frontend: `uploadAttachment()` helper
  in `chat-api.ts`; `sendMessage(text, attachmentIds?)` in `use-stream.ts`
  now emits `attachment_ids` in the stream body; `chat/page.tsx` gained
  hidden file input (`accept="image/png,image/jpeg,.py,.md,.txt,.ipynb"`),
  paperclip button (`aria-label="Attach files"`), chips row
  (`data-testid="attachment-chips"`) with per-chip remove ×, paste
  handler on the textarea, and wrapper-level drag-and-drop. Chip row
  clears on successful send; upload errors surface the backend `detail`
  (e.g. "Unsupported attachment type") under the composer. New deps:
  `aiofiles` added to `backend/pyproject.toml`. Backend: 12 new tests in
  `backend/tests/test_api/test_chat_attachments.py` (auth, PNG ok,
  exe→415, 11MB→413, empty→400, octet-stream .ipynb fallback, stream
  binds image block, stream fences text file, foreign-user 404,
  unknown-id 404, >4 attachments→422, plain-text still works) — all
  green; full backend suite regression clean. Frontend: 4 new tests in
  `frontend/src/app/(portal)/chat/__tests__/attachments.test.tsx`
  (picker→chip, send-carries-attachment_ids + clears row, 415 detail
  surfaces under composer, paste handler uploads + renders chip) plus 3
  chat-api tests for `uploadAttachment` (FormData POST, 415 detail
  surfacing, status-text fallback) — all green. Bonus: fixed latent P1-2
  `ReferenceError: conversationId is not defined` in `ChatArea` by
  adding `conversationId` to the `useStream()` destructure.

### P1-7 — One-click context attach (submission / lesson / exercise)
- **Status:** done
- **Owner:** agent-P1-7
- **Claimed:** 2026-04-20
- **Completed:** 2026-04-20
- **Depends-on:** P1-6
- **Problem:** `?submission_id=` prefill at `chat/page.tsx:496-519` is a
  one-shot drive-by. Students can't attach context mid-conversation.
- **Acceptance criteria:**
  - `+` button on the composer opens a picker: recent submissions, current
    lesson, current exercise, pinned code.
  - Selected context becomes a pinned "chip" above the composer for the turn;
    sent as structured context in `ChatRequest`.
  - Multiple chips can coexist.
- **Implementation note:** New `GET /api/v1/chat/context-suggestions` endpoint
  returns last-5 submissions, recent lessons, and exercises. `StreamRequest`
  extended with `context_refs: list[{kind, id}]` (cap 3). `context_attach_service.py`
  resolves each ref to a human-readable block prepended to the `HumanMessage`.
  Frontend: `ContextPickerPopover` at page.tsx:1509 triggered by `+` button;
  chips row shares the attachment chips container; `sendMessage` extended with
  `contextRefs` arg. Backend `test_chat_context.py` (12 tests); frontend
  `context.test.tsx` (5 tests).

### P1-8 — Search, rename, pin, archive, delete conversations
- **Status:** done
- **Owner:** agent-N (P1-8 sidebar mgmt)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** P0-2, P0-3
- **Problem:** 20-conversation localStorage cap, no search, no delete.
- **Acceptance criteria:**
  - Server-side search across titles + message content (Postgres `ILIKE`
    for v1; Meilisearch later).
  - Right-click / "⋯" menu on sidebar row: rename, pin, archive, delete.
  - Pinned section at top; archived hidden but reachable via filter.
- **Implementation note:** New Alembic migration
  `backend/alembic/versions/0031_conversations_pinned_at.py` adds a nullable
  `conversations.pinned_at TIMESTAMPTZ` + `ix_conversations_pinned_at`
  index; applied cleanly in Postgres (head now 0032, chained via
  P1-6 attachments). `ConversationUpdate` gains `pinned: bool | None`;
  `ConversationRead` + `ConversationListItem` expose `pinned_at`. Repo
  `list_conversations_for_user` now orders `pinned_at DESC NULLS LAST,
  updated_at DESC` (single ORDER BY, NULLs naturally trail on Postgres +
  SQLite). `update_conversation` + `ChatService.update()` accept `pinned`
  and stamp `pinned_at=now()` on true / clear on false; route
  `PATCH /chat/conversations/{id}` forwards it. Sidebar UI (`frontend/src/
  app/(portal)/chat/page.tsx`): debounced (300ms) search input with a
  clear (X) button at the top of the aside; "Pinned" section header +
  divider above "Recent" / "Results" when pinned rows exist; pin icon on
  the row title when pinned; expanded ⋯ menu: Rename / Pin-Unpin /
  Archive-Unarchive / Export / Delete (destructive). Inline rename input
  (Enter saves, Esc cancels, blur commits) with aria-label; hand-rolled
  `DeleteConfirmDialog` (no shadcn AlertDialog installed — Escape +
  backdrop click cancel, primary auto-focus). "Show archived" checkbox
  at the bottom toggles `include_archived=true`; archiving the active
  conversation bounces the pane back to empty. Tests: backend
  `backend/tests/test_api/test_chat_sidebar_mgmt.py` (4 tests — pin
  toggle round-trip, pinned-first ordering, pinned+archived composes,
  search+pinned passthrough) all green; frontend
  `frontend/src/app/(portal)/chat/__tests__/page.test.tsx` extended with
  6 P1-8 tests (pinned header render, search debounce+refetch, show-
  archived toggle, inline rename flow, pin sort, delete-confirm round-
  trip, archive hides row) — 14/14 green.

### P1-9 — Export to Markdown
- **Status:** done
- **Owner:** agent-I (P1-9 export)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** P0-2
- **Problem:** Students can't save good answers for study.
- **Acceptance criteria:**
  - `GET /conversations/{id}/export?format=md` returns a clean Markdown
    transcript with agent labels and timestamps.
  - UI: "Export" in the conversation ⋯ menu + keyboard shortcut.
- **Implementation note:** New pure helper
  `format_conversation_markdown(conversation, messages, *, now=None) -> str`
  in `backend/app/services/chat_service.py` renders the transcript (title,
  exported-at ISO, agent header, per-message `## You · YYYY-MM-DD HH:MM`
  and `## Tutor (agent) · ts` sections — agent parens omitted when
  agent_name is None; "Mixed" when multiple agents spoke). Route
  `GET /api/v1/chat/conversations/{id}/export?format=md` in
  `backend/app/api/v1/routes/chat.py` returns
  `text/markdown; charset=utf-8` with
  `Content-Disposition: attachment; filename="conversation-<8hex>-<YYYYMMDD>.md"`
  (Access-Control-Expose-Headers surfaced); `format=xml` → 400; foreign
  owner → 404; auth required. Client helper
  `exportConversationMarkdown(id)` + `filenameFromDisposition()` in
  `frontend/src/lib/chat-api.ts` fetches with Bearer auth, consumes the
  blob, and downloads via a temporary `<a download>`. UI: replaced the
  ⋯ placeholder agent-E left in the sidebar row with a real popover
  (new `SidebarRow` component, Escape + outside-click closes) whose
  single menu item is "Export as Markdown" (Download icon,
  "Exporting…" pending state) — agent-E can now grow the menu with
  rename / archive / delete. 16 backend tests pass (6 route + 10
  service); 8 frontend tests pass
  (`frontend/src/lib/__tests__/chat-api.test.ts`). Backend ruff clean;
  full frontend suite 140/140 green; the single pre-existing
  `page.tsx:700` ref-in-render lint error is owned by P0-3.

---

## P2 — Production polish

### P2-1 — Smart auto-scroll
- **Status:** done
- **Owner:** agent-J (P2-1 scroll)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** —
- **Problem:** `chat/page.tsx:401-403` snaps to bottom on every message change,
  even when the user scrolled up to re-read.
- **Acceptance criteria:**
  - Track `isAtBottom` via IntersectionObserver on the sentinel.
  - Auto-scroll only when user is already at bottom.
  - "Jump to bottom" floating pill appears when new tokens arrive out-of-view.
- **Implementation note:** New hook
  `frontend/src/hooks/use-smart-auto-scroll.ts` exposes
  `{ isAtBottom, jumpToBottom }` driven by an IntersectionObserver on the
  sentinel with `rootMargin: 0px 0px 80px 0px` (80px "near bottom" band).
  Scroll policy: jump (auto) on initial mount with messages, always snap on
  fresh user message (detected via lastMessageIdRef comparison), smooth-scroll
  on any other change only when `isAtBottom`. Wired into `ChatArea` at
  `frontend/src/app/(portal)/chat/page.tsx`: added `scrollContainerRef` on the
  `flex-1 overflow-y-auto` div, replaced unconditional `scrollIntoView` effect
  with hook output, made ChatArea root `relative`, added `ArrowDown` pill
  (absolute bottom-28 right-6) gated by `!isAtBottom && messages.length > 0`.
  Tests: `use-smart-auto-scroll.test.ts` with MockIntersectionObserver covers
  initial mount, at-bottom smooth scroll, scrolled-up no-scroll, user-send
  always snaps, jumpToBottom behavior, and token-update no-scroll — 7/7 pass;
  full suite 125/125. Lint clean on new files; pre-existing errors in P0-3
  work at `chat/page.tsx:624,803` are unrelated. Build succeeds.

### P2-2 — Batch token renders
- **Status:** done
- **Owner:** agent-D (P2-2+P2-9 perf+skeleton)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** —
- **Problem:** `use-stream.ts:156-167` re-renders the entire list on every
  token. Visibly janks on long replies.
- **Acceptance criteria:**
  - Accumulate tokens in a ref; flush via `requestAnimationFrame` (≤ 60fps).
  - Final state on stream end is identical to pre-change behavior.
  - Microbenchmark shows > 3x reduction in renders on a 2k-token reply.
- **Implementation note:** Added `bufferRef` + `rafIdRef` to `useStream`
  and a module-level `scheduleFrame`/`cancelFrame` pair (rAF with microtask
  fallback for jsdom/SSR). Token chunks now accumulate in the buffer and
  one flush is scheduled per animation frame; `done`, error, abort, and
  unmount paths call `flushNow()` so no tokens are lost. The flush closure
  applies `detectedAgentName` and clears `isThinking` on its first call,
  preserving the pre-batching contract for the first-token transition.
  Added microbenchmark in `src/hooks/use-stream.test.ts`:
  **500 tokens → 1 content-update render** (threshold < 100; un-batched
  baseline is ~500). All 108 frontend tests pass; lint/build clean.
  Rebased on top of agent-B (P0-1 history) and agent-C (P0-5 typed errors);
  no conflicts with their code.

### P2-3 — Agent identity before first token
- **Status:** done
- **Owner:** agent-O (P2-3 identity)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** —
- **Problem:** Backend emits `agent_name` first (`stream.py:179`) but UI only
  shows it as a small caption once tokens start.
- **Acceptance criteria:**
  - Thinking state shows "Tutor is thinking…" with the routed agent label +
    color, before the first token arrives.
- **Implementation note:** New module
  `frontend/src/lib/agent-labels.ts` exports `AGENT_LABELS` (all 20
  agents keyed by lowercase `agent_name`, grouped into 5 categories),
  `AGENT_CATEGORY_COLORS` (creation=indigo, learning=teal,
  analytics=amber, career=purple, engagement=pink), and
  `getAgentLabel(name)` (case-insensitive, trims; falls back to
  `{displayName: "Tutor", colorClass: "bg-slate-400"}` for
  null/undefined/empty, `moa`, and unknown names). `ThinkingDots` in
  `frontend/src/app/(portal)/chat/page.tsx` (lines 364-395) now takes
  `agentName?: string | null`, resolves it via `getAgentLabel`, and
  renders a 1.5×1.5 (6px) rounded category dot + the text
  "{displayName} is thinking…" — or a neutral "Thinking…" + slate dot
  when no agent is known yet. `AssistantBubble`'s `isThinking` branch
  (line ~496) threads `agentName` into `ThinkingDots`. The existing
  bounce dots + `agent_name` caption above the bubble + pulsing avatar
  gradient are preserved so the only visible change is the new identity
  line inside the bubble. Relies on `use-stream.ts:522-529` which
  already patches `agentName` onto the pending assistant message when
  the first SSE event carries only `agent_name` (no chunk) — no hook
  changes needed. Unit tests:
  `frontend/src/lib/__tests__/agent-labels.test.ts` (14 cases: all 20
  agents, category color map, null / undefined / empty / moa / unknown
  fallbacks, case-insensitivity + whitespace, per-category dot
  assertions). Integration test:
  `frontend/src/app/(portal)/chat/__tests__/thinking-identity.test.tsx`
  uses a controllable `ReadableStream` to script an SSE sequence where
  the first event carries only `conversation_id` + `agent_name`
  (socratic_tutor) BEFORE any chunk; asserts the bubble flips from
  "Thinking…" to "Socratic Tutor is thinking…" + teal dot. A second
  case verifies `agent_name="moa"` falls back to "Tutor is thinking…".
  Full suite: 163/163 tests pass (22 files). Lint touched files clean;
  the single pre-existing error on `chat/page.tsx:779` belongs to
  P0-3's `onInputChangeRef.current = onInputChange` line and is
  unrelated.

### P2-4 — Show routing reason + allow override
- **Status:** done
- **Owner:** agent-P2-4
- **Claimed:** 2026-04-20
- **Completed:** 2026-04-20
- **Depends-on:** P2-3
- **Problem:** Auto-routing is opaque. When it picks wrong, students have no recourse.
- **Acceptance criteria:**
  - Backend emits `{routing_reason: "keyword:explain"}` in the first SSE event.
  - Assistant bubble shows a subtle "Routed to Tutor · change" affordance.
  - Clicking "change" offers a dropdown of all 20 agents; regenerates the reply
    under the chosen one (via P1-2).
- **Implementation note:** MOA `moa.py` now returns `routing_reason` alongside
  agent name ("keyword:<pattern>" on keyword hit, "llm_classifier" on fallback).
  `stream.py` emits it in the first SSE event. `use-stream.ts` captures it on
  `StreamMessage.routingReason`. `RoutingReasonBadge` component (page.tsx:1192)
  renders "Routed to X · reason · change" under the agent caption. "change"
  opens a grouped 20-agent dropdown; selection calls `regenerateMessage(id,
  {agentOverride})`. Regenerate backend extended with `agent_override` body
  param. Tests: `test_chat_regenerate.py` + `regenerate.test.tsx`.

### P2-5 — Message metadata on hover
- **Status:** done
- **Owner:** agent-P2-5
- **Claimed:** 2026-04-20
- **Completed:** 2026-04-20
- **Depends-on:** P0-2
- **Problem:** No visibility into latency / tokens / agent per message.
- **Acceptance criteria:**
  - Hover shows: first-token latency, total duration, token count, agent,
    model version.
  - Backend persists these on `chat_messages` when stream completes.
- **Implementation note:** Migration `0033_chat_messages_metadata.py` adds
  `first_token_ms`, `total_duration_ms`, `input_tokens`, `output_tokens`,
  `model` nullable columns to `chat_messages`. `stream.py` tracks
  `start_time` and stamps these on the assistant row on stream done. Schemas
  extended in `chat.py`. Frontend `MessageMetadataPopover` (page.tsx) shows
  on hover of assistant bubble agent-name caption. Tests: `test_chat_metadata.py`
  (backend) + `metadata.test.tsx` (frontend).

### P2-6 — Mobile sidebar drawer
- **Status:** done
- **Owner:** agent-P2-6
- **Claimed:** 2026-04-20
- **Completed:** 2026-04-20
- **Depends-on:** P0-3
- **Problem:** Sidebar is `hidden lg:flex`. Mobile has no conversation access.
- **Acceptance criteria:**
  - Hamburger on mobile header opens a full-height slide-in drawer with the
    conversation list.
  - Closes on selection + on backdrop tap. Swipe-to-close.
- **Implementation note:** Extracted the conversations list into a pure
  `ChatSidebar` component (no outer `<aside>`) rendered inside the existing
  `hidden lg:flex` desktop `<aside>` and, below `lg:`, inside a fixed
  `w-80 max-w-[85vw]` drawer overlay with a `bg-black/50` backdrop button
  and `translate-x-0` slide-in. Mobile header now leads with a
  `aria-label="Open conversations"` hamburger. Drawer unmounts on close to
  avoid duplicating sidebar DOM (other chat tests grep by the shared
  labels). Swipe-left >60px on the drawer closes via a tiny
  touchstart/touchend handler — no lib. New `mobile-drawer.test.tsx`
  covers hamburger render, open, backdrop close, and row-selection close;
  swipe path skipped (jsdom).

### P2-7 — Rate-limit + budget awareness
- **Status:** done
- **Owner:** agent-P2-7
- **Claimed:** 2026-04-20
- **Completed:** 2026-04-20
- **Depends-on:** P0-5
- **Problem:** 429s are invisible as 429s; no daily-budget surface.
- **Acceptance criteria:**
  - Backend returns `X-RateLimit-Remaining` + `Retry-After` on stream endpoint.
  - UI shows a compact pill "X messages left this hour" when remaining < 5.
  - 429 banner counts down in real time.
- **Implementation note:** `app/core/rate_limit.py` + `stream.py:_rate_limit_headers()`
  compute `X-RateLimit-Remaining` and `Retry-After` from slowapi window stats on
  every response; `RateLimitExceeded` handler in `main.py` returns 429 JSON with
  `retry_after_seconds`. `use-stream.ts` reads these headers on 200/429, exposing
  `rateLimitRemaining` + `retryAfterSeconds`. `chat/page.tsx`: pill above composer
  when remaining < 5; `ErrorBanner` (P0-5) extended with mm:ss countdown for
  `rate_limit` kind. Tests: `test_stream_rate_limit.py` (backend) + `rate-limit.test.tsx`
  (4 frontend tests, including pill, quiet-state, singular copy, and 429 banner).

### P2-8 — Slash commands + keyboard shortcuts
- **Status:** todo
- **Owner:** —
- **Claimed:** —
- **Completed:** —
- **Depends-on:** P1-7, P1-9
- **Problem:** Power users have no accelerators.
- **Acceptance criteria:**
  - `/tutor`, `/code`, `/quiz`, `/career`, `/attach`, `/export`, `/new`
    autocomplete in the composer.
  - Shortcuts: `Cmd+K` new chat, `Cmd+/` switch mode, `↑` in empty composer
    edits last user message, `Esc` stops stream.
- **Implementation note:** —

### P2-9 — Better loading skeleton
- **Status:** done
- **Owner:** agent-D (P2-2+P2-9 perf+skeleton)
- **Claimed:** 2026-04-19
- **Completed:** 2026-04-19
- **Depends-on:** —
- **Problem:** `chat/page.tsx:475` Suspense fallback is literally the text
  "Loading…". Everything else in the portal uses skeletons.
- **Acceptance criteria:**
  - Replace with a skeleton matching the chat layout (sidebar shimmer + body
    shimmer + composer shimmer).
- **Implementation note:** New component
  `frontend/src/app/(portal)/chat/chat-skeleton.tsx` mirrors the real
  layout: sidebar (`hidden lg:flex w-64 xl:w-72`) with header bar + 4 fake
  conversation rows; centered welcome shimmer with circular bot icon,
  title/subtitle lines, 2x3 suggested-prompt tile grid matching
  `SUGGESTED_PROMPTS.length`; bottom rounded-pill composer shimmer. Uses
  the existing `@/components/ui/skeleton` primitive so dark-mode adapts
  via the `bg-foreground/[0.06]` token. Wired into `chat/page.tsx` by
  replacing the Suspense fallback at line ~475 with `<ChatSkeleton />`
  and adding the import.

### P2-10 — Warn on mode switch that would lose context
- **Status:** done
- **Owner:** agent-P2-10
- **Claimed:** 2026-04-20
- **Completed:** 2026-04-20
- **Depends-on:** P0-2
- **Problem:** `chat/page.tsx:547-550` silently wipes messages on mode switch.
- **Acceptance criteria:**
  - After P0-2, mode switch stays within the same conversation; pass
    `agent_name` per-turn instead of remounting.
  - If a remount is genuinely needed, show a confirm dialog with "Start new
    conversation" + "Cancel".
- **Implementation note:** Extended `useStream.sendMessage` with a 3rd
  `agentOverride?: string | null` arg; when provided it wins over the hook's
  `agentName` option for both the request body and the in-memory assistant
  bubble (null = force auto routing). `handleModeChange` in `ChatPageInner`
  is now a one-liner `setActiveMode(m)` — no more remount, convId wipe, or
  URL reset. `ChatArea.handleSend` + `handleEditUserMessage` thread
  `mode.agentName` per-turn so a mid-conversation switch takes effect on
  the next send without losing transcript. Added a ⊕ "Start new
  conversation" button to the composer (visible only when
  `messages.length > 0`) that opens a new `ConfirmStartNewDialog` (hand-
  rolled modal matching the delete-confirm style — shadcn's AlertDialog
  isn't installed); Cancel keeps state, Confirm runs the full reset
  (messages/convId cleared, `?c=` dropped, `chatKey` bumped). New test
  file `frontend/src/app/(portal)/chat/__tests__/mode-switch.test.tsx`
  with 4 cases: mid-conversation mode switch preserves transcript +
  convId, next send carries the new `agent_name`, first-turn send
  respects pre-selected mode, and the Cancel/Confirm dialog behavior.
  Full suite: 27 files, 196 passing, 1 skipped.

---

## P3 — Learning-platform differentiators

### P3-1 — "Explain differently" button
- **Status:** todo
- **Owner:** —
- **Claimed:** —
- **Completed:** —
- **Depends-on:** P1-2
- **Acceptance criteria:**
  - Hover action on assistant bubble opens: Simpler / More rigorous / Via
    analogy / Show code. Reruns with an injected overlay.
- **Implementation note:** —

### P3-2 — "Turn this into flashcards" → spaced_repetition
- **Status:** todo
- **Owner:** —
- **Claimed:** —
- **Completed:** —
- **Depends-on:** P0-2
- **Acceptance criteria:**
  - One-click action on an assistant bubble extracts Q/A pairs and enqueues
    them into the `spaced_repetition` agent's card store.
  - Student sees a toast "5 cards added to review".
- **Implementation note:** —

### P3-3 — "Quiz me on this" → adaptive_quiz
- **Status:** todo
- **Owner:** —
- **Claimed:** —
- **Completed:** —
- **Depends-on:** P0-2
- **Acceptance criteria:**
  - Action passes the current conversation as context to `adaptive_quiz`;
    launches a 5-question quiz in a side panel.
- **Implementation note:** —

### P3-4 — Save to notebook
- **Status:** todo
- **Owner:** —
- **Claimed:** —
- **Completed:** —
- **Depends-on:** P0-2
- **Acceptance criteria:**
  - Per-student `notebook_entries` table.
  - "Save" action on any bubble; Notebook page lists, searches, exports.
- **Implementation note:** —

### P3-5 — Mastery delta after conversation
- **Status:** todo
- **Owner:** —
- **Claimed:** —
- **Completed:** —
- **Depends-on:** P0-2, integration with `knowledge_graph` agent
- **Acceptance criteria:**
  - On conversation end (or on demand), show "Your understanding of {concept}
    went from X → Y" based on `knowledge_graph` agent's EMA.
- **Implementation note:** —

### P3-6 — Inline citations to course content
- **Status:** todo
- **Owner:** —
- **Claimed:** —
- **Completed:** —
- **Depends-on:** Pinecone RAG (Phase 6)
- **Acceptance criteria:**
  - RAG citations render as numbered superscripts with hover cards linking to
    the exact lesson + timestamp.
- **Implementation note:** —

### P3-7 — Multi-agent side-by-side
- **Status:** todo
- **Owner:** —
- **Claimed:** —
- **Completed:** —
- **Depends-on:** P0-1
- **Acceptance criteria:**
  - "Compare" toggle runs the same prompt through two agents in parallel,
    renders responses side-by-side; student picks the better one (feeds P1-5).
- **Implementation note:** —

### P3-8 — "Why did you say that?" — overlay stack viewer
- **Status:** todo
- **Owner:** —
- **Claimed:** —
- **Completed:** —
- **Depends-on:** P2-5
- **Acceptance criteria:**
  - Debug-style popover on assistant bubble shows which overlays were applied
    (scaffolding level, socratic level, disagreement, confidence, honesty,
    misconception, intent-before-debug), in student-friendly language.
- **Implementation note:** —

---

## Change log (append-only)

- 2026-04-19 — Tracker created from senior-engineer critique of chat surface.
