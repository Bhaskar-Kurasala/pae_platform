"use client";

/**
 * F8 — In-app messaging hooks.
 *
 * Two consumer surfaces:
 *   - Student side: useUnreadMessages (banner poller), useMyThreads,
 *     useMyThread(threadId), useReplyToThread(threadId).
 *   - Admin side: useAdminThreadsForStudent(studentId) + useSendAdminMessage.
 *
 * The student-facing /messages route is intentionally minimal in v1
 * (banner + reply UI on per-thread page); F8.1 follow-up adds a
 * proper inbox at /messages.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api-client";

// ── Shared types ───────────────────────────────────────────────────

export interface Message {
  id: string;
  thread_id: string;
  student_id: string;
  sender_role: "admin" | "student";
  sender_id: string | null;
  body: string;
  read_at: string | null;
  created_at: string;
}

export interface ThreadSummary {
  thread_id: string;
  last_message_preview: string;
  last_message_at: string;
  last_sender_role: "admin" | "student";
  unread_count: number;
}

interface UnreadCount {
  unread: number;
}

// ── Student side ───────────────────────────────────────────────────

export function useUnreadMessages() {
  return useQuery<UnreadCount>({
    queryKey: ["messages", "unread"],
    queryFn: () => api.get<UnreadCount>("/api/v1/students/me/messages/unread-count"),
    refetchInterval: 60_000,
    staleTime: 30_000,
    // Background refetches that fail shouldn't toast — banner is
    // best-effort.
    meta: { skipErrorToast: true },
  });
}

export function useMyThreads() {
  return useQuery<ThreadSummary[]>({
    queryKey: ["messages", "my-threads"],
    queryFn: () => api.get<ThreadSummary[]>("/api/v1/students/me/messages"),
    staleTime: 30_000,
  });
}

export function useMyThread(threadId: string | null | undefined) {
  return useQuery<Message[]>({
    queryKey: ["messages", "thread", threadId],
    queryFn: () =>
      api.get<Message[]>(`/api/v1/students/me/messages/${threadId}`),
    enabled: !!threadId,
    staleTime: 10_000,
  });
}

export function useReplyToThread(threadId: string | null | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: string) =>
      api.post<Message>("/api/v1/students/me/messages", {
        thread_id: threadId,
        body,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["messages", "thread", threadId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["messages", "my-threads"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["messages", "unread"],
      });
    },
  });
}

export function useMarkThreadRead(threadId: string | null | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<void>(
        `/api/v1/students/me/messages/${threadId}/read`,
        {},
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["messages", "unread"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["messages", "my-threads"],
      });
    },
  });
}

// ── Admin side ─────────────────────────────────────────────────────

export function useAdminMessagesForStudent(
  studentId: string | null | undefined,
) {
  return useQuery<Message[]>({
    queryKey: ["admin", "student-messages", studentId],
    queryFn: () =>
      api.get<Message[]>(`/api/v1/admin/students/${studentId}/messages`),
    enabled: !!studentId,
    staleTime: 15_000,
  });
}

export function useSendAdminMessage(studentId: string | null | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: { body: string; thread_id?: string }) =>
      api.post<Message>(`/api/v1/admin/students/${studentId}/messages`, {
        thread_id: vars.thread_id,
        body: vars.body,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["admin", "student-messages", studentId],
      });
    },
  });
}
