"use client";

import { useQuery } from "@tanstack/react-query";
import {
  chatApi,
  type NotebookEntryOut,
  type NotebookGraduatedFilter,
  type NotebookSummaryResponse,
} from "@/lib/chat-api";
import { useAuthStore } from "@/stores/auth-store";

interface NotebookListOpts {
  source?: string;
  graduated?: NotebookGraduatedFilter;
  tag?: string;
}

export function useNotebookEntries(opts: NotebookListOpts = {}) {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<NotebookEntryOut[]>({
    queryKey: ["notebook", "list", opts],
    queryFn: () => chatApi.listNotebook(opts),
    enabled: isAuthed,
    staleTime: 30_000,
  });
}

export function useNotebookSummary() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<NotebookSummaryResponse>({
    queryKey: ["notebook", "summary"],
    queryFn: () => chatApi.notebookSummary(),
    enabled: isAuthed,
    staleTime: 30_000,
  });
}
