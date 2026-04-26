"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AlertTriangle, Archive, ArchiveRestore, ArrowDown, ArrowUp, AtSign, Bookmark, BookmarkCheck, BookOpen, Bot, BriefcaseBusiness, Check, ChevronLeft, ChevronRight, Clock, Code2, Copy, Download, FileCode, FileText, GraduationCap, ImageIcon, ListChecks, Lock, MoreHorizontal, Paperclip, Pencil, Pin, PinOff, Plus, Puzzle, RefreshCw, RotateCw, Search, Sparkles, Square, Timer, Trash2, User, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { MarkdownRenderer } from "@/components/features/markdown-renderer";
import {
  useStream,
  clearAuthForReauth,
  type StreamError,
  type StreamMessage,
} from "@/hooks/use-stream";
import { useSmartAutoScroll } from "@/hooks/use-smart-auto-scroll";
import { exercisesApi, srsApi } from "@/lib/api-client";
import { useDueCards } from "@/lib/hooks/use-srs";
import { useWelcomePrompts } from "@/lib/hooks/use-welcome-prompts";
import {
  chatApi,
  exportConversationMarkdown,
  regenerateMessage,
  uploadAttachment,
  type ChatAttachmentRead,
  type ChatContextRef,
  type ChatFeedbackCreate,
  type ChatFeedbackRead,
  type ChatMessageRead,
  type ContextSuggestionsResponse,
  type ConversationListItem,
  type QuizQuestion,
} from "@/lib/chat-api";
import { toast } from "@/lib/toast";
import { ChatSkeleton } from "./chat-skeleton";
import { FeedbackControls } from "./feedback-controls";
import { SaveNoteModal } from "@/components/features/notebook/save-note-modal";
import { MakeFlashcardsModal } from "@/components/features/flashcards/make-flashcards-modal";
import { TutorScreen } from "@/components/v8/screens/tutor-screen";
import {
  getAgentLabel,
  getAgentGroups,
  formatRoutingReason,
} from "@/lib/agent-labels";

// ── Mode chips ───────────────────────────────────────────────────
const MODES = [
  { label: "Auto",        agentName: null,               icon: Sparkles,       color: "text-primary" },
  { label: "Tutor",       agentName: "socratic_tutor",   icon: GraduationCap,  color: "text-violet-500" },
  { label: "Code Review", agentName: "coding_assistant", icon: Code2,          color: "text-blue-500" },
  { label: "Career",      agentName: "career_coach",     icon: BriefcaseBusiness, color: "text-orange-500" },
  { label: "Quiz Me",     agentName: "adaptive_quiz",    icon: Bot,            color: "text-green-500" },
] as const;

type ModeAgent = (typeof MODES)[number]["agentName"];

// ── Helpers ──────────────────────────────────────────────────────
const AGENT_GRADIENTS: Record<string, string> = {
  socratic_tutor:   "from-violet-500 to-purple-600",
  coding_assistant: "from-blue-500 to-cyan-600",
  adaptive_quiz:    "from-green-500 to-emerald-600",
  career_coach:     "from-orange-500 to-amber-600",
};

function agentGradient(name: string | undefined) {
  if (!name) return "from-primary to-primary/70";
  return AGENT_GRADIENTS[name] ?? "from-primary to-primary/70";
}

// P0-3 — drop the localStorage conversation cache in favor of server truth.
// We still stash the most-recently-viewed id so a reload renders the same
// conversation before the sidebar list has finished fetching.
const LAST_VIEWED_KEY = "chat-last-viewed-v1";

function readLastViewedId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(LAST_VIEWED_KEY);
  } catch {
    return null;
  }
}

function writeLastViewedId(id: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (id) window.localStorage.setItem(LAST_VIEWED_KEY, id);
    else window.localStorage.removeItem(LAST_VIEWED_KEY);
  } catch {
    /* quota / disabled storage — ignore */
  }
}

/** Map backend `ChatMessageRead` → hook's in-memory `StreamMessage`. */
function messageFromServer(m: ChatMessageRead): StreamMessage | null {
  // The hook doesn't render `system` messages; filter them defensively.
  if (m.role !== "user" && m.role !== "assistant") return null;
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    agentName: m.agent_name ?? undefined,
    timestamp: new Date(m.created_at),
    // P1-5 — hydrate the user's own thumb rating inline so the bubble can
    // render its active state without a follow-up fetch.
    myFeedback: m.my_feedback ?? undefined,
    // P1-2 — sibling set for the regenerate navigator. Empty array stays
    // undefined on the hook side so the navigator component can render
    // via a simple length check.
    siblingIds: m.sibling_ids && m.sibling_ids.length > 0 ? m.sibling_ids : undefined,
    // P2-5 — hover-panel metadata. Null/absent fields flow through as
    // `null`; the popover formatter renders missing values as "—".
    firstTokenMs: m.first_token_ms ?? null,
    totalDurationMs: m.total_duration_ms ?? null,
    inputTokens: m.input_tokens ?? null,
    outputTokens: m.output_tokens ?? null,
    model: m.model ?? null,
  };
}

// ── Sidebar row + actions menu ───────────────────────────────────
// P1-8 — the row hosts the ⋯ menu anchor for Rename / Pin / Archive /
// Delete / Export. Rename is inline (turns the title into a textbox;
// Enter saves, Esc cancels). Delete opens a small confirm dialog — we
// use a hand-rolled modal rather than shadcn AlertDialog (not installed
// in this repo) so the component stays self-contained. All menu items
// have aria labels + keyboard handlers per the accessibility criteria.
function SidebarRow({
  conv,
  isActive,
  onSelect,
  onRename,
  onTogglePin,
  onToggleArchive,
  onDelete,
}: {
  conv: ConversationListItem;
  isActive: boolean;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onTogglePin: (id: string, pinned: boolean) => Promise<void>;
  onToggleArchive: (id: string, archived: boolean) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(conv.title ?? "");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const editInputRef = useRef<HTMLInputElement>(null);

  // Close menu on outside click + on Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  // Focus the rename input when it appears.
  useEffect(() => {
    if (editing) {
      editInputRef.current?.focus();
      editInputRef.current?.select();
    }
  }, [editing]);

  const handleExport = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setMenuOpen(false);
    if (exporting) return;
    setExporting(true);
    try {
      await exportConversationMarkdown(conv.id);
    } catch (err) {
      console.error("[chat] export failed", err);
    } finally {
      setExporting(false);
    }
  };

  const beginRename = (e: React.MouseEvent) => {
    e.stopPropagation();
    setMenuOpen(false);
    setEditValue(conv.title ?? "");
    setEditing(true);
  };

  const commitRename = async () => {
    const next = editValue.trim();
    setEditing(false);
    if (!next || next === (conv.title ?? "")) return;
    try {
      await onRename(conv.id, next);
    } catch (err) {
      console.error("[chat] rename failed", err);
    }
  };

  const cancelRename = () => {
    setEditing(false);
    setEditValue(conv.title ?? "");
  };

  const handleTogglePin = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setMenuOpen(false);
    try {
      await onTogglePin(conv.id, !conv.pinned_at);
    } catch (err) {
      console.error("[chat] pin toggle failed", err);
    }
  };

  const handleToggleArchive = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setMenuOpen(false);
    try {
      await onToggleArchive(conv.id, !conv.archived_at);
    } catch (err) {
      console.error("[chat] archive toggle failed", err);
    }
  };

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setMenuOpen(false);
    setConfirmingDelete(true);
  };

  const confirmDelete = async () => {
    setConfirmingDelete(false);
    try {
      await onDelete(conv.id);
    } catch (err) {
      console.error("[chat] delete failed", err);
    }
  };

  const modeMatch = MODES.find((m) => m.agentName === conv.agent_name);
  const title = conv.title?.trim() || "Untitled conversation";
  const ts = new Date(conv.updated_at);
  const isPinned = Boolean(conv.pinned_at);
  const isArchived = Boolean(conv.archived_at);

  return (
    <div
      ref={rootRef}
      className={cn(
        "group relative w-full rounded-xl mb-0.5 transition-colors",
        isActive
          ? "bg-primary/10 text-primary"
          : "hover:bg-muted/70 text-foreground",
      )}
    >
      {editing ? (
        <div className="px-3 py-2.5 pr-2">
          <input
            ref={editInputRef}
            type="text"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void commitRename();
              } else if (e.key === "Escape") {
                e.preventDefault();
                cancelRename();
              }
            }}
            onBlur={() => {
              // Commit on blur so clicking another row saves the rename.
              void commitRename();
            }}
            onClick={(e) => e.stopPropagation()}
            aria-label="Rename conversation"
            className="w-full rounded-md border border-primary/40 bg-background px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-primary/30"
          />
        </div>
      ) : (
        <button
          onClick={() => onSelect(conv.id)}
          aria-label={`Open conversation: ${title}`}
          className="w-full text-left rounded-xl px-3 py-2.5 pr-9"
        >
          <div className="flex items-center gap-1.5">
            {isPinned && (
              <Pin
                className="h-3 w-3 shrink-0 text-primary/70"
                aria-label="Pinned"
              />
            )}
            <p className="text-sm font-medium truncate leading-snug">{title}</p>
          </div>
          <div className="flex items-center gap-1.5 mt-1">
            {conv.agent_name && (
              <span
                className={cn(
                  "text-[10px] font-medium capitalize",
                  isActive ? "text-primary/70" : modeMatch?.color ?? "text-primary/60",
                )}
              >
                {modeMatch?.label ?? conv.agent_name.split("_").join(" ")}
              </span>
            )}
            <span className="text-[10px] text-muted-foreground">
              {ts.toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            </span>
            {conv.message_count > 0 && (
              <span className="ml-auto text-[10px] text-muted-foreground/60">
                {conv.message_count}
              </span>
            )}
          </div>
        </button>
      )}
      {!editing && (
        <button
          type="button"
          aria-label="Conversation actions"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={(e) => {
            e.stopPropagation();
            setMenuOpen((v) => !v);
          }}
          className={cn(
            "absolute right-2 top-2 h-6 w-6 rounded-md flex items-center justify-center text-muted-foreground/60 hover:text-foreground hover:bg-muted/80 transition-opacity",
            menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
          )}
        >
          <MoreHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      )}
      {menuOpen && (
        <div
          role="menu"
          aria-label="Conversation actions menu"
          className="absolute right-2 top-9 z-20 min-w-[180px] rounded-lg border bg-popover text-popover-foreground shadow-md py-1"
        >
          <button
            role="menuitem"
            type="button"
            onClick={beginRename}
            aria-label="Rename conversation"
            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left hover:bg-muted"
          >
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Rename</span>
          </button>
          <button
            role="menuitem"
            type="button"
            onClick={handleTogglePin}
            aria-label={isPinned ? "Unpin conversation" : "Pin conversation"}
            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left hover:bg-muted"
          >
            {isPinned ? (
              <PinOff className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <Pin className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            <span>{isPinned ? "Unpin" : "Pin"}</span>
          </button>
          <button
            role="menuitem"
            type="button"
            onClick={handleToggleArchive}
            aria-label={
              isArchived ? "Unarchive conversation" : "Archive conversation"
            }
            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left hover:bg-muted"
          >
            {isArchived ? (
              <ArchiveRestore className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <Archive className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            <span>{isArchived ? "Unarchive" : "Archive"}</span>
          </button>
          <button
            role="menuitem"
            type="button"
            onClick={handleExport}
            disabled={exporting}
            aria-label="Export conversation as Markdown"
            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left hover:bg-muted disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{exporting ? "Exporting…" : "Export as Markdown"}</span>
          </button>
          <div className="my-1 h-px bg-border" role="none" />
          <button
            role="menuitem"
            type="button"
            onClick={handleDeleteClick}
            aria-label="Delete conversation"
            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left text-destructive hover:bg-destructive/10"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Delete</span>
          </button>
        </div>
      )}
      {confirmingDelete && (
        <DeleteConfirmDialog
          title={title}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setConfirmingDelete(false)}
        />
      )}
    </div>
  );
}

// ── Delete confirm dialog ────────────────────────────────────────
// shadcn's AlertDialog isn't installed in this repo; we render a minimal
// modal ourselves so the sidebar doesn't pull in a new dep. Backdrop tap
// or Escape dismisses; the primary CTA calls `onConfirm`.
function DeleteConfirmDialog({
  title,
  onConfirm,
  onCancel,
}: {
  title: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    };
    document.addEventListener("keydown", onKey);
    // Move focus to the cancel-adjacent primary so Enter confirms.
    confirmBtnRef.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Confirm delete conversation"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onCancel}
        aria-hidden="true"
      />
      <div className="relative z-10 w-full max-w-sm rounded-xl border bg-popover p-5 text-popover-foreground shadow-lg">
        <h2 className="text-sm font-semibold">Delete conversation?</h2>
        <p className="mt-2 text-xs text-muted-foreground">
          &ldquo;{title}&rdquo; will be permanently deleted. This cannot be undone.
        </p>
        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-muted"
            aria-label="Cancel delete"
          >
            Cancel
          </button>
          <button
            ref={confirmBtnRef}
            type="button"
            onClick={onConfirm}
            className="rounded-md bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90"
            aria-label="Confirm delete"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Sidebar ──────────────────────────────────────────────────────
// P1-8 — adds a debounced search input at the top, an "Show archived"
// toggle at the bottom, and a Pinned section rendered above a divider
// when any row is pinned. Search + archived toggle both trigger a
// refetch via the parent (`onQueryChange`, `onToggleArchived`).
//
// P2-6 — extracted as a pure component so it can be rendered inside
// either the desktop `<aside>` (hidden on mobile) or the mobile slide-in
// drawer overlay. The parent owns the breakpoint wrappers; this component
// only renders the header, search input, conversation list, and the
// show-archived toggle.
function ChatSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  loading,
  query,
  onQueryChange,
  showArchived,
  onToggleArchived,
  onRename,
  onTogglePin,
  onToggleArchive,
  onDelete,
}: {
  conversations: ConversationListItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  loading: boolean;
  query: string;
  onQueryChange: (q: string) => void;
  showArchived: boolean;
  onToggleArchived: (next: boolean) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onTogglePin: (id: string, pinned: boolean) => Promise<void>;
  onToggleArchive: (id: string, archived: boolean) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  // P1-8 — split pinned vs the rest so we can render the pinned section
  // with its own header above a divider. Backend already orders pinned
  // first; splitting in the UI is cosmetic.
  const pinned = conversations.filter((c) => c.pinned_at);
  const rest = conversations.filter((c) => !c.pinned_at);
  const hasQuery = query.trim().length > 0;
  const { data: dueCards } = useDueCards(50);
  const dueCount = dueCards?.length ?? 0;

  return (
    <div className="flex flex-col h-full w-full">
      <div className="flex items-center justify-between px-4 h-16 border-b shrink-0">
        <div className="flex items-center gap-2">
          <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-primary to-primary/60 flex items-center justify-center">
            <Bot className="h-4 w-4 text-white" aria-hidden="true" />
          </div>
          <span className="font-semibold text-sm">AI Tutor</span>
          {dueCount > 0 && (
            <Link
              href="/today"
              className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-600 hover:bg-amber-500/20 transition-colors"
              aria-label={`${dueCount} card${dueCount !== 1 ? "s" : ""} due for review — go to Today`}
            >
              <BookOpen className="h-3 w-3" aria-hidden="true" />
              {dueCount} due
            </Link>
          )}
        </div>
        <button
          onClick={onNew}
          aria-label="New conversation"
          className="h-8 w-8 rounded-lg flex items-center justify-center hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <div className="px-3 pt-3 pb-2 shrink-0">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/60"
            aria-hidden="true"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Search conversations…"
            aria-label="Search conversations"
            className="w-full rounded-lg border bg-background/60 pl-8 pr-8 py-1.5 text-xs outline-none placeholder:text-muted-foreground/50 focus:border-primary/40 focus:ring-2 focus:ring-primary/20"
          />
          {hasQuery && (
            <button
              type="button"
              onClick={() => onQueryChange("")}
              aria-label="Clear search"
              className="absolute right-1.5 top-1/2 h-5 w-5 -translate-y-1/2 rounded-md text-muted-foreground/60 hover:bg-muted hover:text-foreground flex items-center justify-center"
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      <div
        className="flex-1 overflow-y-auto py-1 px-2"
        data-testid="conversation-list"
      >
        {loading ? (
          <div
            role="status"
            aria-label="Loading conversations"
            className="flex flex-col items-center justify-center py-12 gap-3 text-center px-4"
          >
            <div
              className="h-6 w-6 rounded-full border-2 border-muted border-t-primary animate-spin"
              aria-hidden="true"
            />
            <p className="text-xs text-muted-foreground">Loading conversations…</p>
          </div>
        ) : conversations.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 gap-3 text-center px-4">
            <Clock className="h-8 w-8 text-muted-foreground/30" aria-hidden="true" />
            <p className="text-xs text-muted-foreground">
              {hasQuery ? "No matches" : "No conversations yet"}
            </p>
          </div>
        ) : (
          <>
            {pinned.length > 0 && (
              <>
                <p className="px-2 mt-1 mb-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50">
                  Pinned
                </p>
                {pinned.map((conv) => (
                  <SidebarRow
                    key={conv.id}
                    conv={conv}
                    isActive={activeId === conv.id}
                    onSelect={onSelect}
                    onRename={onRename}
                    onTogglePin={onTogglePin}
                    onToggleArchive={onToggleArchive}
                    onDelete={onDelete}
                  />
                ))}
                <div
                  className="my-2 mx-2 h-px bg-border"
                  role="separator"
                  aria-hidden="true"
                />
              </>
            )}
            {rest.length > 0 && (
              <>
                <p className="px-2 mt-1 mb-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50">
                  {hasQuery ? "Results" : "Recent"}
                </p>
                {rest.map((conv) => (
                  <SidebarRow
                    key={conv.id}
                    conv={conv}
                    isActive={activeId === conv.id}
                    onSelect={onSelect}
                    onRename={onRename}
                    onTogglePin={onTogglePin}
                    onToggleArchive={onToggleArchive}
                    onDelete={onDelete}
                  />
                ))}
              </>
            )}
          </>
        )}
      </div>

      <div className="border-t px-3 py-2 shrink-0">
        <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground hover:text-foreground">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => onToggleArchived(e.target.checked)}
            aria-label="Show archived conversations"
            className="h-3.5 w-3.5 rounded border-border accent-primary"
          />
          <span>Show archived</span>
        </label>
      </div>
    </div>
  );
}

// ── Welcome screen ───────────────────────────────────────────────
// Welcome prompts now come from `useWelcomePrompts(mode)` — the backend
// personalizes them from the user's last lesson, last failed exercise,
// last touched skill, and recent misconceptions. The hook ships a curated
// fallback so anonymous / loading users still see something useful.
function modeAgentToHookMode(
  agentName: ModeAgent,
): "auto" | "tutor" | "code" | "career" | "quiz" {
  switch (agentName) {
    case "socratic_tutor":
      return "tutor";
    case "coding_assistant":
      return "code";
    case "career_coach":
      return "career";
    case "adaptive_quiz":
      return "quiz";
    default:
      return "auto";
  }
}

function WelcomeScreen({ mode, onPrompt }: { mode: typeof MODES[number]; onPrompt: (text: string) => void }) {
  const hookMode = modeAgentToHookMode(mode.agentName);
  const { data: promptsData } = useWelcomePrompts(hookMode);
  const prompts = promptsData.prompts;
  return (
    <div className="flex flex-col items-center justify-center h-full px-6 py-12 gap-8">
      <div className="relative">
        <div className={cn("h-20 w-20 rounded-3xl bg-gradient-to-br flex items-center justify-center shadow-lg", agentGradient(mode.agentName ?? undefined))}>
          <Bot className="h-10 w-10 text-white" aria-hidden="true" />
        </div>
        <div className="absolute -bottom-1 -right-1 h-6 w-6 rounded-full bg-green-500 border-2 border-background flex items-center justify-center">
          <Sparkles className="h-3 w-3 text-white" aria-hidden="true" />
        </div>
      </div>

      <div className="text-center max-w-md">
        <h2 className="text-2xl font-bold tracking-tight">
          {mode.agentName ? `${mode.label} Mode` : "Your AI Coach"}
        </h2>
        <p className="text-muted-foreground text-sm mt-2 leading-relaxed">
          {mode.agentName
            ? `Focused on ${mode.label.toLowerCase()}. Ask me anything.`
            : "The right agent is automatically selected based on your question."}
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 w-full max-w-4xl">
        {prompts.map((p) => (
          <button
            key={p.text}
            onClick={() => onPrompt(p.text)}
            aria-label={`Suggested prompt: ${p.text}`}
            data-prompt-rationale={p.rationale}
            className="group flex items-start gap-3 rounded-2xl border border-border/60 bg-card/80 px-4 py-3.5 text-left hover:border-primary/40 hover:bg-primary/5 hover:shadow-sm transition-all duration-150"
          >
            <span className="text-lg leading-none mt-0.5 shrink-0">{p.icon}</span>
            <span className="text-sm text-muted-foreground group-hover:text-foreground transition-colors line-clamp-2 leading-snug">
              {p.text}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Message bubbles ──────────────────────────────────────────────
// P1-1 — user bubble hosts an inline edit affordance. `onEdit` is only
// provided when the row is a persisted (server-side) message id AND the
// transcript isn't currently streaming; otherwise the pencil is hidden. The
// textarea reuses the bubble's width and autosizes to content.
// P1-3 — when a user turn has been edited, the original + each edit persist
// as a chain of `chat_messages` rows (forked via `parent_id`). The server
// returns the full chain in `sibling_ids`; we render the same `< k / N >`
// navigator component used on assistant bubbles so students can step
// between the branches without losing prior drafts.
function UserBubble({
  messageId,
  content,
  onEdit,
  canEdit,
  siblingIds,
  onSelectSibling,
  // P2-8 — when true, open the editor automatically (triggered by ↑ shortcut).
  forceEdit,
  onForceEditConsumed,
}: {
  messageId: string;
  content: string;
  canEdit: boolean;
  onEdit?: (messageId: string, nextContent: string) => Promise<void>;
  // P1-3 — user-side sibling list (edit branches). Only rendered when the
  // chain has more than one entry. The parent owns the fetch + id swap.
  siblingIds?: string[];
  onSelectSibling?: (messageId: string, targetId: string) => Promise<void>;
  forceEdit?: boolean;
  onForceEditConsumed?: () => void;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(content);
  const [isSaving, setIsSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Autosize the textarea when entering edit mode + as the draft grows.
  useEffect(() => {
    if (!isEditing) return;
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 280)}px`;
  }, [isEditing, draft]);

  // If the server-side content changes (e.g. after a successful edit the
  // bubble re-renders with the new message's text), keep the draft in sync
  // when we're NOT mid-edit so the next open starts from fresh state.
  useEffect(() => {
    if (!isEditing) setDraft(content);
  }, [content, isEditing]);

  const openEditor = () => {
    setDraft(content);
    setEditError(null);
    setIsEditing(true);
    // Focus on next tick so the textarea has mounted.
    requestAnimationFrame(() => {
      const ta = textareaRef.current;
      if (ta) {
        ta.focus();
        ta.setSelectionRange(ta.value.length, ta.value.length);
      }
    });
  };

  // P2-8 — open the editor when the parent requests it (↑ shortcut).
  useEffect(() => {
    if (forceEdit && canEdit && !isEditing) {
      openEditor();
      onForceEditConsumed?.();
    }
  // Only re-run on forceEdit change; openEditor is stable (no deps change).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forceEdit]);

  const cancelEdit = () => {
    if (isSaving) return;
    setIsEditing(false);
    setDraft(content);
    setEditError(null);
  };

  const save = async () => {
    if (!onEdit) return;
    const next = draft.trim();
    if (!next) {
      setEditError("Message can't be empty.");
      return;
    }
    if (next === content.trim()) {
      // No-op edit — just close without round-tripping.
      setIsEditing(false);
      return;
    }
    setIsSaving(true);
    setEditError(null);
    try {
      await onEdit(messageId, next);
      setIsEditing(false);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Edit failed. Please try again.";
      setEditError(message);
    } finally {
      setIsSaving(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      cancelEdit();
    } else if (
      e.key === "Enter" &&
      (e.metaKey || e.ctrlKey) &&
      !e.shiftKey
    ) {
      e.preventDefault();
      void save();
    }
  };

  return (
    <div className="group/msg flex justify-end gap-3">
      <div className="max-w-[60%] flex flex-col items-end">
        {isEditing ? (
          <div className="w-full rounded-3xl rounded-tr-lg bg-card border border-border/60 shadow-sm p-3">
            <textarea
              ref={textareaRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isSaving}
              maxLength={10000}
              aria-label="Edit message"
              data-testid="edit-textarea"
              className="w-full resize-none bg-transparent text-sm leading-relaxed outline-none disabled:opacity-60 min-h-[3rem] max-h-[280px]"
            />
            {editError ? (
              <p
                role="alert"
                className="mt-1 text-xs text-destructive"
                data-testid="edit-error"
              >
                {editError}
              </p>
            ) : null}
            <div className="mt-2 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={cancelEdit}
                disabled={isSaving}
                data-testid="edit-cancel"
                className="inline-flex items-center rounded-full px-3 py-1 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void save()}
                disabled={isSaving || !draft.trim()}
                data-testid="edit-save"
                className="inline-flex items-center rounded-full bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSaving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="rounded-3xl rounded-tr-lg bg-primary px-5 py-3.5 text-sm text-primary-foreground leading-relaxed shadow-sm whitespace-pre-wrap">
              {content}
            </div>
            {(() => {
              // P1-3 — the chain navigator appears alongside Edit whenever the
              // user has more than one branch on this turn (i.e. they've edited
              // at least once). It's always visible (not hover-gated) because
              // it's how students discover/recover prior drafts; Edit stays
              // hover-gated per P1-1.
              const hasUserSiblings = (siblingIds?.length ?? 0) > 1;
              const showEdit = canEdit && !!onEdit;
              if (!showEdit && !hasUserSiblings) return null;
              return (
                <div
                  className="mt-1 mr-1 flex items-center gap-1"
                  aria-label="Message actions"
                >
                  {hasUserSiblings && onSelectSibling && siblingIds && (
                    <SiblingNavigator
                      siblingIds={siblingIds}
                      currentId={messageId}
                      onSelect={(targetId) =>
                        void onSelectSibling(messageId, targetId)
                      }
                    />
                  )}
                  {showEdit && (
                    <div
                      className="opacity-0 group-hover/msg:opacity-100 focus-within:opacity-100 transition-opacity"
                    >
                      <button
                        type="button"
                        onClick={openEditor}
                        aria-label="Edit message"
                        data-testid="edit-open"
                        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                        Edit
                      </button>
                    </div>
                  )}
                </div>
              );
            })()}
          </>
        )}
      </div>
      <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center shrink-0 mt-1 border border-border/50">
        <User className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      </div>
    </div>
  );
}

// P2-3 — thinking indicator now reveals the routed agent as soon as the
// first SSE event arrives (carrying `agent_name` before any content
// tokens). Before the first event `agentName` is undefined and we render
// a neutral "Thinking…" so there's no flicker the moment the classifier
// decides. The dot color encodes the agent's category.
function ThinkingDots({ agentName }: { agentName?: string | null }) {
  const { displayName, colorClass } = getAgentLabel(agentName);
  const label = agentName ? `${displayName} is thinking…` : "Thinking…";
  return (
    <div
      className="flex items-center gap-2 py-1"
      aria-label={label}
      role="status"
      aria-live="polite"
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full shrink-0",
          agentName ? colorClass : "bg-muted-foreground/40",
        )}
        aria-hidden="true"
        data-testid="thinking-agent-dot"
      />
      <span className="text-xs text-muted-foreground" data-testid="thinking-label">
        {label}
      </span>
      <span className="flex items-center gap-1 ml-1" aria-hidden="true">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-bounce"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </span>
    </div>
  );
}

function CopyMessageButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    // SSR / unsupported browser guard. Modern HTTPS/localhost has it.
    if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
      console.warn("[CopyMessageButton] navigator.clipboard unavailable; copy skipped");
      return;
    }
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // silently ignore — user will notice no feedback
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => void handleCopy()}
        aria-label={copied ? "Copied" : "Copy message"}
        className={cn(
          "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
          copied
            ? "text-emerald-600 dark:text-emerald-400"
            : "text-muted-foreground hover:bg-muted hover:text-foreground",
        )}
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        {copied ? "Copied" : "Copy"}
      </button>
      <span role="status" aria-live="polite" className="sr-only">
        {copied ? "Copied" : ""}
      </span>
    </>
  );
}

// P3-4 — "Save to notebook" hover action on assistant bubbles. Mirrors the
// CopyMessageButton pattern: self-contained, fires an async callback, shows a
// brief active-state toggle. `isSaved` is true when the parent has already
// bookmarked this message id in the current session.
function BookmarkButton({
  onClick,
  isSaved,
}: {
  onClick: () => void;
  isSaved: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={isSaved ? "Saved to notebook" : "Save to notebook"}
      aria-pressed={isSaved}
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
        isSaved
          ? "text-primary"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {isSaved ? (
        <BookmarkCheck className="h-3.5 w-3.5" />
      ) : (
        <Bookmark className="h-3.5 w-3.5" />
      )}
      {isSaved ? "Saved" : "Save"}
    </button>
  );
}

// P1-2 — "Regenerate" hover action on assistant bubbles. Matches the existing
// hover-action visual style (CopyMessageButton / FeedbackControls). The click
// handler lives in the parent so the regenerate fetch + stream consumption can
// share state with useStream (new variant replaces the current bubble's
// content + sibling list grows by one).
function RegenerateButton({
  onClick,
  isRegenerating,
  disabled,
}: {
  onClick: () => void;
  isRegenerating: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || isRegenerating}
      aria-label={isRegenerating ? "Regenerating response" : "Regenerate response"}
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
        "text-muted-foreground hover:bg-muted hover:text-foreground",
        "disabled:opacity-50 disabled:cursor-not-allowed",
      )}
    >
      <RotateCw
        className={cn("h-3.5 w-3.5", isRegenerating && "animate-spin")}
        aria-hidden="true"
      />
      {isRegenerating ? "Regenerating" : "Regenerate"}
    </button>
  );
}

// P3-1 — "Explain differently" hover action. Shows a 4-option dropdown
// (Simpler / More rigorous / Via analogy / Show code) that calls the
// regenerate route with an explain_style hint.
const EXPLAIN_OPTIONS = [
  { value: "simpler",       label: "Simpler" },
  { value: "more_rigorous", label: "More rigorous" },
  { value: "via_analogy",   label: "Via analogy" },
  { value: "show_code",     label: "Show code" },
] as const;

function ExplainDifferentlyButton({
  onSelect,
  disabled,
}: {
  onSelect: (style: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="Explain differently"
        aria-expanded={open}
        aria-haspopup="menu"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        data-testid="explain-differently-trigger"
        className={cn(
          "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
          "text-muted-foreground hover:bg-muted hover:text-foreground",
          "disabled:opacity-50 disabled:cursor-not-allowed",
        )}
      >
        <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
        Explain differently
      </button>
      {open && (
        <div
          role="menu"
          data-testid="explain-differently-menu"
          className={cn(
            "absolute bottom-full left-0 mb-1 z-50",
            "rounded-lg border border-border bg-popover shadow-md",
            "min-w-[150px] py-1",
          )}
        >
          {EXPLAIN_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              role="menuitem"
              type="button"
              data-testid={`explain-option-${value}`}
              className="w-full text-left px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
              onClick={() => {
                setOpen(false);
                onSelect(value);
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// P1-2 — `< 1 / N >` variant switcher below an assistant bubble that has
// siblings. Hidden when there's only one variant. The caller owns the
// click handlers (they need to fetch the sibling content + mutate the
// hook's message array in place).
function SiblingNavigator({
  siblingIds,
  currentId,
  onSelect,
  disabled,
}: {
  siblingIds: string[];
  currentId: string;
  onSelect: (targetId: string) => void;
  disabled?: boolean;
}) {
  const idx = siblingIds.indexOf(currentId);
  if (idx < 0 || siblingIds.length < 2) return null;
  const atStart = idx === 0;
  const atEnd = idx === siblingIds.length - 1;
  const goPrev = () => {
    if (atStart || disabled) return;
    onSelect(siblingIds[idx - 1]);
  };
  const goNext = () => {
    if (atEnd || disabled) return;
    onSelect(siblingIds[idx + 1]);
  };

  return (
    <div
      role="group"
      aria-label={`Response ${idx + 1} of ${siblingIds.length}`}
      data-testid="sibling-navigator"
      className="inline-flex items-center gap-0.5 rounded-md text-[11px] text-muted-foreground"
    >
      <button
        type="button"
        onClick={goPrev}
        disabled={atStart || disabled}
        aria-label="Previous response"
        className="inline-flex items-center justify-center rounded-md p-1 hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      <span className="tabular-nums px-1 min-w-[38px] text-center">
        {idx + 1} / {siblingIds.length}
      </span>
      <button
        type="button"
        onClick={goNext}
        disabled={atEnd || disabled}
        aria-label="Next response"
        className="inline-flex items-center justify-center rounded-md p-1 hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}

// P2-5 — hover-panel metadata popover. Rendered on the agent-label caption
// above each assistant bubble; shows `model · first / total · in / out tokens`
// so students can reason about latency + cost without leaving the thread.
// All fields are optional: rows that pre-date the feature or hit a stream
// error persist with NULL metadata and render as an em-dash.
function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTokens(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

function MessageMetadataPopover({
  agentName,
  model,
  firstTokenMs,
  totalDurationMs,
  inputTokens,
  outputTokens,
  children,
}: {
  agentName?: string;
  model?: string | null;
  firstTokenMs?: number | null;
  totalDurationMs?: number | null;
  inputTokens?: number | null;
  outputTokens?: number | null;
  children: React.ReactNode;
}) {
  const modelLabel = model ?? "—";
  const firstLabel = formatMs(firstTokenMs);
  const totalLabel = formatMs(totalDurationMs);
  const inLabel = formatTokens(inputTokens);
  const outLabel = formatTokens(outputTokens);
  // Single-line summary used by accessibility tools (aria-label on the
  // trigger) and assertable in tests — matches the tracker's spec format:
  // `model · 123ms first / 2.3s total · 450 in / 890 out tokens`.
  const summary = `${modelLabel} · ${firstLabel} first / ${totalLabel} total · ${inLabel} in / ${outLabel} out tokens`;

  return (
    <span className="relative inline-block group/meta" data-testid="message-metadata">
      <button
        type="button"
        tabIndex={0}
        aria-label={`Message metadata: ${summary}`}
        className="inline-flex items-center gap-1 rounded px-0.5 -mx-0.5 outline-none focus-visible:ring-1 focus-visible:ring-primary/50 cursor-default"
        data-testid="message-metadata-trigger"
      >
        {children}
      </button>
      <span
        role="tooltip"
        data-testid="message-metadata-popover"
        className={cn(
          "pointer-events-none absolute left-0 top-full z-50 mt-1 min-w-[18rem] rounded-lg border border-border/60 bg-popover px-3 py-2 text-[11px] text-popover-foreground shadow-lg",
          "opacity-0 translate-y-0.5 transition-[opacity,transform] duration-150",
          "group-hover/meta:opacity-100 group-hover/meta:translate-y-0",
          "group-focus-within/meta:opacity-100 group-focus-within/meta:translate-y-0",
        )}
      >
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-normal normal-case tracking-normal">
          <dt className="text-muted-foreground">Agent</dt>
          <dd className="font-medium">{agentName ?? "—"}</dd>
          <dt className="text-muted-foreground">Model</dt>
          <dd className="font-mono text-[10px]">{modelLabel}</dd>
          <dt className="text-muted-foreground">First token</dt>
          <dd className="tabular-nums">{firstLabel}</dd>
          <dt className="text-muted-foreground">Total</dt>
          <dd className="tabular-nums">{totalLabel}</dd>
          <dt className="text-muted-foreground">Tokens in</dt>
          <dd className="tabular-nums">{inLabel}</dd>
          <dt className="text-muted-foreground">Tokens out</dt>
          <dd className="tabular-nums">{outLabel}</dd>
        </dl>
      </span>
    </span>
  );
}

// ── P2-4 — routing affordance ────────────────────────────────────
// Renders "Routed to {agent} · {reason} · change" under the agent name.
// Clicking "change" opens a dropdown of all 20 agents grouped by the 5
// categories; picking one dispatches to the parent's `onChange` which
// funnels into the P1-2 regenerate flow with an agent_override payload.
function RoutingAffordance({
  messageId,
  agentName,
  routingReason,
  onChange,
  disabled,
}: {
  messageId: string;
  agentName: string;
  routingReason?: string;
  onChange: (
    messageId: string,
    options: { agentOverride: string },
  ) => Promise<void>;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const resolved = getAgentLabel(agentName);
  const reasonLabel = formatRoutingReason(routingReason);
  const groups = getAgentGroups();

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const onPick = (name: string) => {
    setOpen(false);
    if (name === agentName) return;
    void onChange(messageId, { agentOverride: name });
  };

  return (
    <div
      ref={containerRef}
      data-testid="routing-affordance"
      className="relative ml-1 mb-1.5 text-[11px] leading-4 text-muted-foreground/70"
    >
      <span>Routed to </span>
      <span className="font-medium text-muted-foreground">{resolved.displayName}</span>
      {reasonLabel && (
        <>
          <span aria-hidden="true"> · </span>
          <span className="font-mono">{reasonLabel}</span>
        </>
      )}
      <span aria-hidden="true"> · </span>
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Change routed agent"
        onClick={() => setOpen((v) => !v)}
        className="underline-offset-2 hover:underline focus:underline text-primary/80 hover:text-primary disabled:opacity-50 disabled:cursor-not-allowed"
      >
        change
      </button>
      {open && (
        <div
          role="listbox"
          aria-label="Pick an agent to regenerate under"
          data-testid="routing-override-dropdown"
          className="absolute left-0 top-5 z-20 w-64 max-h-80 overflow-y-auto rounded-xl border bg-popover shadow-xl text-xs"
        >
          {groups.map((group) => (
            <div key={group.category} className="py-1">
              <div className="px-3 pt-1 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {group.label}
              </div>
              {group.agents.map((a) => {
                const selected = a.name === agentName;
                return (
                  <button
                    key={a.name}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    onClick={() => onPick(a.name)}
                    className={cn(
                      "w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-muted",
                      selected && "bg-muted/60 font-medium",
                    )}
                  >
                    <span className="flex-1 truncate">{a.displayName}</span>
                    {selected && <Check className="h-3 w-3 text-primary" aria-hidden="true" />}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// P-Today3 (2026-04-26) — pure trigger. The parent owns modal state +
// the saved-set tracking, mirroring how the bookmark button feeds the
// SaveNoteModal. Removed the inline immediate POST that used to call the
// spaced_repetition extractor — see MakeFlashcardsModal docstring for why.
function FlashcardButton({
  onClick,
  isSaved,
}: {
  onClick: () => void;
  isSaved: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={
        isSaved
          ? "Flashcards already saved from this message"
          : "Make flashcards from this message"
      }
      aria-pressed={isSaved}
      data-testid="flashcard-button"
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
        isSaved
          ? "text-green-600"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {isSaved ? (
        <Check className="h-3.5 w-3.5" aria-hidden="true" />
      ) : (
        <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      {isSaved ? "Saved" : "Flashcards"}
    </button>
  );
}

function AssistantBubble({
  messageId,
  content,
  agentName,
  routingReason,
  isStreaming,
  isLast,
  isThinking,
  myFeedback,
  onSubmitFeedback,
  siblingIds,
  onSelectSibling,
  onRegenerate,
  isRegenerating,
  model,
  firstTokenMs,
  totalDurationMs,
  inputTokens,
  outputTokens,
  onSaveToNotebook,
  isSaved = false,
  onQuizMe,
  onMakeFlashcards,
  flashcardsSaved = false,
  truncated = false,
  dbMessageId,
  onContinue,
}: {
  messageId: string;
  content: string;
  agentName?: string;
  // P2-4 — backend-supplied routing decision rendered under the agent name.
  routingReason?: string;
  isStreaming: boolean;
  isLast: boolean;
  isThinking?: boolean;
  myFeedback?: ChatFeedbackRead | null;
  // P1-5 — parent owns the POST + optimistic state update. Omitted for the
  // live-streaming bubble (its id is a client UUID, not the persisted one),
  // in which case the thumbs are hidden.
  onSubmitFeedback?: (
    messageId: string,
    payload: ChatFeedbackCreate,
  ) => Promise<void>;
  // P1-2 — sibling navigator + regenerate. Both are undefined for the
  // live-streaming bubble (persisted-only actions).
  siblingIds?: string[];
  onSelectSibling?: (messageId: string, targetId: string) => Promise<void>;
  // P2-4/P3-1 — `onRegenerate` accepts optional agentOverride and explainStyle.
  onRegenerate?: (
    messageId: string,
    options?: { agentOverride?: string; explainStyle?: string },
  ) => Promise<void>;
  isRegenerating?: boolean;
  // P2-5 — hover-panel metadata. Populated only for persisted assistant
  // rows; the live-streaming bubble renders without a popover.
  model?: string | null;
  firstTokenMs?: number | null;
  totalDurationMs?: number | null;
  inputTokens?: number | null;
  outputTokens?: number | null;
  // P3-4 — notebook bookmark. `onSaveToNotebook` is omitted for the
  // live-streaming bubble; `isSaved` tracks whether this message id is
  // already in the current session's saved set.
  onSaveToNotebook?: () => void;
  isSaved?: boolean;
  // P3-3 — quiz me button callback. Undefined for live-streaming bubbles.
  onQuizMe?: (messageId: string, content: string) => void;
  // P-Today3 — open MakeFlashcardsModal. Omitted for live-streaming bubbles.
  // `flashcardsSaved` mirrors `isSaved` semantics for the flashcards button.
  onMakeFlashcards?: () => void;
  flashcardsSaved?: boolean;
  // Long-answer continuation. Set when the backend hit its token budget.
  truncated?: boolean;
  // Server-assigned DB message id — needed to reference the row for continuation.
  dbMessageId?: string;
  onContinue?: (dbMessageId: string, assistantMessageId: string) => void;
}) {
  const router = useRouter();
  const modeLabel = MODES.find((m) => m.agentName === agentName)?.label;
  const showActions = !isThinking && !(isStreaming && isLast) && content.length > 0;
  const canRate = showActions && onSubmitFeedback !== undefined;

  // P0-3 — detect a fenced code block so we can surface "Try in Studio"
  const CODE_BLOCK_RE = /```[\s\S]*?```/;
  const hasCodeBlock = CODE_BLOCK_RE.test(content);

  function handleTryInStudio() {
    // Extract first code block content (strip the fences + optional language tag)
    const match = /```(?:\w+)?\n?([\s\S]*?)```/.exec(content);
    const codeContent = match ? match[1] : content;
    const encoded = btoa(unescape(encodeURIComponent(codeContent)));
    router.push(`/studio?code=${encoded}`);
  }
  const canRegenerate = showActions && onRegenerate !== undefined;
  const hasSiblings = (siblingIds?.length ?? 0) > 1;
  // P2-5 — only surface the metadata popover on bubbles with at least one
  // non-null metadata field. Historical rows + live-streaming rows fall
  // through to the plain caption so we don't show a useless "— — —".
  const hasMetadata =
    !isThinking &&
    !(isStreaming && isLast) &&
    (model != null ||
      firstTokenMs != null ||
      totalDurationMs != null ||
      inputTokens != null ||
      outputTokens != null);
  // P2-4 — only show the routing affordance on persisted, fully-rendered
  // bubbles where the user can actually trigger a regenerate. Hidden
  // during streaming / thinking / on the live-streaming placeholder.
  const canShowRouting =
    showActions && canRegenerate && !!agentName && agentName !== "system";

  return (
    <div className="group/msg flex gap-3">
      <div className={cn(
        "h-8 w-8 rounded-full bg-gradient-to-br flex items-center justify-center shrink-0 mt-1 shadow-sm",
        isThinking ? "animate-pulse" : "",
        agentGradient(agentName),
      )}>
        <Bot className="h-4 w-4 text-white" aria-hidden="true" />
      </div>
      <div className="flex-1 min-w-0">
        {agentName && agentName !== "system" && (
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/60 mb-1.5 ml-1">
            {hasMetadata ? (
              <MessageMetadataPopover
                agentName={agentName}
                model={model}
                firstTokenMs={firstTokenMs}
                totalDurationMs={totalDurationMs}
                inputTokens={inputTokens}
                outputTokens={outputTokens}
              >
                {modeLabel ?? agentName.split("_").join(" ")}
              </MessageMetadataPopover>
            ) : (
              modeLabel ?? agentName.split("_").join(" ")
            )}
          </p>
        )}
        <div className="rounded-3xl rounded-tl-lg bg-card border border-border/50 px-5 py-4 shadow-sm">
          {isThinking ? (
            <ThinkingDots agentName={agentName} />
          ) : (
            <MarkdownRenderer content={content} isStreaming={isStreaming && isLast} />
          )}
        </div>
        {truncated && !isStreaming && dbMessageId && onContinue && (
          <div className="mt-2 ml-1 flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground animate-pulse">
              <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
              Continuing…
            </span>
          </div>
        )}
        {showActions && (
          <div
            className="mt-1 ml-1 flex items-center gap-1 opacity-0 group-hover/msg:opacity-100 focus-within:opacity-100 transition-opacity"
            aria-label="Message actions"
          >
            <CopyMessageButton content={content} />
            {onMakeFlashcards && (
              <FlashcardButton
                onClick={onMakeFlashcards}
                isSaved={flashcardsSaved}
              />
            )}
            {onQuizMe && (
              <button
                type="button"
                onClick={() => onQuizMe(messageId, content)}
                aria-label="Quiz me on this message"
                data-testid="quiz-me-button"
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              >
                <ListChecks className="h-3.5 w-3.5" aria-hidden="true" />
                Quiz me
              </button>
            )}
            {canRegenerate && (
              <RegenerateButton
                onClick={() => void onRegenerate(messageId)}
                isRegenerating={!!isRegenerating}
              />
            )}
            {canRegenerate && (
              <ExplainDifferentlyButton
                disabled={!!isRegenerating}
                onSelect={(style) => void onRegenerate(messageId, { explainStyle: style })}
              />
            )}
            {hasSiblings && onSelectSibling && siblingIds && (
              <SiblingNavigator
                siblingIds={siblingIds}
                currentId={messageId}
                onSelect={(targetId) =>
                  void onSelectSibling(messageId, targetId)
                }
                disabled={isRegenerating}
              />
            )}
            {canRate && (
              <FeedbackControls
                messageId={messageId}
                myFeedback={myFeedback}
                onSubmit={onSubmitFeedback}
              />
            )}
            {onSaveToNotebook && (
              <BookmarkButton onClick={onSaveToNotebook} isSaved={isSaved} />
            )}
            {hasCodeBlock && showActions && (
              <button
                type="button"
                onClick={handleTryInStudio}
                aria-label="Try this code in Studio"
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              >
                <Code2 className="h-3.5 w-3.5" aria-hidden="true" />
                Try in Studio
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Mode chip row ────────────────────────────────────────────────
function ModeChips({ active, onChange }: { active: ModeAgent; onChange: (m: ModeAgent) => void }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {MODES.map((mode) => {
        const Icon = mode.icon;
        const isActive = active === mode.agentName;
        return (
          <button
            key={mode.label}
            onClick={() => onChange(mode.agentName)}
            aria-pressed={isActive}
            aria-label={`Switch to ${mode.label} mode`}
            className={cn(
              "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all",
              isActive
                ? "bg-primary text-primary-foreground shadow-sm"
                : "border border-border/60 text-muted-foreground hover:border-primary/40 hover:text-foreground hover:bg-primary/5",
            )}
          >
            <Icon className={cn("h-3.5 w-3.5", isActive ? "text-primary-foreground" : mode.color)} aria-hidden="true" />
            {mode.label}
          </button>
        );
      })}
    </div>
  );
}

// P1-6 — accept list for the native file picker + the paste/drop handlers.
// Keep it in sync with the backend's `ALLOWED_MIME_TYPES` in
// `backend/app/services/attachment_service.py`. Extensions are included for
// macOS Chrome, which sometimes sends `application/octet-stream` for .ipynb
// and relies on the file-extension fallback server-side.
const ATTACHMENT_ACCEPT = "image/png,image/jpeg,.py,.md,.txt,.ipynb";
const KB = 1024;
const MB = KB * 1024;

function formatBytes(n: number): string {
  if (n >= MB) return `${(n / MB).toFixed(1)} MB`;
  if (n >= KB) return `${(n / KB).toFixed(0)} KB`;
  return `${n} B`;
}

// ── Context picker (P1-7) ───────────────────────────────────────
// One-click attach for a submission / lesson / exercise. The popover opens
// on the "+" button, fetches suggestions lazily on first open, and dispatches
// a selected ContextRef to the parent. We dedupe by (kind,id) so a second
// click on the same row is a no-op rather than growing the chip list.
function ContextPickerIcon({ kind }: { kind: ChatContextRef["kind"] }) {
  const Icon =
    kind === "submission" ? FileCode : kind === "lesson" ? BookOpen : Puzzle;
  return <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />;
}

function ContextPickerPopover({
  onSelect,
  selectedRefs,
  onClose,
}: {
  onSelect: (ref: ChatContextRef, label: string) => void;
  selectedRefs: ChatContextRef[];
  onClose: () => void;
}) {
  const [data, setData] = useState<ContextSuggestionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await chatApi.getContextSuggestions();
        if (!alive) return;
        setData(res);
      } catch (err) {
        if (!alive) return;
        setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // Click-outside dismiss.
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [onClose]);

  const isSelected = (kind: ChatContextRef["kind"], id: string): boolean =>
    selectedRefs.some((r) => r.kind === kind && r.id === id);

  return (
    <div
      ref={containerRef}
      role="dialog"
      aria-label="Attach context"
      data-testid="context-picker"
      className="absolute bottom-12 left-0 z-20 w-80 max-h-96 overflow-y-auto rounded-xl border bg-popover shadow-xl text-sm"
    >
      {loading ? (
        <div className="p-4 text-muted-foreground">Loading…</div>
      ) : error ? (
        <div className="p-4 text-destructive">{error}</div>
      ) : data ? (
        <div className="py-2">
          {data.submissions.length > 0 && (
            <>
              <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Recent submissions
              </div>
              {data.submissions.map((s) => {
                const selected = isSelected("submission", s.id);
                return (
                  <button
                    key={`sub-${s.id}`}
                    type="button"
                    disabled={selected}
                    onClick={() =>
                      onSelect(
                        { kind: "submission", id: s.id },
                        s.exercise_title,
                      )
                    }
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ContextPickerIcon kind="submission" />
                    <span className="flex-1 truncate">{s.exercise_title}</span>
                    {selected && <Check className="h-3 w-3 text-primary" aria-hidden="true" />}
                  </button>
                );
              })}
            </>
          )}
          {data.lessons.length > 0 && (
            <>
              <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Current lesson
              </div>
              {data.lessons.map((l) => {
                const selected = isSelected("lesson", l.id);
                return (
                  <button
                    key={`les-${l.id}`}
                    type="button"
                    disabled={selected}
                    onClick={() =>
                      onSelect({ kind: "lesson", id: l.id }, l.title)
                    }
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ContextPickerIcon kind="lesson" />
                    <span className="flex-1 truncate">{l.title}</span>
                    {selected && <Check className="h-3 w-3 text-primary" aria-hidden="true" />}
                  </button>
                );
              })}
            </>
          )}
          {data.exercises.length > 0 && (
            <>
              <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Exercises
              </div>
              {data.exercises.map((x) => {
                const selected = isSelected("exercise", x.id);
                return (
                  <button
                    key={`ex-${x.id}`}
                    type="button"
                    disabled={selected}
                    onClick={() =>
                      onSelect({ kind: "exercise", id: x.id }, x.title)
                    }
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ContextPickerIcon kind="exercise" />
                    <span className="flex-1 truncate">{x.title}</span>
                    {selected && <Check className="h-3 w-3 text-primary" aria-hidden="true" />}
                  </button>
                );
              })}
            </>
          )}
          {data.submissions.length === 0 &&
            data.lessons.length === 0 &&
            data.exercises.length === 0 && (
              <div className="p-4 text-muted-foreground text-center">
                No context available yet.
              </div>
            )}
        </div>
      ) : null}
    </div>
  );
}

// Labeled context ref we carry in local state — server only cares about
// (kind,id) but the chip needs a display label we already paid to fetch.
interface LabeledContextRef extends ChatContextRef {
  label: string;
}

// ── Input bar ────────────────────────────────────────────────────
// P2-8 — slash command definitions. Each entry maps a `/command` to its
// action: mode switch (tutor/code/quiz/career), context picker, export, or
// new chat. The `kind` field drives the handler in InputBar.
const SLASH_COMMANDS = [
  { cmd: "/tutor",   label: "Tutor mode",           kind: "mode",   agentName: "socratic_tutor" },
  { cmd: "/code",    label: "Code Review mode",      kind: "mode",   agentName: "coding_assistant" },
  { cmd: "/quiz",    label: "Quiz Me mode",          kind: "mode",   agentName: "adaptive_quiz" },
  { cmd: "/career",  label: "Career mode",           kind: "mode",   agentName: "career_coach" },
  { cmd: "/attach",  label: "Attach context (@)",    kind: "attach", agentName: null },
  { cmd: "/export",  label: "Export conversation",   kind: "export", agentName: null },
  { cmd: "/new",     label: "New conversation",      kind: "new",    agentName: null },
] as const;

function InputBar({
  value,
  onChange,
  onSend,
  onCancel,
  isStreaming,
  activeMode,
  onModeChange,
  onStartNew,
  canStartNew,
  attachments,
  onUploadFiles,
  onRemoveAttachment,
  uploadError,
  contextRefs,
  onAddContextRef,
  onRemoveContextRef,
  // P2-8 — extra callbacks for keyboard accelerators.
  onArrowUpEmpty,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  // P0-4: while streaming, the send button becomes a Stop button that calls
  // this handler. Parent threads `cancel` from `useStream`.
  onCancel: () => void;
  isStreaming: boolean;
  activeMode: ModeAgent;
  onModeChange: (m: ModeAgent) => void;
  // P2-10 — "Start new conversation" affordance. Clicking opens a confirm
  // dialog (parent-owned) so an accidental click doesn't lose transcript.
  // Disabled when there is nothing to lose (empty transcript).
  onStartNew: () => void;
  canStartNew: boolean;
  // P1-6 — attachments API. `attachments` is the list of already-uploaded
  // pending rows (slim projection from the backend); `onUploadFiles` accepts
  // any `FileList | File[]` from the three entry points (picker / paste /
  // drop); `onRemoveAttachment` drops a single chip.
  attachments: ChatAttachmentRead[];
  onUploadFiles: (files: FileList | File[]) => void;
  onRemoveAttachment: (id: string) => void;
  uploadError: string | null;
  // P1-7 — context-refs API. Chips rendered in a dedicated row above the
  // attachment chips; picker opened via an "@" button next to the paperclip.
  contextRefs: LabeledContextRef[];
  onAddContextRef: (ref: ChatContextRef, label: string) => void;
  onRemoveContextRef: (kind: ChatContextRef["kind"], id: string) => void;
  // P2-8 — fires when ↑ pressed in an empty composer to edit the last user msg.
  onArrowUpEmpty?: () => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  // P1-7 — picker popover visibility. Lazy-mount keeps us from paying the
  // network cost until the student actually clicks the "@" button.
  const [pickerOpen, setPickerOpen] = useState(false);
  // P2-8 — slash-command autocomplete menu state.
  const [slashMenuOpen, setSlashMenuOpen] = useState(false);
  const [slashHighlight, setSlashHighlight] = useState(0);
  // Backend caps `context_refs` at 3 via Pydantic `max_length=3`; mirror
  // here so we never POST a payload that will 422.
  const MAX_CONTEXT_REFS = 3;
  const atContextLimit = contextRefs.length >= MAX_CONTEXT_REFS;

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }, [value]);

  // P2-8 — derive which slash commands are visible based on what the user typed.
  const slashFilter = value.startsWith("/") && !value.includes(" ")
    ? value.toLowerCase()
    : "";
  const slashVisible = slashFilter
    ? SLASH_COMMANDS.filter((c) => c.cmd.startsWith(slashFilter))
    : [];
  // Sync the menu open state to whether there are visible items.
  // We do this inline (not in an effect) so it's synchronous with `value`.
  const shouldMenuBeOpen = slashVisible.length > 0;

  // Execute the selected slash command.
  const executeSlashCommand = (entry: (typeof SLASH_COMMANDS)[number]) => {
    onChange("");
    setSlashMenuOpen(false);
    setSlashHighlight(0);
    if (entry.kind === "mode") {
      onModeChange(entry.agentName as ModeAgent);
    } else if (entry.kind === "attach") {
      setPickerOpen(true);
    } else if (entry.kind === "export") {
      // Export is handled at the page level via the sidebar ⋯ menu; here we
      // just surface a no-op placeholder. The /export command closes the menu
      // so the user knows it was recognised; full plumbing is P1-8 scope.
    } else if (entry.kind === "new") {
      onStartNew();
    }
  };

  // Sync slashMenuOpen whenever the filter changes (open on match, close on no match).
  useEffect(() => {
    if (shouldMenuBeOpen) {
      setSlashMenuOpen(true);
      setSlashHighlight(0);
    } else {
      setSlashMenuOpen(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slashFilter]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // P2-8 — slash menu navigation.
    if (shouldMenuBeOpen || slashMenuOpen) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSlashMenuOpen(true);
        setSlashHighlight((h) => (h + 1) % slashVisible.length);
        return;
      }
      if (e.key === "ArrowUp" && slashMenuOpen) {
        e.preventDefault();
        setSlashHighlight((h) => (h - 1 + slashVisible.length) % slashVisible.length);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setSlashMenuOpen(false);
        return;
      }
      if (e.key === "Enter" && slashMenuOpen && slashVisible.length > 0) {
        e.preventDefault();
        executeSlashCommand(slashVisible[slashHighlight]);
        return;
      }
    }

    // P2-8 — Esc stops stream when streaming (textarea is enabled, so this
    // fires before the window handler in ChatArea).
    if (e.key === "Escape" && isStreaming) {
      e.preventDefault();
      onCancel();
      return;
    }

    // P2-8 — ↑ in empty composer enters edit mode on last user message.
    if (e.key === "ArrowUp" && !value && !isStreaming) {
      e.preventDefault();
      onArrowUpEmpty?.();
      return;
    }

    // DISC-46 — plain Enter sends; Shift+Enter inserts a newline. Matches
    // the prevailing convention across ChatGPT / Claude.ai / Gemini.
    if (e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      if (shouldMenuBeOpen || slashMenuOpen) return; // menu takes priority
      onSend();
    }
  };

  // P1-6 — paste handler. Walks the clipboard items, keeps entries with a
  // .getAsFile() and hands them to the parent uploader. Skips plain text so
  // normal copy/paste of a snippet still lands in the textarea.
  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files: File[] = [];
    for (const item of Array.from(items)) {
      if (item.kind === "file") {
        const f = item.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length > 0) {
      e.preventDefault();
      onUploadFiles(files);
    }
  };

  // P1-6 — drag-drop. preventDefault on dragOver is required for drop to
  // fire; dragEnter/Leave + isDragging drive the outline highlight.
  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer?.files?.length) {
      onUploadFiles(e.dataTransfer.files);
    }
  };

  return (
    <div className="shrink-0 px-4 pb-4 pt-2">
      <div
        className={cn(
          "max-w-5xl mx-auto rounded-3xl border bg-card shadow-lg transition-shadow",
          "focus-within:shadow-xl focus-within:border-primary/40",
          isStreaming ? "border-primary/30" : "border-border/60",
          isDragging && "ring-2 ring-primary/40",
        )}
        onDragOver={(e) => {
          e.preventDefault();
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          // Only flip off when the pointer exits the composer surface. Child
          // enters bubble a dragLeave on the parent; clamping to when the
          // relatedTarget is outside avoids a flicker.
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
            setIsDragging(false);
          }
        }}
        onDrop={handleDrop}
      >
        {/* P1-7 — pending-context chip row. Visually distinct from attachment
            chips (tinted primary background) so the student can tell at a
            glance which rows will be prepended as structured context vs.
            which will ride along as raw files. */}
        {contextRefs.length > 0 && (
          <div
            className="flex flex-wrap gap-2 px-4 pt-3"
            aria-label="Pending context references"
            data-testid="context-chips"
          >
            {contextRefs.map((ref) => (
              <div
                key={`${ref.kind}-${ref.id}`}
                className="flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 pl-2 pr-1 py-1 text-xs"
                data-testid={`context-chip-${ref.kind}`}
              >
                <ContextPickerIcon kind={ref.kind} />
                <span className="max-w-[200px] truncate font-medium">
                  {ref.label}
                </span>
                <span className="text-muted-foreground/70 capitalize">
                  {ref.kind}
                </span>
                <button
                  type="button"
                  onClick={() => onRemoveContextRef(ref.kind, ref.id)}
                  aria-label={`Remove ${ref.label}`}
                  className="h-5 w-5 rounded-full flex items-center justify-center hover:bg-muted"
                >
                  <X className="h-3 w-3" aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
        )}
        {/* P1-6 — pending-attachments chip row. Rendered above the textarea so
            the student always sees what they're about to send. Each chip
            shows an icon (image vs file), filename, size, and a × button. */}
        {attachments.length > 0 && (
          <div
            className="flex flex-wrap gap-2 px-4 pt-3"
            aria-label="Pending attachments"
            data-testid="attachment-chips"
          >
            {attachments.map((att) => {
              const isImage = att.mime_type.startsWith("image/");
              const Icon = isImage ? ImageIcon : FileText;
              return (
                <div
                  key={att.id}
                  className="flex items-center gap-2 rounded-full border border-border/60 bg-muted/40 pl-2 pr-1 py-1 text-xs"
                >
                  <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                  <span className="max-w-[180px] truncate font-medium">
                    {att.filename}
                  </span>
                  <span className="text-muted-foreground/70">
                    {formatBytes(att.size_bytes)}
                  </span>
                  <button
                    type="button"
                    onClick={() => onRemoveAttachment(att.id)}
                    aria-label={`Remove ${att.filename}`}
                    className="h-5 w-5 rounded-full flex items-center justify-center hover:bg-muted"
                  >
                    <X className="h-3 w-3" aria-hidden="true" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
        {uploadError && (
          <p
            className="px-5 pt-2 text-[11px] text-destructive"
            role="alert"
            aria-live="polite"
          >
            {uploadError}
          </p>
        )}
        {/* P2-8 — slash command autocomplete menu. Floats above the textarea,
            anchored to the bottom of the composer. Visible when the user types
            `/` and there are matching commands. Arrow keys navigate; Enter or
            click selects; Esc closes. */}
        <div className="relative">
          {slashMenuOpen && slashVisible.length > 0 && (
            <ul
              role="listbox"
              aria-label="Slash commands"
              data-testid="slash-menu"
              className="absolute bottom-full mb-1 left-0 z-30 w-64 rounded-xl border bg-popover text-popover-foreground shadow-lg py-1 text-sm"
            >
              {slashVisible.map((entry, idx) => (
                <li
                  key={entry.cmd}
                  role="option"
                  aria-selected={idx === slashHighlight}
                  data-testid={`slash-item-${entry.cmd.slice(1)}`}
                  onMouseDown={(e) => {
                    // Use mousedown so the textarea doesn't blur before click.
                    e.preventDefault();
                    executeSlashCommand(entry);
                  }}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2 cursor-pointer",
                    idx === slashHighlight
                      ? "bg-primary/10 text-primary"
                      : "hover:bg-muted",
                  )}
                >
                  <span className="font-mono font-medium text-xs w-20 shrink-0">
                    {entry.cmd}
                  </span>
                  <span className="text-xs text-muted-foreground truncate">
                    {entry.label}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder="Ask your AI coach anything…"
            rows={1}
            disabled={isStreaming}
            aria-label="Message input"
            className="w-full resize-none bg-transparent px-5 pt-4 pb-2 text-sm leading-relaxed outline-none placeholder:text-muted-foreground/50 disabled:opacity-60 max-h-[160px] overflow-y-auto"
          />
        </div>
        <div className="flex items-center justify-between px-4 pb-3 gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isStreaming}
              aria-label="Attach files"
              title="Attach files (PNG/JPEG, .py/.md/.txt/.ipynb — max 4, 10 MB each)"
              className="h-8 w-8 rounded-full flex items-center justify-center text-muted-foreground hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Paperclip className="h-4 w-4" aria-hidden="true" />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ATTACHMENT_ACCEPT}
              className="hidden"
              onChange={(e) => {
                if (e.target.files && e.target.files.length > 0) {
                  onUploadFiles(e.target.files);
                }
                // Reset so selecting the same file twice re-fires onChange.
                e.target.value = "";
              }}
            />
            {/* P1-7 — context picker. Sibling to the paperclip so the two
                attach-affordances live next to each other. The popover
                absolutely-positions upward from this button; its parent div
                is `relative` so `bottom-12 left-0` anchors to the button. */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setPickerOpen((o) => !o)}
                disabled={isStreaming || atContextLimit}
                aria-label="Attach context"
                aria-expanded={pickerOpen}
                aria-haspopup="dialog"
                title={
                  atContextLimit
                    ? `Max ${MAX_CONTEXT_REFS} context items per message`
                    : "Attach submission, lesson, or exercise context"
                }
                data-testid="context-picker-trigger"
                className="h-8 w-8 rounded-full flex items-center justify-center text-muted-foreground hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <AtSign className="h-4 w-4" aria-hidden="true" />
              </button>
              {pickerOpen && (
                <ContextPickerPopover
                  selectedRefs={contextRefs}
                  onClose={() => setPickerOpen(false)}
                  onSelect={(ref, label) => {
                    onAddContextRef(ref, label);
                    setPickerOpen(false);
                  }}
                />
              )}
            </div>
            <ModeChips active={activeMode} onChange={onModeChange} />
            {/* P2-10 — "Start new conversation" affordance. Opens a confirm
                dialog (owned by the page) before clearing messages so an
                accidental click doesn't wipe a long transcript. Hidden when
                there's nothing to start fresh from, which keeps the composer
                clean on a brand-new conversation. */}
            {canStartNew && (
              <button
                type="button"
                onClick={onStartNew}
                disabled={isStreaming}
                aria-label="Start new conversation"
                title="Start new conversation"
                className="h-7 w-7 rounded-full flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="hidden sm:block text-[11px] text-muted-foreground/50">
              {isStreaming ? "Generating…" : "Enter to send · Shift+Enter newline"}
            </span>
            <button
              // P0-4: while streaming, this is a Stop button that cancels the
              // in-flight request. Otherwise it's the Send button. Keeping a
              // single element means layout doesn't shift when the state
              // flips; only the icon + color + handler change.
              onClick={isStreaming ? onCancel : onSend}
              disabled={!isStreaming && !value.trim()}
              aria-label={isStreaming ? "Stop generating" : "Send message"}
              title={isStreaming ? "Stop (Esc)" : undefined}
              className={cn(
                "h-9 w-9 rounded-2xl flex items-center justify-center transition-all shadow-sm",
                "hover:shadow-md active:scale-95",
                isStreaming
                  ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  : "bg-primary text-primary-foreground hover:bg-primary/90",
                "disabled:opacity-30 disabled:cursor-not-allowed",
              )}
            >
              {isStreaming ? (
                // Filled square — the universal "stop" affordance (matches
                // ChatGPT / Claude.ai / Gemini). `fill="currentColor"` makes
                // lucide's outline render as a solid glyph.
                <Square className="h-3.5 w-3.5" fill="currentColor" aria-hidden="true" />
              ) : (
                <ArrowUp className="h-4 w-4" aria-hidden="true" />
              )}
            </button>
          </div>
        </div>
      </div>
      <p className="text-center text-[11px] text-muted-foreground/40 mt-2">
        Powered by Claude · Responses may be inaccurate
      </p>
    </div>
  );
}

// ── Error banner (P0-5) ──────────────────────────────────────────
// Distinct copy, icon, and retry behavior per error kind. For `rate_limit`
// we drive a live countdown off `retryAfterMs` so the Retry button disables
// until the server's window elapses. For `auth`, the action button clears
// the auth store and navigates to /login instead of retrying the request.
function ErrorBanner({ error, isStreaming, onRetry }: {
  error: StreamError;
  isStreaming: boolean;
  onRetry: () => Promise<void>;
}) {
  const router = useRouter();
  // Rate-limit countdown. We render `secondsRemaining` directly; the effect
  // below seeds it from the current error and ticks it down each second.
  // Date.now() lives inside the effect (not render) so the react-compiler
  // purity rule stays happy.
  const [secondsRemaining, setSecondsRemaining] = useState(0);

  useEffect(() => {
    if (error.kind !== "rate_limit") return;
    const deadline = Date.now() + (error.retryAfterMs ?? 30_000);
    const tick = () => {
      const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      setSecondsRemaining(remaining);
    };
    tick(); // seed immediately
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [error]);

  const Icon =
    error.kind === "auth" ? Lock
    : error.kind === "rate_limit" ? Timer
    : AlertTriangle;

  // P2-7 — format the countdown as mm:ss so long windows ("retry in 1m 05s")
  // stay legible. Single-digit seconds get zero-padded so the text doesn't
  // shift width on every tick.
  const mm = Math.floor(secondsRemaining / 60);
  const ss = secondsRemaining % 60;
  const mmss = `${mm}:${ss.toString().padStart(2, "0")}`;

  const copy =
    error.kind === "auth"
      ? "Session expired — please sign in again."
    : error.kind === "rate_limit"
      ? secondsRemaining > 0
        ? `Rate limited — retry in ${mmss}`
        : "Rate limited — you can try again now."
    : error.kind === "server"
      ? error.message
    : "Connection lost — your last message didn\u2019t get a response.";

  const actionLabel = error.kind === "auth" ? "Sign in" : "Retry";
  const actionDisabled =
    error.kind === "auth"
      ? false
      : isStreaming || (error.kind === "rate_limit" && secondsRemaining > 0);

  const handleAction = () => {
    if (error.kind === "auth") {
      clearAuthForReauth();
      router.push("/login");
      return;
    }
    void onRetry();
  };

  return (
    <div className="mx-auto w-full max-w-5xl px-6 pt-3" role="alert">
      <div className="flex items-center justify-between gap-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-200">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 shrink-0" aria-hidden />
          <span>{copy}</span>
        </div>
        <button
          type="button"
          onClick={handleAction}
          disabled={actionDisabled}
          aria-label={actionLabel}
          className="inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-900 transition-colors hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-100 dark:hover:bg-red-900/40"
        >
          {error.kind === "auth" ? (
            <Lock className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          )}
          {actionLabel}
        </button>
      </div>
    </div>
  );
}

// ── Chat area ────────────────────────────────────────────────────
// P0-3: `ChatArea` is remounted via `key={chatKey}` on every conversation
// switch, new-chat, or mode change. `initialMessages` + `initialConversationId`
// seed the hook on mount for pre-existing conversations. Smoother transitions
// (no remount) are P1-1/P1-2 scope.
function ChatArea({
  mode,
  onFirstMessage,
  onConversationId,
  onModeChange,
  onRequestStartNew,
  prefill,
  initialMessages,
  initialConversationId,
  initialInput,
  onInputChange,
}: {
  mode: typeof MODES[number];
  onFirstMessage: (preview: string, agent: string | undefined) => void;
  onConversationId: (id: string) => void;
  onModeChange: (m: ModeAgent) => void;
  // P2-10 — fired when the user clicks the "Start new conversation" button.
  // The page decides whether to show the confirm dialog or fire straight
  // through (empty transcript case).
  onRequestStartNew: () => void;
  prefill?: string;
  initialMessages?: StreamMessage[];
  initialConversationId?: string;
  initialInput?: string;
  onInputChange: (next: string) => void;
}) {
  const {
    messages,
    isStreaming,
    error,
    sendMessage,
    continueMessage,
    retry,
    cancel,
    setMessages,
    conversationId,
    rateLimitRemaining,
  } = useStream({
    agentName: mode.agentName ?? undefined,
    initialMessages,
    conversationId: initialConversationId,
    onConversationId,
    onMessagePersisted: (ephemeralId, dbId) => {
      persistedIdSet.add(dbId);
      // Fire-and-forget: pre-generate 3 quiz versions for every persisted
      // assistant message so Quiz Me is instant on the first click.
      const msg = messages.find(
        (m) => m.id === ephemeralId && m.role === "assistant",
      );
      if (msg) {
        chatApi.triggerQuizPregenerate(dbId, msg.content);
      }
    },
  });

  // P1-5 — POST the rating then patch `myFeedback` on the message in-place.
  // The hook exposes `setMessages` (functional setter) so we don't duplicate
  // the full message array into page-level state. Parent owns the state to
  // keep FeedbackControls pure; catch is swallow-and-log so a transient
  // failure doesn't crash the bubble (the chip stays visually unset, user
  // can retry).
  const handleSubmitFeedback = useCallback(
    async (messageId: string, payload: ChatFeedbackCreate): Promise<void> => {
      try {
        const saved = await chatApi.postFeedback(messageId, payload);
        setMessages((prev) =>
          prev.map((m) => (m.id === messageId ? { ...m, myFeedback: saved } : m)),
        );
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Failed to submit feedback", err);
      }
    },
    [setMessages],
  );

  // P1-1 — server-known ids snapshot. Used by the render map to decide which
  // messages expose the pencil / thumbs / regenerate / sibling-navigator
  // affordances. Seeded at mount from `initialMessages` AND any sibling ids
  // they advertise (regenerated variants aren't in the canonical chain but
  // are still real server rows — see P1-2). The set is mutable: new sibling
  // ids minted by a successful regenerate / sibling-swap get added here so
  // the bubble can flip between them without losing its affordances.
  // Declared ABOVE the edit / regenerate / sibling callbacks so closures
  // capture it without hitting the TDZ when React re-runs the function body.
  const persistedIdSet = useRef<Set<string>>(
    new Set([
      ...(initialMessages ?? []).map((m) => m.id),
      ...(initialMessages ?? []).flatMap((m) => m.siblingIds ?? []),
    ]),
  ).current;

  // P1-1 — edit a persisted user turn.
  //  1) POST /chat/messages/{id}/edit → server forks a new row (P1-3) while
  //     preserving the original turn + soft-deletes every message strictly
  //     after it; the response carries the new row + its sibling chain.
  //  2) Trim local state to every message with `created_at` strictly older
  //     than the edited one (we use array index since hook state is already
  //     chronological).
  //  3) Call sendMessage(new content) so `useStream` appends the new user
  //     bubble + streams a fresh assistant reply — identical to a normal send
  //     from the UI's perspective. The hook keeps the same conversationId so
  //     the backend appends rather than creating a new conversation.
  //  4) Re-hydrate the tail once the stream completes so the new user bubble
  //     carries its `sibling_ids` chain; without this the `< k / N >`
  //     navigator wouldn't render until the next full page load.
  // Throws on failure so the bubble can display the error inline.
  const handleEditUserMessage = useCallback(
    async (messageId: string, nextContent: string): Promise<void> => {
      const editResult = await chatApi.editMessage(messageId, {
        content: nextContent,
      });
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === messageId);
        if (idx < 0) return prev;
        // Drop the edited message and everything after it; sendMessage will
        // append the new user bubble + the streaming assistant reply.
        return prev.slice(0, idx);
      });
      // P1-3 — the edit response carries the freshly-forked user row's id +
      // the full user-side sibling chain. Seed `persistedIdSet` with every id
      // in the chain so the navigator + edit controls stay live after the
      // stream completes.
      persistedIdSet.add(editResult.id);
      for (const sid of editResult.sibling_ids ?? []) {
        persistedIdSet.add(sid);
      }
      // P2-10 — honor the currently-selected mode on edit-regenerate too.
      await sendMessage(nextContent, undefined, mode.agentName);
      // P1-3 — after the stream completes, re-hydrate the tail so the newly
      // minted user bubble carries its `sibling_ids` (= full edit chain).
      // Without this step the navigator wouldn't appear until the next full
      // page load.
      if (conversationId) {
        try {
          const fresh = await chatApi.getConversation(conversationId);
          const siblings = editResult.sibling_ids ?? [];
          const siblingsKey = [...siblings].sort().join(",");
          setMessages((prev) => {
            if (prev.length === 0) return prev;
            return prev.map((m) => {
              if (m.role !== "user") return m;
              const fromServer = fresh.messages.find(
                (fm) => fm.id === m.id && fm.role === "user",
              );
              if (!fromServer) return m;
              const serverSiblings = fromServer.sibling_ids ?? [];
              // Only overwrite when the server advertises the same chain;
              // this keeps earlier untouched turns from being clobbered.
              if (
                [...serverSiblings].sort().join(",") === siblingsKey &&
                serverSiblings.length > 1
              ) {
                for (const sid of serverSiblings) persistedIdSet.add(sid);
                return { ...m, siblingIds: serverSiblings };
              }
              return m;
            });
          });
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn("Edit hydrate failed", err);
        }
      }
    },
    [sendMessage, setMessages, mode.agentName, conversationId, persistedIdSet],
  );

  // P1-2 — regenerate an assistant reply. We stream a fresh variant via
  // `POST /chat/messages/{id}/regenerate` and replace the source bubble's
  // content + id with the new sibling in place. The prior variant stays in
  // the DB (the navigator's < / > flips back to it via `handleSelectSibling`).
  //
  // Because `useStream` owns the top-level `isStreaming` flag used by the
  // composer, we keep this flow decoupled — a local `regeneratingId` gate
  // prevents parallel clicks per-bubble without blocking the user from
  // sending a new turn while the regenerate is in flight (matching ChatGPT's
  // UX). If the backend rejects ownership, the handler logs and returns.
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null);
  const handleRegenerate = useCallback(
    async (
      messageId: string,
      options?: { agentOverride?: string; explainStyle?: string },
    ): Promise<void> => {
      if (regeneratingId !== null) return;
      setRegeneratingId(messageId);
      try {
        const res = await regenerateMessage(messageId, {
          agentOverride: options?.agentOverride,
          explainStyle: options?.explainStyle,
        });
        if (!res.ok) {
          // Surface the backend's detail if present (401/404/400/429/5xx) so
          // the console points at the failure class while the bubble reverts
          // to its pre-click state.
          let detail = `${res.status}`;
          try {
            const body = (await res.json()) as { detail?: string };
            if (body.detail) detail = body.detail;
          } catch {
            /* non-JSON — keep status only */
          }
          // eslint-disable-next-line no-console
          console.error("Regenerate failed", detail);
          return;
        }
        const reader = res.body?.getReader();
        if (!reader) return;
        // Flip the bubble to a thinking state for the duration of the stream.
        setMessages((prev) =>
          prev.map((m) =>
            m.id === messageId
              ? { ...m, content: "", isThinking: true }
              : m,
          ),
        );
        const decoder = new TextDecoder();
        let buffer = "";
        let detectedAgent: string | undefined;
        let newMessageId: string | null = null;
        let accumulated = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith("data: ")) continue;
            const jsonStr = trimmed.slice(6);
            if (jsonStr === "[DONE]") continue;
            try {
              const parsed = JSON.parse(jsonStr) as {
                chunk?: string;
                done?: boolean;
                agent_name?: string;
                regenerated_from?: string;
                error?: string;
              };
              if (parsed.agent_name) {
                detectedAgent = parsed.agent_name;
              }
              if (parsed.chunk !== undefined && parsed.chunk !== "") {
                accumulated += parsed.chunk;
                // Mutate the bubble's content in-place. Keep the old id while
                // streaming; we swap to the server-side id on done below
                // (or on next hydration).
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === messageId
                      ? {
                          ...m,
                          content: accumulated,
                          agentName: detectedAgent ?? m.agentName,
                          isThinking: false,
                        }
                      : m,
                  ),
                );
              }
              if (parsed.done === true) break;
            } catch {
              /* best-effort SSE parse */
            }
          }
        }
        // Fetch the conversation to re-hydrate sibling ids + grab the
        // newly-persisted assistant id. This is cheaper than tracking the
        // id through the SSE protocol and keeps the UI source-of-truth in
        // sync with the server's canonical chain.
        try {
          if (conversationId) {
            const fresh = await chatApi.getConversation(conversationId);
            const newCanonical = fresh.messages
              .filter((m) => m.role === "assistant")
              .find((m) =>
                (m.sibling_ids ?? []).includes(messageId)
                  ? true
                  : false,
              );
            if (newCanonical) {
              newMessageId = newCanonical.id;
              // Track every known sibling id so the bubble keeps its pencil /
              // regenerate / navigator affordances after we swap its id in
              // place. `persistedIdSet.has(msg.id)` is the gate on those
              // controls, and the newly-minted row isn't in the initial seed.
              persistedIdSet.add(newCanonical.id);
              for (const sid of newCanonical.sibling_ids ?? []) {
                persistedIdSet.add(sid);
              }
            }
            setMessages((prev) => {
              // Replace the regenerating bubble (by old id) with the fresh
              // canonical assistant row + its sibling list.
              return prev.map((m) => {
                if (m.id !== messageId) return m;
                const fromServer = fresh.messages.find(
                  (fm) => fm.id === (newMessageId ?? m.id),
                );
                if (!fromServer) {
                  return { ...m, siblingIds: undefined };
                }
                return {
                  ...m,
                  id: fromServer.id,
                  content: fromServer.content,
                  agentName: fromServer.agent_name ?? m.agentName,
                  myFeedback: fromServer.my_feedback ?? undefined,
                  siblingIds:
                    fromServer.sibling_ids && fromServer.sibling_ids.length > 0
                      ? fromServer.sibling_ids
                      : undefined,
                  isThinking: false,
                };
              });
            });
          }
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn("Regenerate hydrate failed", err);
        }
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Regenerate error", err);
      } finally {
        setRegeneratingId(null);
      }
    },
    [regeneratingId, setMessages, conversationId, persistedIdSet],
  );

  // P1-2 — flip the visible assistant bubble to a different sibling.
  // Fetches the target variant via `/messages/{id}` and swaps the bubble's
  // id + content in place. The sibling list itself doesn't change, so the
  // < / > navigator keeps counting correctly.
  const handleSelectSibling = useCallback(
    async (currentMessageId: string, targetId: string): Promise<void> => {
      try {
        const row = await chatApi.getMessage(targetId);
        // Defensive: the target id is always a real server row (the API 404s
        // on anything else), so mark it persisted in case it wasn't in the
        // initial seed or wasn't discovered via a prior regenerate.
        persistedIdSet.add(row.id);
        for (const sid of row.sibling_ids ?? []) {
          persistedIdSet.add(sid);
        }
        setMessages((prev) =>
          prev.map((m) =>
            m.id === currentMessageId
              ? {
                  ...m,
                  id: row.id,
                  content: row.content,
                  agentName: row.agent_name ?? m.agentName,
                  myFeedback: row.my_feedback ?? undefined,
                  siblingIds:
                    row.sibling_ids && row.sibling_ids.length > 0
                      ? row.sibling_ids
                      : m.siblingIds,
                  isThinking: false,
                }
              : m,
          ),
        );
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Failed to load sibling", err);
      }
    },
    [setMessages, persistedIdSet],
  );

  // P3-4 — tracks which message ids have been bookmarked this session.
  const [savedMessageIds, setSavedMessageIds] = useState<Set<string>>(new Set());

  // P-Today2 (2026-04-26) — bookmark now opens the SaveNoteModal instead of
  // firing an immediate POST. The modal handles summarization, edit, and the
  // actual saveToNotebook call; it tells us via `onSaved` so we can mark the
  // message as bookmarked in this session.
  const [savePromptTarget, setSavePromptTarget] = useState<{
    messageId: string;
    content: string;
    userQuestion: string | undefined;
  } | null>(null);

  const handleSaveToNotebook = useCallback(
    (messageId: string, msgContent: string): void => {
      if (!conversationId) return;
      // Find the immediately preceding user turn to give the summarizer
      // (and the title heuristic) better context. Fall back to undefined
      // when the assistant message is somehow first in the list.
      const idx = messages.findIndex((m) => m.id === messageId);
      let userQuestion: string | undefined;
      for (let i = idx - 1; i >= 0; i--) {
        if (messages[i]?.role === "user") {
          userQuestion = messages[i]?.content;
          break;
        }
      }
      setSavePromptTarget({
        messageId,
        content: msgContent,
        userQuestion,
      });
    },
    [conversationId, messages],
  );

  const handleNoteSaved = useCallback(
    (_entryId: string) => {
      const target = savePromptTarget;
      if (target) {
        setSavedMessageIds((prev) => new Set([...prev, target.messageId]));
      }
    },
    [savePromptTarget],
  );

  // P-Today3 — flashcards modal target + per-session saved set.
  const [flashcardTarget, setFlashcardTarget] = useState<{
    messageId: string;
    content: string;
  } | null>(null);
  const [flashcardsSavedIds, setFlashcardsSavedIds] = useState<Set<string>>(
    new Set(),
  );

  const handleMakeFlashcards = useCallback(
    (messageId: string, msgContent: string): void => {
      if (!conversationId) return;
      setFlashcardTarget({ messageId, content: msgContent });
    },
    [conversationId],
  );

  const handleFlashcardsSaved = useCallback(() => {
    const target = flashcardTarget;
    if (target) {
      setFlashcardsSavedIds((prev) => new Set([...prev, target.messageId]));
    }
  }, [flashcardTarget]);

  // P3-3 — quiz panel state. Non-null when the quiz panel is open.
  const [quizPanel, setQuizPanel] = useState<{
    messageId: string;
    questions: QuizQuestion[];
    concepts_covered?: string[];
  } | null>(null);
  const [quizLoading, setQuizLoading] = useState(false);

  const handleQuizMe = useCallback(
    async (messageId: string, content: string): Promise<void> => {
      if (quizLoading) return;
      setQuizLoading(true);
      try {
        // Try cache first — gives instant feel with a brief shimmer.
        // On cache miss (404 or error), fall back to live generation.
        const [cached] = await Promise.all([
          chatApi.getCachedQuiz(messageId),
          // Minimum 1s shimmer so "Generating quiz…" doesn't flash for <100ms
          new Promise<void>((r) => setTimeout(r, 1000)),
        ]);

        const result = cached ?? await chatApi.generateQuiz(messageId, content);

        setQuizPanel({
          messageId,
          questions: result.questions,
          concepts_covered: result.concepts_covered,
        });
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("[chat] quiz generation failed", err);
        toast.error("Could not generate quiz — try again");
      } finally {
        setQuizLoading(false);
      }
    },
    [quizLoading],
  );

  // P2-8 — tracks which user message should be forced into edit mode (↑ shortcut).
  const [forcingEditId, setForcingEditId] = useState<string | null>(null);

  // P2-8 — ↑ in empty composer: find the last persisted user message and open
  // its editor. Mirrors clicking the pencil button.
  const handleArrowUpEmpty = useCallback(() => {
    if (isStreaming) return;
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role === "user" && persistedIdSet.has(m.id)) {
        setForcingEditId(m.id);
        return;
      }
    }
  }, [messages, isStreaming, persistedIdSet]);

  const [input, setInput] = useState<string>(initialInput ?? "");
  // P1-6 — local state for pending (uploaded-but-not-yet-sent) attachments.
  // Each `ChatAttachmentRead` carries the server-assigned id we pass to
  // `sendMessage` via `attachment_ids` on the next turn. `uploadError` shows
  // the backend's 415/413 detail inline under the composer.
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachmentRead[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  // P1-7 — pending context-refs. Backend caps at 3; we enforce at add-time.
  const [pendingContextRefs, setPendingContextRefs] = useState<LabeledContextRef[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const lastReportedLength = useRef(initialMessages?.length ?? 0);
  const prefillApplied = useRef(false);
  const onInputChangeRef = useRef(onInputChange);
  onInputChangeRef.current = onInputChange;

  // P0-3: mirror composer input up to the page so it survives conversation
  // switches (which remount this component). Effect avoids re-rendering the
  // parent on every keystroke synchronously.
  useEffect(() => {
    onInputChangeRef.current(input);
  }, [input]);

  // P2-1 — smart auto-scroll. Only yank to bottom if the user is already
  // there; otherwise show a "Jump to bottom" pill.
  const { isAtBottom, jumpToBottom } = useSmartAutoScroll({
    messages,
    isStreaming,
    containerRef: scrollContainerRef,
    sentinelRef: messagesEndRef,
  });

  // DISC-38 — when routed from a failing submission (?submission_id=...),
  // seed the composer with a concrete prompt so the student can send it or
  // edit first. Only runs once per mount — switching modes remounts this
  // component via `key={chatKey}`, so the prefill stays available until
  // it's been typed/sent.
  useEffect(() => {
    if (prefillApplied.current) return;
    if (!prefill) return;
    if (messages.length > 0) return;
    setInput(prefill);
    prefillApplied.current = true;
  }, [prefill, messages.length]);

  // P0-3: notify the page on the FIRST user turn of a fresh conversation so
  // it can cache preview/agent for the optimistic sidebar insert that
  // happens when `onConversationId` fires from the first SSE event. Skipped
  // for hydrated conversations (which already have server state).
  useEffect(() => {
    if (messages.length > lastReportedLength.current) {
      const last = messages[messages.length - 1];
      if (
        last?.role === "user" &&
        !initialConversationId &&
        (initialMessages?.length ?? 0) === 0 &&
        messages.length === 1
      ) {
        onFirstMessage(last.content.slice(0, 60), mode.agentName ?? undefined);
      }
      lastReportedLength.current = messages.length;
    }
  }, [messages, mode.agentName, onFirstMessage, initialConversationId, initialMessages]);

  // Auto-continue: when the last assistant message is truncated and streaming
  // has just finished, fire continueMessage automatically after a short pause
  // so the student never has to manually type "continue".
  useEffect(() => {
    if (isStreaming) return;
    const last = messages[messages.length - 1];
    if (!last || last.role !== "assistant" || !last.truncated || !last.dbMessageId) return;
    const timer = setTimeout(() => {
      void continueMessage(last.dbMessageId!, last.id);
    }, 800);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStreaming, messages]);

  // P1-6 — attachment handlers. Uploading happens eagerly on drop/paste/pick
  // so the user sees the chip immediately; the server-assigned id goes into
  // `pendingAttachments` and rides along with the next send. On error we
  // surface the backend's detail (415/413 message) under the composer.
  const MAX_ATTACHMENTS_PER_MESSAGE = 4;
  const handleUploadFiles = useCallback(
    async (files: FileList | File[]) => {
      setUploadError(null);
      const incoming = Array.from(files);
      const remaining = Math.max(
        0,
        MAX_ATTACHMENTS_PER_MESSAGE - pendingAttachments.length,
      );
      if (remaining <= 0) {
        setUploadError(
          `Max ${MAX_ATTACHMENTS_PER_MESSAGE} attachments per message.`,
        );
        return;
      }
      const slice = incoming.slice(0, remaining);
      for (const file of slice) {
        try {
          const att = await uploadAttachment(file);
          setPendingAttachments((prev) => [...prev, att]);
        } catch (err) {
          setUploadError(
            err instanceof Error ? err.message : "Upload failed.",
          );
        }
      }
      if (incoming.length > slice.length) {
        setUploadError(
          `Max ${MAX_ATTACHMENTS_PER_MESSAGE} attachments — extras ignored.`,
        );
      }
    },
    [pendingAttachments.length],
  );

  const handleRemoveAttachment = useCallback((id: string) => {
    setPendingAttachments((prev) => prev.filter((a) => a.id !== id));
  }, []);

  // P1-7 — context-refs handlers. Dedupe by (kind,id) so a second click from
  // the picker is a no-op rather than growing the chip row with duplicates.
  const handleAddContextRef = useCallback(
    (ref: ChatContextRef, label: string) => {
      setPendingContextRefs((prev) => {
        if (prev.some((r) => r.kind === ref.kind && r.id === ref.id)) {
          return prev;
        }
        if (prev.length >= 3) return prev;
        return [...prev, { ...ref, label }];
      });
    },
    [],
  );

  const handleRemoveContextRef = useCallback(
    (kind: ChatContextRef["kind"], id: string) => {
      setPendingContextRefs((prev) =>
        prev.filter((r) => !(r.kind === kind && r.id === id)),
      );
    },
    [],
  );

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    // P1-6 — snapshot + clear the chip row before awaiting the stream so the
    // user immediately sees the composer empty out and can start typing the
    // next turn without stale chips.
    const ids = pendingAttachments.map((a) => a.id);
    setPendingAttachments([]);
    setUploadError(null);
    // P1-7 — same deal for context-refs. Strip the `label` (display-only) so
    // the payload matches the backend's `ChatContextRef` schema exactly.
    const refs: ChatContextRef[] = pendingContextRefs.map((r) => ({
      kind: r.kind,
      id: r.id,
    }));
    setPendingContextRefs([]);
    // P2-10 — pass the currently-selected mode as a per-turn override so a
    // mid-conversation mode switch immediately takes effect on the NEXT send
    // without remounting the component or wiping the transcript. `mode` is a
    // fresh prop on every render, so the closure always captures the latest
    // agentName the user picked.
    await sendMessage(
      text,
      ids.length > 0 ? ids : undefined,
      mode.agentName,
      refs.length > 0 ? refs : undefined,
    );
  }, [
    input,
    isStreaming,
    sendMessage,
    pendingAttachments,
    pendingContextRefs,
    mode.agentName,
  ]);

  // P0-4 — Esc cancels the in-flight stream from anywhere on the page.
  // Attached to `window`, not the textarea, because the student may have
  // scrolled the transcript or clicked a sidebar row before they decide to
  // stop. Only active while streaming so Esc doesn't steal focus behavior
  // from other components (e.g. closing menus) at rest.
  useEffect(() => {
    if (!isStreaming) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        cancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isStreaming, cancel]);

  // P2-1 — pill is visible whenever the user is scrolled away from the
  // live edge and there's transcript to return to. We deliberately skip
  // the `isStreaming` gate — the pill is equally useful right after a
  // reply finishes so the student can re-anchor before sending again.
  const showJumpPill = !isAtBottom && messages.length > 0;

  return (
    <div className="relative flex flex-col h-full overflow-hidden">
      <div ref={scrollContainerRef} className="flex-1 overflow-y-auto" aria-live="polite">
        {messages.length === 0 ? (
          <WelcomeScreen mode={mode} onPrompt={setInput} />
        ) : (
          <div className="max-w-5xl mx-auto px-6 py-6 space-y-6">
            {messages.map((msg, i) => {
              const isLast = i === messages.length - 1;
              // P1-1 — a message is "persisted" (has a real server id the
              // edit/feedback endpoints can accept) iff it came in via
              // `initialMessages`. Client-side uuids minted by `useStream`
              // during a live stream aren't known server-side until the
              // conversation gets re-hydrated on a remount, so we block edit
              // on those rows until then.
              const isPersisted = persistedIdSet.has(msg.id);
              const canEdit = isPersisted && !isStreaming;
              return msg.role === "user"
                ? <UserBubble
                    key={msg.id}
                    messageId={msg.id}
                    content={msg.content}
                    canEdit={canEdit}
                    onEdit={handleEditUserMessage}
                    // P1-3 — edited user turns grow a sibling chain. Surface
                    // the `< k / N >` navigator + wire the shared swap
                    // callback so the bubble can flip between branches.
                    siblingIds={msg.siblingIds}
                    onSelectSibling={isPersisted ? handleSelectSibling : undefined}
                    // P2-8 — ↑ shortcut activates edit on the last persisted user msg.
                    forceEdit={forcingEditId === msg.id}
                    onForceEditConsumed={() => setForcingEditId(null)}
                  />
                : <AssistantBubble
                    key={msg.id}
                    messageId={msg.id}
                    content={msg.content}
                    agentName={msg.agentName}
                    isStreaming={isStreaming}
                    isLast={isLast}
                    isThinking={msg.isThinking}
                    myFeedback={msg.myFeedback}
                    onSubmitFeedback={isPersisted ? handleSubmitFeedback : undefined}
                    siblingIds={msg.siblingIds}
                    onSelectSibling={isPersisted ? handleSelectSibling : undefined}
                    onRegenerate={isPersisted ? handleRegenerate : undefined}
                    isRegenerating={regeneratingId === msg.id}
                    // P2-5 — hover-panel metadata (model / latency / tokens).
                    model={msg.model}
                    firstTokenMs={msg.firstTokenMs}
                    totalDurationMs={msg.totalDurationMs}
                    inputTokens={msg.inputTokens}
                    outputTokens={msg.outputTokens}
                    // P3-3 — quiz me. Only available on persisted assistant rows.
                    onQuizMe={isPersisted ? (id, c) => void handleQuizMe(id, c) : undefined}
                    // P3-4 — notebook bookmark.
                    onSaveToNotebook={
                      isPersisted
                        ? () => void handleSaveToNotebook(msg.id, msg.content)
                        : undefined
                    }
                    isSaved={savedMessageIds.has(msg.id)}
                    // P-Today3 — flashcards modal opener.
                    onMakeFlashcards={
                      isPersisted
                        ? () => handleMakeFlashcards(msg.id, msg.content)
                        : undefined
                    }
                    flashcardsSaved={flashcardsSavedIds.has(msg.id)}
                    // Long-answer continuation.
                    truncated={msg.truncated}
                    dbMessageId={msg.dbMessageId}
                    onContinue={
                      msg.truncated && msg.dbMessageId
                        ? (dbId, assistantId) => void continueMessage(dbId, assistantId)
                        : undefined
                    }
                  />;
            })}
            <div ref={messagesEndRef} className="h-4" />
          </div>
        )}
      </div>

      {showJumpPill && (
        <button
          type="button"
          onClick={jumpToBottom}
          aria-label="Jump to bottom"
          className="absolute bottom-28 right-6 z-10 h-9 w-9 rounded-full bg-primary text-primary-foreground shadow-lg flex items-center justify-center hover:opacity-90 transition-opacity"
        >
          <ArrowDown className="h-4 w-4" aria-hidden="true" />
        </button>
      )}

      {error ? (
        <ErrorBanner error={error} isStreaming={isStreaming} onRetry={retry} />
      ) : null}

      {/* P2-7 — compact budget pill. Only when the server has volunteered a
          remaining count AND the user is near the limit, so it doesn't
          distract during normal use. Non-interactive — purely informational. */}
      {rateLimitRemaining != null && rateLimitRemaining < 5 ? (
        <div className="mx-auto w-full max-w-5xl px-6 pt-2" aria-live="polite">
          <span
            data-testid="rate-limit-pill"
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted px-3 py-1 text-xs text-muted-foreground"
          >
            <Timer className="h-3 w-3" aria-hidden />
            {rateLimitRemaining === 1
              ? "1 message left this hour"
              : `${rateLimitRemaining} messages left this hour`}
          </span>
        </div>
      ) : null}

      <InputBar
        value={input}
        onChange={setInput}
        onSend={() => void handleSend()}
        onCancel={cancel}
        isStreaming={isStreaming}
        activeMode={mode.agentName}
        onModeChange={onModeChange}
        onStartNew={onRequestStartNew}
        // P2-10 — only surface the affordance when there's an active
        // conversation to leave behind. Brand-new (empty) chats don't
        // need the button since there's nothing to lose.
        canStartNew={messages.length > 0}
        attachments={pendingAttachments}
        onUploadFiles={(files) => void handleUploadFiles(files)}
        onRemoveAttachment={handleRemoveAttachment}
        uploadError={uploadError}
        contextRefs={pendingContextRefs}
        onAddContextRef={handleAddContextRef}
        onRemoveContextRef={handleRemoveContextRef}
        onArrowUpEmpty={handleArrowUpEmpty}
      />
      {/* P3-3 — quiz panel slide-in from the right */}
      {quizLoading && (
        <div
          className="fixed right-0 top-0 h-full w-96 bg-white shadow-xl z-50 flex items-center justify-center border-l border-border"
          aria-label="Generating quiz…"
          data-testid="quiz-panel-loading"
        >
          <div className="flex flex-col items-center gap-3 text-muted-foreground">
            <RefreshCw className="h-6 w-6 animate-spin" aria-hidden="true" />
            <span className="text-sm">Generating quiz…</span>
          </div>
        </div>
      )}
      {quizPanel && !quizLoading && (
        <QuizPanel
          panel={quizPanel}
          onClose={() => setQuizPanel(null)}
          onUpdatePanel={setQuizPanel}
        />
      )}

      {savePromptTarget && conversationId && (
        <SaveNoteModal
          open={true}
          onOpenChange={(next) => {
            if (!next) setSavePromptTarget(null);
          }}
          messageId={savePromptTarget.messageId}
          conversationId={conversationId}
          content={savePromptTarget.content}
          userQuestion={savePromptTarget.userQuestion}
          onSaved={handleNoteSaved}
        />
      )}

      {flashcardTarget && conversationId && (
        <MakeFlashcardsModal
          open={true}
          onOpenChange={(next) => {
            if (!next) setFlashcardTarget(null);
          }}
          messageId={flashcardTarget.messageId}
          conversationId={conversationId}
          content={flashcardTarget.content}
          onSaved={handleFlashcardsSaved}
        />
      )}

    </div>
  );
}

// ── Quiz panel (P3-3) ────────────────────────────────────────────
// Slide-in panel from the right. Shows 5 MCQ questions with a neuroscience-
// informed flow: select option → pick confidence → reveal answer + explanation.
// Bloom level badges, distractor rationales, and an end-of-quiz summary with
// confidence breakdown are all rendered inline. Positioned to the right of the
// chat area without conflicting with the ChatSidebar on the left.

// Per-question confidence state — purely local to QuizPanel, not stored in API.
type QuizConfidence = "sure" | "think_so" | "guessing";

// Extended local question state layered on top of the API type.
type LocalQuestion = QuizQuestion & {
  // selected_index already in QuizQuestion
  confidence?: QuizConfidence;
};

// Bloom level → display label + Tailwind color classes
const BLOOM_BADGE: Record<string, { label: string; cls: string }> = {
  recall:        { label: "Recall",      cls: "bg-gray-100 text-gray-600" },
  comprehension: { label: "Understand",  cls: "bg-blue-100 text-blue-700" },
  application:   { label: "Apply",       cls: "bg-violet-100 text-violet-700" },
  analysis:      { label: "Analyse",     cls: "bg-orange-100 text-orange-700" },
};

function QuizPanel({
  panel,
  onClose,
  onUpdatePanel,
}: {
  panel: { messageId: string; questions: QuizQuestion[]; concepts_covered?: string[] };
  onClose: () => void;
  onUpdatePanel: (p: { messageId: string; questions: QuizQuestion[]; concepts_covered?: string[] }) => void;
}) {
  const router = useRouter();
  const qc = useQueryClient();
  // Local layer: track pending selection + confidence before reveal
  const [localQuestions, setLocalQuestions] = useState<LocalQuestion[]>(
    () => panel.questions.map((q) => ({ ...q })),
  );
  // Track which question indices are pending-reveal (option chosen, confidence not yet picked)
  const [pendingReveal, setPendingReveal] = useState<Set<number>>(new Set());
  const [flashcardLoading, setFlashcardLoading] = useState(false);
  const [flashcardsDone, setFlashcardsDone] = useState(false);

  const titlePreview = panel.questions[0]?.question?.slice(0, 30) ?? "Quiz";
  const allAnswered = localQuestions.every((q, qi) => q.selected_index !== undefined && !pendingReveal.has(qi));

  // Step 1: student clicks an option — goes into pending-reveal
  const handleSelectOption = (qi: number, oi: number) => {
    const q = localQuestions[qi];
    if (q.selected_index !== undefined && !pendingReveal.has(qi)) return; // already revealed
    setLocalQuestions((prev) =>
      prev.map((lq, i) => (i === qi ? { ...lq, selected_index: oi } : lq)),
    );
    setPendingReveal((prev) => new Set([...prev, qi]));
  };

  // Step 2: student picks confidence → reveal answer
  const handleConfidence = (qi: number, conf: QuizConfidence) => {
    setLocalQuestions((prev) =>
      prev.map((lq, i) => (i === qi ? { ...lq, confidence: conf } : lq)),
    );
    setPendingReveal((prev) => {
      const next = new Set(prev);
      next.delete(qi);
      return next;
    });
    // Sync back to parent so state survives panel re-mount
    const updated = localQuestions.map((lq, i) =>
      i === qi ? { ...lq, confidence: conf } : lq,
    );
    onUpdatePanel({ ...panel, questions: updated });
  };

  // Flashcard button: persist each wrong question directly to SRS review queue
  const handleAddFlashcards = async () => {
    setFlashcardLoading(true);
    try {
      const wrongOnes = localQuestions.filter(
        (q, qi) => q.selected_index !== undefined && !pendingReveal.has(qi) && q.selected_index !== q.correct_index,
      );
      await Promise.all(
        wrongOnes.map((q) => {
          const slug = q.question.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 80).replace(/-+$/g, "");
          const prompt = `${q.question}\n\nAnswer: ${q.options[q.correct_index]}\n\n${q.explanation}`.slice(0, 2000);
          return srsApi.create({
            concept_key: `quiz:${slug}`,
            prompt,
          });
        }),
      );
      setFlashcardsDone(true);
      void qc.invalidateQueries({ queryKey: ["srs", "due"] });
      toast.success(
        `${wrongOnes.length} missed question${wrongOnes.length !== 1 ? "s" : ""} added to review queue`,
        { action: { label: "Review now →", onClick: () => router.push("/today") } },
      );
    } catch {
      toast.error("Could not save flashcards — try again");
    } finally {
      setFlashcardLoading(false);
    }
  };

  // Confidence breakdown for summary
  const summaryStats = (() => {
    const revealed = localQuestions.filter((q, qi) => q.selected_index !== undefined && !pendingReveal.has(qi));
    const correct = revealed.filter((q) => q.selected_index === q.correct_index).length;
    const wrong = revealed.filter((q) => q.selected_index !== q.correct_index).length;
    const sure_correct   = revealed.filter((q) => q.confidence === "sure"     && q.selected_index === q.correct_index).length;
    const sure_wrong     = revealed.filter((q) => q.confidence === "sure"     && q.selected_index !== q.correct_index).length;
    const guess_correct  = revealed.filter((q) => q.confidence === "guessing" && q.selected_index === q.correct_index).length;
    const guess_wrong    = revealed.filter((q) => q.confidence === "guessing" && q.selected_index !== q.correct_index).length;
    return { correct, wrong, sure_correct, sure_wrong, guess_correct, guess_wrong };
  })();

  const revealedCount = localQuestions.filter((q, qi) => q.selected_index !== undefined && !pendingReveal.has(qi)).length;

  return (
    <div
      className="fixed right-0 top-0 h-full w-96 bg-white shadow-xl z-50 flex flex-col border-l border-border overflow-hidden"
      role="dialog"
      aria-modal="true"
      aria-label="Quiz panel"
      data-testid="quiz-panel"
    >
      {/* Header */}
      <div className="flex flex-col border-b border-border bg-card shrink-0">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2 min-w-0">
            <ListChecks className="h-4 w-4 text-primary shrink-0" aria-hidden="true" />
            <span className="text-sm font-semibold truncate">
              Quiz: {titlePreview}…
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close quiz panel"
            className="h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground transition-colors shrink-0"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        {/* Concept chips */}
        {panel.concepts_covered && panel.concepts_covered.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-4 pb-3">
            {panel.concepts_covered.map((concept) => (
              <span
                key={concept}
                className="inline-flex items-center rounded-full bg-primary/10 text-primary px-2 py-0.5 text-[10px] font-medium"
              >
                {concept}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Questions */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
        {localQuestions.map((q, qi) => {
          const isInPending = pendingReveal.has(qi);
          const isRevealed = q.selected_index !== undefined && !isInPending;
          const isCorrect = isRevealed && q.selected_index === q.correct_index;
          const bloomInfo = q.bloom_level ? BLOOM_BADGE[q.bloom_level] : null;
          const isMisconceptionTrap = q.question_type === "misconception_trap";

          return (
            <div key={qi} className="space-y-2">
              {/* Question header badges */}
              <div className="flex flex-wrap items-center gap-1.5 mb-1">
                {bloomInfo && (
                  <span className={cn("inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold", bloomInfo.cls)}>
                    {bloomInfo.label}
                  </span>
                )}
                {isMisconceptionTrap && (
                  <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold bg-amber-100 text-amber-700">
                    ⚠ Misconception trap
                  </span>
                )}
              </div>

              {/* Question text */}
              <p className="text-sm font-medium leading-snug" data-testid={`quiz-question-${qi}`}>
                {qi + 1}. {q.question}
              </p>

              {/* Options */}
              <div className="space-y-1.5">
                {q.options.map((opt, oi) => {
                  const label = String.fromCharCode(65 + oi); // A, B, C, D
                  const isSelected = q.selected_index === oi;
                  const isThisCorrect = oi === q.correct_index;
                  let optClass =
                    "flex items-start gap-2 w-full rounded-lg border px-3 py-2 text-sm text-left transition-colors";
                  if (!isRevealed && !isInPending) {
                    optClass += " border-border hover:border-primary/50 hover:bg-primary/5 cursor-pointer";
                  } else if (isInPending && isSelected) {
                    // Pending: selected but confidence not yet chosen — yellow highlight
                    optClass += " border-yellow-400 bg-yellow-50 text-yellow-900 cursor-default";
                  } else if (isInPending) {
                    optClass += " border-border text-muted-foreground cursor-default";
                  } else if (isRevealed && isThisCorrect) {
                    optClass += " border-green-500 bg-green-50 text-green-800";
                  } else if (isRevealed && isSelected && !isThisCorrect) {
                    optClass += " border-destructive bg-destructive/10 text-destructive";
                  } else {
                    optClass += " border-border text-muted-foreground";
                  }
                  return (
                    <button
                      key={oi}
                      type="button"
                      disabled={isRevealed || (isInPending && !isSelected)}
                      onClick={() => handleSelectOption(qi, oi)}
                      aria-label={`Option ${label}: ${opt}`}
                      data-testid={`quiz-option-${qi}-${oi}`}
                      className={optClass}
                    >
                      <span className="font-semibold shrink-0">{label}.</span>
                      <span>{opt}</span>
                      {isRevealed && isThisCorrect && (
                        <Check className="h-3.5 w-3.5 ml-auto shrink-0 text-green-600" aria-hidden="true" />
                      )}
                    </button>
                  );
                })}
              </div>

              {/* Confidence picker — shown after option selected, before reveal */}
              {isInPending && (
                <div className="pt-1 space-y-1">
                  <p className="text-[11px] text-muted-foreground font-medium">How confident are you?</p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      data-testid="quiz-confidence-sure"
                      onClick={() => handleConfidence(qi, "sure")}
                      className="flex-1 rounded-lg border border-green-300 bg-green-50 px-2 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100 transition-colors"
                    >
                      🎯 I&apos;m sure
                    </button>
                    <button
                      type="button"
                      data-testid="quiz-confidence-think-so"
                      onClick={() => handleConfidence(qi, "think_so")}
                      className="flex-1 rounded-lg border border-blue-300 bg-blue-50 px-2 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors"
                    >
                      🤔 Think so
                    </button>
                    <button
                      type="button"
                      data-testid="quiz-confidence-guessing"
                      onClick={() => handleConfidence(qi, "guessing")}
                      className="flex-1 rounded-lg border border-amber-300 bg-amber-50 px-2 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100 transition-colors"
                    >
                      🎲 Guessing
                    </button>
                  </div>
                </div>
              )}

              {/* Explanation — shown after reveal */}
              {isRevealed && (
                <div
                  className={cn(
                    "rounded-lg px-3 py-2.5 text-xs leading-relaxed space-y-1.5",
                    isCorrect
                      ? "bg-green-50 text-green-800 border border-green-200"
                      : "bg-red-50 text-red-800 border border-red-200",
                  )}
                  data-testid={`quiz-explanation-${qi}`}
                >
                  <p className="font-semibold">{isCorrect ? "✓ Correct!" : "✗ Not quite."}</p>
                  <p>{q.explanation}</p>
                  {/* Distractor rationale for wrong answers */}
                  {!isCorrect && q.distractor_rationales && q.selected_index !== undefined && (
                    <p className="text-[11px] opacity-80 italic border-t border-current/20 pt-1.5 mt-1.5">
                      Why this answer is tempting: {q.distractor_rationales[
                        // Map selected wrong index to distractor index (skip correct_index slot)
                        q.selected_index < q.correct_index ? q.selected_index : q.selected_index - 1
                      ] ?? q.distractor_rationales[0]}
                    </p>
                  )}
                  {/* Bloom level chip at bottom of explanation */}
                  {bloomInfo && (
                    <div className="pt-0.5">
                      <span className={cn("inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold", bloomInfo.cls)}>
                        {bloomInfo.label}
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {/* End-of-quiz summary */}
        {allAnswered && (
          <div
            className="mt-4 rounded-xl border border-border bg-muted/40 p-4 space-y-3"
            data-testid="quiz-summary"
          >
            <div className="border-b border-border pb-2 text-xs font-semibold text-center text-muted-foreground uppercase tracking-wider">
              Your Results
            </div>
            <div className="flex gap-4 justify-center text-sm font-semibold">
              <span className="text-green-700">✓ {summaryStats.correct} correct</span>
              <span className="text-red-600">✗ {summaryStats.wrong} wrong</span>
            </div>
            <div className="space-y-1 text-xs text-muted-foreground">
              <p className="font-medium text-foreground text-[11px] uppercase tracking-wide mb-1">Confidence breakdown</p>
              <p>• Sure + Correct: <span className="font-semibold text-foreground">{summaryStats.sure_correct}</span> <span className="text-green-600">(solid knowledge)</span></p>
              {summaryStats.sure_wrong > 0 && (
                <p>• Sure + Wrong: <span className="font-semibold text-foreground">{summaryStats.sure_wrong}</span> <span className="text-amber-600">⚠ misconception — review this!</span></p>
              )}
              {summaryStats.sure_wrong === 0 && (
                <p>• Sure + Wrong: <span className="font-semibold text-foreground">0</span></p>
              )}
              <p>• Guessing + Correct: <span className="font-semibold text-foreground">{summaryStats.guess_correct}</span> {summaryStats.guess_correct > 0 && <span className="text-blue-600">(lucky — needs reinforcement)</span>}</p>
              <p>• Guessing + Wrong: <span className="font-semibold text-foreground">{summaryStats.guess_wrong}</span></p>
            </div>
            {summaryStats.wrong > 0 && (
              <button
                type="button"
                data-testid="quiz-add-flashcards-btn"
                disabled={flashcardLoading || flashcardsDone}
                onClick={() => void handleAddFlashcards()}
                className={cn(
                  "w-full rounded-lg border px-3 py-2 text-xs font-medium transition-colors",
                  flashcardsDone
                    ? "border-green-300 bg-green-50 text-green-700 cursor-default"
                    : "border-primary/40 bg-primary/5 text-primary hover:bg-primary/10",
                )}
              >
                {flashcardsDone
                  ? "✓ Added to Flashcards"
                  : flashcardLoading
                    ? "Saving…"
                    : `Add ${summaryStats.wrong} missed question${summaryStats.wrong !== 1 ? "s" : ""} to Flashcards →`}
              </button>
            )}
          </div>
        )}
      </div>

      {/* Footer — only while answering */}
      {!allAnswered && (
        <div className="border-t border-border px-4 py-3 shrink-0 bg-card">
          <p className="text-xs text-muted-foreground text-center">
            {revealedCount} / {localQuestions.length} answered
          </p>
        </div>
      )}
    </div>
  );
}

// ── Start-new confirm dialog (P2-10) ─────────────────────────────
// Minimal hand-rolled modal matching the Delete-confirm style elsewhere in
// this file — shadcn's AlertDialog isn't installed, and pulling it in just
// for this one surface would be overkill. Focus lands on Cancel by default
// so an errant Enter keypress doesn't irreversibly blow away the transcript.
// Dialog is fully keyboard-accessible: Esc = cancel, Tab cycles within the
// two buttons, and the backdrop click also cancels.
function ConfirmStartNewDialog({
  open,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  // Focus Cancel when opened + Esc closes. The listener is scoped to `open`
  // so we don't attach global handlers while the dialog is off-screen.
  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="start-new-dialog-title"
    >
      <button
        type="button"
        aria-label="Cancel"
        onClick={onCancel}
        className="absolute inset-0 bg-black/50"
        tabIndex={-1}
      />
      <div className="relative z-10 w-full max-w-sm rounded-xl border bg-card p-5 shadow-2xl">
        <h2
          id="start-new-dialog-title"
          className="text-sm font-semibold"
        >
          Start a new conversation?
        </h2>
        <p className="mt-2 text-xs text-muted-foreground">
          The current chat will move to the sidebar.
        </p>
        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border/60 bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            Start new
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────
export default function ChatPage() {
  return (
    <Suspense fallback={<ChatSkeleton />}>
      <ChatPageInner />
    </Suspense>
  );
}

function ChatPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const submissionId = searchParams.get("submission_id");
  const topic = searchParams.get("topic");
  const urlConvId = searchParams.get("c");

  const [activeMode, setActiveMode] = useState<ModeAgent>(null);
  // P0-3: conversations are server-truth now. Fetched once on mount; updated
  // optimistically when the stream endpoint returns a new conversation_id.
  const [conversations, setConversations] = useState<ConversationListItem[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(true);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [hydratedMessages, setHydratedMessages] = useState<StreamMessage[] | undefined>(undefined);
  const [chatKey, setChatKey] = useState(0);
  const [prefill, setPrefill] = useState<string | undefined>(undefined);
  // P0-3: preserve composer input across conversation switches so a
  // half-typed thought doesn't get wiped when the user clicks a row.
  const [composerInput, setComposerInput] = useState<string>("");
  // P1-8 — sidebar search + archive toggle. `query` drives the input (updated
  // every keystroke); `debouncedQuery` is what we send to the server so we
  // don't thrash /conversations on every character.
  const [query, setQuery] = useState<string>("");
  const [debouncedQuery, setDebouncedQuery] = useState<string>("");
  const [showArchived, setShowArchived] = useState<boolean>(false);
  // P2-6 — mobile slide-in drawer visibility. Only relevant below the
  // `lg` breakpoint; on desktop the sidebar is permanently mounted.
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);
  // P2-10 — "Start new conversation" confirm dialog visibility. Opened from
  // the composer's ⊕ affordance; confirming fires `handleNew` which clears
  // messages, drops `?c=`, and remounts the chat area.
  const [startNewOpen, setStartNewOpen] = useState<boolean>(false);
  const prefillLoadedFor = useRef<string | null>(null);
  const initialConvApplied = useRef(false);
  // P-Tutor3 (2026-04-26) — clicking "+ New" on `/chat?c=ABC` races: state
  // updates clear `activeConvId` synchronously, but `router.replace("/chat")`
  // updates `searchParams` asynchronously. The URL-sync effect would then
  // see `urlConvId="ABC"` + `activeConvId=null` and re-open the conversation
  // we just left. This ref tells the URL-sync effect to ignore one stale
  // urlConvId tick after a manual clear. We unset it once urlConvId actually
  // transitions to null.
  const manualClearPending = useRef(false);
  // Same-tick cache for the first-message preview/agent so we can synthesize
  // a sidebar entry when the server id arrives in the first SSE event.
  const pendingFirstMessageRef = useRef<{ preview: string; agent: string | undefined } | null>(null);

  // DISC-38 — if arrived from a failing exercise submission, fetch the
  // submission, build a tutor-ready prompt, and switch to Tutor mode.
  // P0-3: prefill always starts a fresh conversation.
  useEffect(() => {
    if (!submissionId) return;
    if (prefillLoadedFor.current === submissionId) return;
    prefillLoadedFor.current = submissionId;
    let cancelled = false;
    (async () => {
      try {
        const sub = await exercisesApi.getSubmission(submissionId);
        if (cancelled) return;
        const intro = topic === "exercise_help"
          ? "I just submitted an exercise and it didn't pass. Can you help me understand what went wrong?"
          : "Can you help me with this submission?";
        const feedback = sub.feedback ? `\n\nFeedback I got:\n${sub.feedback}` : "";
        setPrefill(`${intro}${feedback}`);
        setActiveMode("socratic_tutor");
        setActiveConvId(null);
        setHydratedMessages(undefined);
        setChatKey((k) => k + 1);
      } catch {
        setPrefill("I need help with an exercise I just submitted — it didn't pass. Can you walk me through what might have gone wrong?");
        setActiveMode("socratic_tutor");
        setActiveConvId(null);
        setHydratedMessages(undefined);
        setChatKey((k) => k + 1);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [submissionId, topic]);

  // P1-8 — debounce the search input so we only fire one /conversations
  // request ~300ms after the user stops typing.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
    }, 300);
    return () => window.clearTimeout(handle);
  }, [query]);

  // P0-3 / P1-8: fetch the sidebar conversation list. Re-runs when the
  // debounced query or `showArchived` toggle changes so the server does the
  // ILIKE + archived filtering (and the pinned rows stay floated to the top).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await chatApi.listConversations({
          includeArchived: showArchived,
          q: debouncedQuery || undefined,
        });
        if (cancelled) return;
        setConversations(list);
      } catch {
        // Best-effort: empty sidebar on failure. Could surface a toast here
        // but the existing error-banner targets stream turns, not sidebar.
        if (!cancelled) setConversations([]);
      } finally {
        if (!cancelled) setConversationsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery, showArchived]);

  // P0-3: load a conversation's messages + hydrate. Used by sidebar clicks
  // AND the initial-mount `?c=` / last-viewed-id path.
  const openConversation = useCallback(
    async (id: string, opts: { pushUrl?: boolean } = { pushUrl: true }) => {
      try {
        const conv = await chatApi.getConversation(id);
        const msgs = conv.messages
          .map(messageFromServer)
          .filter((m): m is StreamMessage => m !== null);
        setHydratedMessages(msgs);
        setActiveConvId(id);
        writeLastViewedId(id);
        if (conv.agent_name) {
          const match = MODES.find((m) => m.agentName === conv.agent_name);
          setActiveMode(match?.agentName ?? null);
        }
        setChatKey((k) => k + 1);
        if (opts.pushUrl !== false) {
          router.replace(`/chat?c=${id}`);
        }
      } catch {
        // Fall back to a fresh conversation if the server returns 404/403.
        setHydratedMessages(undefined);
        setActiveConvId(null);
        writeLastViewedId(null);
      }
    },
    [router],
  );

  // P0-3: on initial mount, honor `?c=` first, fall back to last-viewed id.
  useEffect(() => {
    if (initialConvApplied.current) return;
    initialConvApplied.current = true;
    const target = urlConvId ?? readLastViewedId();
    if (!target) return;
    void openConversation(target, { pushUrl: !urlConvId });
  }, [urlConvId, openConversation]);

  // P0-3: sync when the URL `?c=` changes via back/forward.
  useEffect(() => {
    if (!initialConvApplied.current) return;
    if (!urlConvId) {
      // The URL has caught up to a manual clear — drop the guard.
      manualClearPending.current = false;
      if (activeConvId !== null) {
        setActiveConvId(null);
        setHydratedMessages(undefined);
        setChatKey((k) => k + 1);
      }
      return;
    }
    // P-Tutor3 — ignore a stale `?c=` tick that lingers after `handleNew`
    // until Next.js commits the `router.replace("/chat")` navigation.
    if (manualClearPending.current) return;
    if (urlConvId === activeConvId) return;
    void openConversation(urlConvId, { pushUrl: false });
  }, [urlConvId, activeConvId, openConversation]);

  const currentMode = MODES.find((m) => m.agentName === activeMode) ?? MODES[0];

  // P2-10 — mode switch stays within the same conversation. The hook receives
  // `agent_name` per-turn via `sendMessage(text, ids, mode.agentName)` so the
  // user's context is preserved across the chip change; the only visible
  // effect is the active-chip highlight and the gradient/label on the next
  // assistant bubble. To start a fresh conversation use the "Start new
  // conversation" button, which routes through `handleNew` with a confirm
  // dialog when there's existing transcript to lose.
  const handleModeChange = (m: ModeAgent) => {
    setActiveMode(m);
  };

  const handleNew = () => {
    // P2-6 — ensure the mobile drawer is dismissed when starting a new
    // conversation (whether triggered from inside the drawer or the
    // mobile header's `+` button).
    setDrawerOpen(false);
    setActiveMode(null);
    setActiveConvId(null);
    setHydratedMessages(undefined);
    setComposerInput("");
    writeLastViewedId(null);
    // P-Tutor3 — block the URL-sync effect from re-opening the old
    // conversation while `searchParams` still holds the stale `?c=` value
    // (Next.js commits the navigation on the next tick, not synchronously).
    manualClearPending.current = true;
    router.replace("/chat");
    setChatKey((k) => k + 1);
  };

  // P2-8 — Cmd+K: start a new chat (mirrors the "New Chat" button).
  // Cmd+/: cycle through MODES array (Auto → Tutor → Code → Career → Quiz → Auto).
  // Both use Ctrl on Windows/Linux.
  const handleNewRef = useRef(handleNew);
  handleNewRef.current = handleNew;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;
      if (e.key === "k" || e.key === "K") {
        e.preventDefault();
        handleNewRef.current();
      } else if (e.key === "/") {
        e.preventDefault();
        setActiveMode((prev) => {
          const idx = MODES.findIndex((m) => m.agentName === prev);
          const nextIdx = (idx + 1) % MODES.length;
          return MODES[nextIdx].agentName;
        });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // P2-10 — open the confirm dialog. ChatArea only surfaces the ⊕ button when
  // it has transcript, so by the time this fires there is genuinely something
  // to lose. Cancel keeps all current state; Confirm inlines the same reset
  // as `handleNew` — duplicating avoids closing over the non-memoized
  // `handleNew`, which would cause the callback identity to churn every
  // render.
  const handleRequestStartNew = useCallback(() => {
    setStartNewOpen(true);
  }, []);
  const handleConfirmStartNew = useCallback(() => {
    setStartNewOpen(false);
    setDrawerOpen(false);
    setActiveMode(null);
    setActiveConvId(null);
    setHydratedMessages(undefined);
    setComposerInput("");
    writeLastViewedId(null);
    // P-Tutor3 — see handleNew for why this guard is needed.
    manualClearPending.current = true;
    router.replace("/chat");
    setChatKey((k) => k + 1);
  }, [router]);
  const handleCancelStartNew = useCallback(() => {
    setStartNewOpen(false);
  }, []);

  const handleSelectConversation = (id: string) => {
    // P2-6 — close the mobile drawer whenever a row is selected. Harmless
    // on desktop since the drawer isn't rendered there.
    setDrawerOpen(false);
    if (id === activeConvId) return;
    void openConversation(id, { pushUrl: true });
  };

  // P0-3: cache preview/agent for the optimistic sidebar insert that
  // happens when `onConversationId` fires from the first SSE event.
  const handleFirstMessage = useCallback(
    (preview: string, agent: string | undefined) => {
      pendingFirstMessageRef.current = {
        preview: preview.trim(),
        agent,
      };
    },
    [],
  );

  const handleConversationId = useCallback(
    (id: string) => {
      setActiveConvId(id);
      writeLastViewedId(id);
      router.replace(`/chat?c=${id}`);
      const pending = pendingFirstMessageRef.current;
      pendingFirstMessageRef.current = null;
      setConversations((prev) => {
        // Dedup by id — callback fires once per stream, defend against
        // React strict-mode double-invoke anyway.
        if (prev.some((c) => c.id === id)) return prev;
        const now = new Date().toISOString();
        const entry: ConversationListItem = {
          id,
          title: pending?.preview || "New conversation",
          agent_name: pending?.agent ?? null,
          updated_at: now,
          archived_at: null,
          pinned_at: null,
          // User turn (persisted pre-stream) + assistant turn (persisted on
          // done) = 2 by the time we see an id.
          message_count: 2,
        };
        return [entry, ...prev];
      });
    },
    [router],
  );

  // P1-8 — inline rename. Patch the list row in-place on success; swallow
  // errors so the menu collapses cleanly (the row stays at the old title).
  const handleRenameConversation = useCallback(
    async (id: string, nextTitle: string): Promise<void> => {
      const trimmed = nextTitle.trim();
      if (!trimmed) return;
      try {
        const updated = await chatApi.renameConversation(id, trimmed);
        setConversations((prev) =>
          prev.map((c) =>
            c.id === id
              ? { ...c, title: updated.title, updated_at: updated.updated_at }
              : c,
          ),
        );
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Failed to rename conversation", err);
      }
    },
    [],
  );

  // P1-8 — pin/unpin. Server stamps `pinned_at` on true, clears on false.
  // We mirror that locally so the sidebar re-sorts without waiting for the
  // next fetch; the ordering matches the server's ORDER BY.
  const handleTogglePinConversation = useCallback(
    async (id: string, nextPinned: boolean): Promise<void> => {
      try {
        const updated = await chatApi.pinConversation(id, nextPinned);
        setConversations((prev) => {
          const next = prev.map((c) =>
            c.id === id
              ? { ...c, pinned_at: updated.pinned_at, updated_at: updated.updated_at }
              : c,
          );
          // Resort locally: pinned rows first (pinned_at DESC), then rest by
          // updated_at DESC. Mirrors the server's ORDER BY.
          return [...next].sort((a, b) => {
            if (a.pinned_at && !b.pinned_at) return -1;
            if (!a.pinned_at && b.pinned_at) return 1;
            if (a.pinned_at && b.pinned_at) {
              return a.pinned_at < b.pinned_at ? 1 : -1;
            }
            return a.updated_at < b.updated_at ? 1 : -1;
          });
        });
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Failed to toggle pin", err);
      }
    },
    [],
  );

  // P1-8 — archive/unarchive. If the current `showArchived` filter would
  // exclude the freshly-archived row, we drop it from local state; otherwise
  // we patch `archived_at` in place so the row styling updates.
  const handleToggleArchiveConversation = useCallback(
    async (id: string, nextArchived: boolean): Promise<void> => {
      try {
        const updated = await chatApi.archiveConversation(id, nextArchived);
        setConversations((prev) => {
          if (nextArchived && !showArchived) {
            return prev.filter((c) => c.id !== id);
          }
          return prev.map((c) =>
            c.id === id
              ? {
                  ...c,
                  archived_at: updated.archived_at,
                  updated_at: updated.updated_at,
                }
              : c,
          );
        });
        // If we archived the currently open conversation, bounce back to the
        // empty chat so the student isn't left staring at a transcript that's
        // no longer in their sidebar.
        if (nextArchived && activeConvId === id && !showArchived) {
          setActiveConvId(null);
          setHydratedMessages(undefined);
          writeLastViewedId(null);
          router.replace("/chat");
          setChatKey((k) => k + 1);
        }
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Failed to toggle archive", err);
      }
    },
    [activeConvId, router, showArchived],
  );

  // P1-8 — soft-delete via server. Remove from local state and, if it was
  // the active conversation, reset the main pane like "New conversation".
  const handleDeleteConversation = useCallback(
    async (id: string): Promise<void> => {
      try {
        await chatApi.deleteConversation(id);
        setConversations((prev) => prev.filter((c) => c.id !== id));
        if (activeConvId === id) {
          setActiveConvId(null);
          setHydratedMessages(undefined);
          writeLastViewedId(null);
          router.replace("/chat");
          setChatKey((k) => k + 1);
        }
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Failed to delete conversation", err);
      }
    },
    [activeConvId, router],
  );

  // P2-6 — shared sidebar props so we can mount `<ChatSidebar />` in both
  // the desktop `<aside>` and the mobile drawer without repeating the wiring.
  const sidebarProps = {
    conversations,
    activeId: activeConvId,
    onSelect: handleSelectConversation,
    onNew: handleNew,
    loading: conversationsLoading,
    query,
    onQueryChange: setQuery,
    showArchived,
    onToggleArchived: setShowArchived,
    onRename: handleRenameConversation,
    onTogglePin: handleTogglePinConversation,
    onToggleArchive: handleToggleArchiveConversation,
    onDelete: handleDeleteConversation,
  };

  // P2-6 — swipe-to-close handlers for the mobile drawer. We only react
  // to mostly-horizontal swipes with a > 60px leftward delta; anything
  // else (vertical scroll, tiny drags) is ignored so normal list scrolling
  // inside the drawer is unaffected.
  const swipeStartRef = useRef<{ x: number; y: number } | null>(null);
  const handleDrawerTouchStart = (e: React.TouchEvent<HTMLElement>) => {
    const t = e.touches[0];
    if (!t) return;
    swipeStartRef.current = { x: t.clientX, y: t.clientY };
  };
  const handleDrawerTouchEnd = (e: React.TouchEvent<HTMLElement>) => {
    const start = swipeStartRef.current;
    swipeStartRef.current = null;
    if (!start) return;
    const t = e.changedTouches[0];
    if (!t) return;
    const dx = t.clientX - start.x;
    const dy = t.clientY - start.y;
    if (dx < -60 && Math.abs(dx) > Math.abs(dy)) {
      setDrawerOpen(false);
    }
  };

  // P-Tutor1 (2026-04-26) — `isEmpty` controls whether TutorScreen shows
  // the editorial opener cards. We're empty when there's no active
  // conversation AND no hydrated history — which matches "fresh thread,
  // nothing typed yet". Once a stream starts, ChatArea owns the messages
  // and the opener row collapses naturally on the next render.
  const tutorIsEmpty =
    activeConvId === null && (!hydratedMessages || hydratedMessages.length === 0);

  // P-Tutor1 — opener click pre-fills the existing composer. ChatArea reads
  // `initialInput` only on mount, so we bump `chatKey` to force a remount
  // and seed the composer with the prompt text. Cheap (the page is empty
  // when opener cards are visible, so there's no streaming state to lose).
  const handleOpenerPrompt = (text: string) => {
    setComposerInput(text);
    setHydratedMessages(undefined);
    setActiveConvId(null);
    setChatKey((k) => k + 1);
  };

  return (
    <>
      <TutorScreen
        conversations={conversations}
        conversationsLoading={conversationsLoading}
        activeConversationId={activeConvId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNew}
        mode={activeMode}
        onModeChange={handleModeChange as (next: string | null) => void}
        isEmpty={tutorIsEmpty}
        onOpenerPrompt={handleOpenerPrompt}
      >
        <ChatArea
          key={chatKey}
          mode={currentMode}
          onFirstMessage={handleFirstMessage}
          onConversationId={handleConversationId}
          onModeChange={handleModeChange}
          onRequestStartNew={handleRequestStartNew}
          prefill={prefill}
          initialMessages={hydratedMessages}
          initialConversationId={activeConvId ?? undefined}
          initialInput={composerInput}
          onInputChange={setComposerInput}
        />
      </TutorScreen>

      {/* P2-10 — confirm dialog for the composer's ⊕ "Start new conversation"
          affordance. Rendered as a sibling so it overlays the editorial
          shell + the transcript regardless of scroll position. */}
      <ConfirmStartNewDialog
        open={startNewOpen}
        onConfirm={handleConfirmStartNew}
        onCancel={handleCancelStartNew}
      />
    </>
  );
}
