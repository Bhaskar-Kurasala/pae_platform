"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

// ── Types ────────────────────────────────────────────────────────

export type EvidenceKind = "strength" | "gap" | "neutral";

export type NextActionIntent =
  | "skills_gap"
  | "story_gap"
  | "interview_gap"
  | "jd_target_unclear"
  | "ready_but_stalling"
  | "thin_data"
  | "ready_to_apply";

export interface EvidenceChip {
  text: string;
  evidence_id: string;
  kind: EvidenceKind;
  source_url?: string | null;
}

export interface NextAction {
  intent: NextActionIntent;
  route: string;
  label: string;
}

// ── JD Decoder ────────────────────────────────────────────────────

export type CultureSeverity = "info" | "watch" | "warn";

export interface FillerFlag {
  phrase: string;
  meaning: string;
}

export interface CultureSignal {
  pattern: string;
  severity: CultureSeverity;
  note: string;
}

export interface JdAnalysisPayload {
  role: string;
  company: string | null;
  seniority_read: string;
  must_haves: string[];
  wishlist: string[];
  filler_flags: FillerFlag[];
  culture_signals: CultureSignal[];
  wishlist_inflated: boolean;
}

export interface MatchScorePayload {
  score: number | null;
  headline: string;
  evidence: EvidenceChip[];
  next_action: NextAction;
}

export interface DecodeJdResponse {
  jd_analysis_id: string;
  cached: boolean;
  analysis: JdAnalysisPayload;
  match_score: MatchScorePayload;
}

// ── Hooks ─────────────────────────────────────────────────────────

export function useDecodeJd() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { jd_text: string }) =>
      api.post<DecodeJdResponse>("/api/v1/readiness/jd/decode", payload),
    onSuccess: (data) => {
      qc.setQueryData(
        ["jd-analysis", data.jd_analysis_id],
        data.analysis,
      );
    },
  });
}

export function useJdAnalysis(jdHash: string | null) {
  return useQuery({
    queryKey: ["jd-analysis-by-hash", jdHash],
    enabled: !!jdHash,
    queryFn: () =>
      api.get<JdAnalysisPayload>(`/api/v1/readiness/jd/${jdHash}`),
  });
}

// ── Diagnostic ────────────────────────────────────────────────────

export interface SnapshotSummary {
  target_role: string | null;
  lessons_completed: number;
  exercises_submitted: number;
  capstones_shipped: number;
  mocks_taken: number;
  recent_mock_scores: number[];
  peer_review_count: number;
  peer_review_avg_rating: number | null;
  open_weaknesses: string[];
  resume_freshness_days: number | null;
  time_on_task_minutes: number;
  skills_top: string[];
}

export interface StartDiagnosticResponse {
  session_id: string;
  opening_message: string;
  snapshot_summary: SnapshotSummary;
  prior_session_hint: string | null;
}

export interface DiagnosticTurnResponse {
  session_id: string;
  turn: number;
  agent_message: string;
  is_final: boolean;
  invoke_jd_decoder: boolean;
}

export interface VerdictPayload {
  headline: string;
  evidence: EvidenceChip[];
  next_action: NextAction;
}

export interface FinalizeResponse {
  session_id: string;
  verdict: VerdictPayload;
  sycophancy_flags: string[];
}

export interface PastDiagnosis {
  session_id: string;
  started_at: string;
  completed_at: string | null;
  headline: string | null;
  next_action_label: string | null;
  next_action_intent: NextActionIntent | null;
  next_action_clicked_at: string | null;
  next_action_completed_at: string | null;
}

export interface PastDiagnosesResponse {
  items: PastDiagnosis[];
}

const DIAGNOSTIC_BASE = "/api/v1/readiness/diagnostic";

export function useStartDiagnostic() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<StartDiagnosticResponse>(`${DIAGNOSTIC_BASE}/sessions`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["past-diagnoses"] });
    },
  });
}

export function useSubmitDiagnosticTurn(sessionId: string | null) {
  return useMutation({
    mutationFn: (payload: { content: string }) => {
      if (!sessionId) {
        return Promise.reject(new Error("no active diagnostic session"));
      }
      return api.post<DiagnosticTurnResponse>(
        `${DIAGNOSTIC_BASE}/sessions/${sessionId}/turn`,
        payload,
      );
    },
  });
}

export function useFinalizeDiagnostic(sessionId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { closing_note?: string | null }) => {
      if (!sessionId) {
        return Promise.reject(new Error("no active diagnostic session"));
      }
      return api.post<FinalizeResponse>(
        `${DIAGNOSTIC_BASE}/sessions/${sessionId}/finalize`,
        payload,
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["past-diagnoses"] });
    },
  });
}

export function useAbandonDiagnostic() {
  return useMutation({
    mutationFn: (sessionId: string) =>
      api.post<void>(
        `${DIAGNOSTIC_BASE}/sessions/${sessionId}/abandon`,
        {},
      ),
  });
}

export function usePastDiagnoses(enabled: boolean = true) {
  return useQuery({
    queryKey: ["past-diagnoses"],
    enabled,
    queryFn: () =>
      api.get<PastDiagnosesResponse>(`${DIAGNOSTIC_BASE}/sessions`),
  });
}

// ── North-star instrumentation ─────────────────────────────────────

export interface NextActionClickResponse {
  session_id: string;
  clicked_at: string;
}

export interface CompletionCheckResponse {
  session_id: string;
  clicked_at: string | null;
  completed_at: string | null;
  completed_within_window: boolean;
  intent: NextActionIntent | null;
}

export interface NorthStarRateResponse {
  window_days: number;
  sessions_with_verdict: number;
  sessions_clicked: number;
  sessions_completed_within_24h: number;
  click_through_rate: number;
  completion_within_24h_rate: number;
}

export function useRecordNextActionClick() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      api.post<NextActionClickResponse>(
        `${DIAGNOSTIC_BASE}/sessions/${sessionId}/next-action/click`,
        {},
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["past-diagnoses"] });
    },
  });
}

export function useCheckCompletion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      api.post<CompletionCheckResponse>(
        `${DIAGNOSTIC_BASE}/sessions/${sessionId}/check-completion`,
        {},
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["past-diagnoses"] });
    },
  });
}

export function useNorthStarRate(windowDays: number = 14) {
  return useQuery({
    queryKey: ["readiness-north-star", windowDays],
    queryFn: () =>
      api.get<NorthStarRateResponse>(
        `${DIAGNOSTIC_BASE}/north-star?window_days=${windowDays}`,
      ),
  });
}
