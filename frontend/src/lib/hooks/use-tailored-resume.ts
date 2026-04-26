"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

export interface IntakeQuestion {
  id: string;
  label: string;
  kind: "text" | "textarea";
  required: "true" | "false";
}

export interface QuotaState {
  allowed: boolean;
  reason:
    | "first_resume_free"
    | "within_quota"
    | "daily_limit"
    | "monthly_limit";
  remaining_today: number;
  remaining_month: number;
  reset_at: string | null;
}

export interface IntakeStartResponse {
  questions: IntakeQuestion[];
  quota: QuotaState;
  soft_gate: boolean;
}

export interface TailoredResumeBullet {
  text: string;
  evidence_id: string;
  ats_keywords: string[];
}

export interface TailoredResumeContent {
  summary: string;
  bullets: TailoredResumeBullet[];
  skills: string[];
  ats_keywords: string[];
  tailoring_notes?: string[];
}

export interface CoverLetterContent {
  body: string;
  subject_line: string;
}

export interface ValidationResult {
  passed: boolean;
  violations: string[];
  deterministic_failures?: string[];
  llm_failures?: string[];
}

export interface TailoredResumeResult {
  id: string;
  content: TailoredResumeContent;
  cover_letter: CoverLetterContent;
  validation: ValidationResult;
  quota: QuotaState;
  cost_inr: number;
}

export interface IntakeStartRequest {
  jd_text: string;
  jd_id?: string | null;
}

export interface GenerateRequest {
  jd_text: string;
  jd_id?: string | null;
  intake_answers: Record<string, string>;
}

export function useTailoredResumeQuota(enabled = true) {
  return useQuery<{ quota: QuotaState }>({
    queryKey: ["tailored-resume", "quota"],
    queryFn: () =>
      api.get<{ quota: QuotaState }>("/api/v1/tailored-resume/quota"),
    enabled,
  });
}

export function useStartIntake() {
  return useMutation<IntakeStartResponse, Error, IntakeStartRequest>({
    mutationFn: (body) =>
      api.post<IntakeStartResponse>("/api/v1/tailored-resume/intake", body),
  });
}

export function useGenerateTailoredResume() {
  const qc = useQueryClient();
  return useMutation<TailoredResumeResult, Error, GenerateRequest>({
    mutationFn: (body) =>
      api.post<TailoredResumeResult>(
        "/api/v1/tailored-resume/generate",
        body,
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tailored-resume", "quota"] });
    },
  });
}

export function tailoredResumePdfUrl(id: string): string {
  return `/api/v1/tailored-resume/${id}/pdf`;
}
