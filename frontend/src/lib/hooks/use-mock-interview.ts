"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

// ── Types ────────────────────────────────────────────────────────

export type MockMode =
  | "behavioral"
  | "technical_conceptual"
  | "live_coding"
  | "system_design";

export type MockLevel = "junior" | "mid" | "senior";

export interface MockQuestion {
  id: string;
  text: string;
  mode: MockMode;
  difficulty: number;
  source: string;
  position: number;
}

export interface RubricCriterion {
  name: string;
  score: number;
  rationale: string;
}

export interface AnswerEvaluation {
  criteria: RubricCriterion[];
  overall: number;
  confidence: number;
  would_pass: boolean;
  feedback: string;
  needs_human_review: boolean;
}

export interface StartMockResponse {
  session_id: string;
  mode: MockMode;
  target_role: string;
  level: MockLevel;
  voice_enabled: boolean;
  first_question: MockQuestion;
  memory_recall: string | null;
}

export interface SubmitAnswerResponse {
  answer_id: string;
  evaluation: AnswerEvaluation;
  next_question: MockQuestion | null;
  interviewer_reaction: string | null;
  cost_inr_so_far: number;
  cost_cap_exceeded: boolean;
}

export interface MockTranscriptTurn {
  role: "interviewer" | "candidate";
  text: string;
  at: string;
  audio_ref: string | null;
}

export interface PatternInsights {
  filler_word_rate: number;
  avg_time_to_first_word_ms: number | null;
  avg_words_per_answer: number;
  evasion_count: number;
  confidence_language_score: number;
}

export interface NextAction {
  label: string;
  detail: string;
  target_url: string | null;
}

export interface MockSessionReport {
  session_id: string;
  headline: string;
  verdict: string;
  rubric_summary: Record<string, number>;
  patterns: PatternInsights;
  strengths: string[];
  weaknesses: string[];
  next_action: NextAction;
  analyst_confidence: number;
  needs_human_review: boolean;
  transcript: MockTranscriptTurn[];
  total_cost_inr: number;
  share_token: string | null;
}

export interface CompleteSessionResponse {
  session_id: string;
  status: string;
  report: MockSessionReport;
}

export interface MockSessionListItem {
  id: string;
  mode: string;
  target_role: string | null;
  status: string;
  overall_score: number | null;
  total_cost_inr: number;
  created_at: string;
}

export interface ShareResponse {
  share_token: string;
  public_url: string;
}

// ── Hooks ────────────────────────────────────────────────────────

export interface StartMockPayload {
  mode: MockMode;
  target_role: string;
  level: MockLevel;
  jd_text?: string;
  voice_enabled: boolean;
}

export function useStartMockSession() {
  const qc = useQueryClient();
  return useMutation<StartMockResponse, Error, StartMockPayload>({
    mutationFn: (payload) =>
      api.post<StartMockResponse>("/api/v1/mock/sessions/start", payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["mock-sessions"] });
    },
  });
}

export interface SubmitAnswerPayload {
  session_id: string;
  question_id: string;
  text: string;
  audio_ref?: string;
  latency_ms?: number;
  time_to_first_word_ms?: number;
}

export function useSubmitMockAnswer() {
  return useMutation<SubmitAnswerResponse, Error, SubmitAnswerPayload>({
    mutationFn: ({ session_id, ...payload }) =>
      api.post<SubmitAnswerResponse>(
        `/api/v1/mock/sessions/${session_id}/answer`,
        payload,
      ),
  });
}

export function useCompleteMockSession() {
  const qc = useQueryClient();
  return useMutation<CompleteSessionResponse, Error, string>({
    mutationFn: (sessionId) =>
      api.post<CompleteSessionResponse>(
        `/api/v1/mock/sessions/${sessionId}/complete`,
        {},
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["mock-sessions"] });
    },
  });
}

export function useMockReport(sessionId: string | null) {
  return useQuery<MockSessionReport>({
    queryKey: ["mock-report", sessionId],
    queryFn: () =>
      api.get<MockSessionReport>(
        `/api/v1/mock/sessions/${sessionId}/report`,
      ),
    enabled: Boolean(sessionId),
  });
}

export function useMyMockSessions() {
  return useQuery<MockSessionListItem[]>({
    queryKey: ["mock-sessions"],
    queryFn: () => api.get<MockSessionListItem[]>("/api/v1/mock/sessions"),
  });
}

export function useShareMockSession() {
  return useMutation<ShareResponse, Error, string>({
    mutationFn: (sessionId) =>
      api.post<ShareResponse>(
        `/api/v1/mock/sessions/${sessionId}/share`,
        {},
      ),
  });
}

export function usePublicMockReport(token: string | null) {
  return useQuery<MockSessionReport>({
    queryKey: ["mock-public-report", token],
    queryFn: () =>
      api.get<MockSessionReport>(`/api/v1/mock/public-reports/${token}`),
    enabled: Boolean(token),
  });
}
