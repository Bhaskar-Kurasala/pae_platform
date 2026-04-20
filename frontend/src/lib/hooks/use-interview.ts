"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

// ── Types ────────────────────────────────────────────────────────

export type InterviewMode = "behavioral" | "technical" | "system_design";

export interface SessionStartResponse {
  id: string;
  mode: InterviewMode;
  status: string;
  first_question: string;
  overall_score: number | null;
}

export interface RubricScores {
  clarity: number;
  structure: number;
  depth: number;
  evidence: number;
  confidence_language: number;
}

export interface AnswerResponse {
  scores: RubricScores;
  overall: number;
  feedback: string;
  next_question: string | null;
  tip: string;
}

export interface SessionSummary {
  id: string;
  mode: InterviewMode;
  status: string;
  overall_score: number | null;
  created_at: string;
}

export interface SessionCompleteResponse {
  overall_score: number;
}

export interface Story {
  id: string;
  title: string;
  situation: string;
  task: string;
  action: string;
  result: string;
  tags: string[];
  created_at?: string;
}

export interface StoryInput {
  title: string;
  situation: string;
  task: string;
  action: string;
  result: string;
  tags: string[];
}

// ── Interview Session Hooks ──────────────────────────────────────

export function useStartSession() {
  return useMutation<SessionStartResponse, Error, { mode: InterviewMode; topic?: string }>({
    mutationFn: (data) =>
      api.post<SessionStartResponse>("/api/v1/interview/sessions/start", data),
  });
}

export function useSubmitAnswer() {
  return useMutation<
    AnswerResponse,
    Error,
    { session_id: string; question: string; answer: string }
  >({
    mutationFn: (data) =>
      api.post<AnswerResponse>("/api/v1/interview/sessions/answer", data),
  });
}

export function useCompleteSession() {
  const qc = useQueryClient();
  return useMutation<SessionCompleteResponse, Error, string>({
    mutationFn: (sessionId) =>
      api.post<SessionCompleteResponse>(
        `/api/v1/interview/sessions/${sessionId}/complete`,
        {},
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["interview-sessions"] });
    },
  });
}

export function useInterviewSessions() {
  return useQuery<SessionSummary[]>({
    queryKey: ["interview-sessions"],
    queryFn: () => api.get<SessionSummary[]>("/api/v1/interview/sessions"),
  });
}

// ── Story Bank Hooks ─────────────────────────────────────────────

export function useStories() {
  return useQuery<Story[]>({
    queryKey: ["stories"],
    queryFn: () => api.get<Story[]>("/api/v1/interview/stories"),
  });
}

export function useCreateStory() {
  const qc = useQueryClient();
  return useMutation<Story, Error, StoryInput>({
    mutationFn: (data) => api.post<Story>("/api/v1/interview/stories", data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["stories"] });
    },
  });
}

export function useDeleteStory() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id) => api.del(`/api/v1/interview/stories/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["stories"] });
    },
  });
}
