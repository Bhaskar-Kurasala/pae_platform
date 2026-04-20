"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

export interface ResumeBullet {
  text: string;
  evidence_id: string;
  ats_keywords: string[];
}

export interface ResumeData {
  id: string;
  title: string;
  summary: string | null;
  bullets: ResumeBullet[];
  skills_snapshot: any[] | null;
  linkedin_blurb: string | null;
  ats_keywords: string[];
  verdict: "strong_fit" | "good_fit" | "needs_work" | null;
}

export interface FitVerdict {
  verdict: "apply" | "skill_up" | "skip";
  verdict_reason: string;
  fit_score: number;
  buckets: {
    proven: string[];
    unproven: string[];
    missing: string[];
  };
  weeks_to_close: number;
  top_3_actions: string[];
}

export interface FitScoreData {
  fit_score: number;
  matched_skills: string[];
  skill_gap: string[];
  verdict: FitVerdict | null;
}

export interface JdLibraryItem {
  id: string;
  title: string;
  company: string | null;
  last_fit_score: number | null;
  verdict: "apply" | "skill_up" | "skip" | null;
  created_at: string;
}

export interface LearningPlanData {
  plan: string;
  skill_gap: string[];
}

export interface InterviewQuestionData {
  id: string;
  question: string;
  answer_hint: string | null;
  difficulty: string;
  category: string;
  skill_tags: string[] | null;
}

export interface JdBody {
  jd_text: string;
  jd_title: string;
}

export function useMyResume() {
  return useQuery<ResumeData>({
    queryKey: ["career", "resume"],
    queryFn: () => api.get<ResumeData>("/api/v1/career/resume"),
  });
}

export function useRegenerateResume() {
  const qc = useQueryClient();
  return useMutation<ResumeData, Error, boolean>({
    mutationFn: (force: boolean) =>
      api.post<ResumeData>("/api/v1/career/resume/regenerate", { force }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["career", "resume"] });
    },
  });
}

export function useFitScore() {
  return useMutation<FitScoreData, Error, JdBody>({
    mutationFn: (body: JdBody) =>
      api.post<FitScoreData>("/api/v1/career/fit-score", body),
  });
}

export function useLearningPlan() {
  return useMutation<LearningPlanData, Error, JdBody>({
    mutationFn: (body: JdBody) =>
      api.post<LearningPlanData>("/api/v1/career/learning-plan", body),
  });
}

export function useSaveJd() {
  const qc = useQueryClient();
  return useMutation<JdLibraryItem, Error, { title: string; company?: string; jd_text: string }>({
    mutationFn: (data) =>
      api.post<JdLibraryItem>("/api/v1/career/jd-library", data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["jd-library"] });
    },
  });
}

export function useJdLibrary() {
  return useQuery<JdLibraryItem[]>({
    queryKey: ["jd-library"],
    queryFn: () => api.get<JdLibraryItem[]>("/api/v1/career/jd-library"),
  });
}

export function useDeleteJd() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id) => api.del(`/api/v1/career/jd-library/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["jd-library"] });
    },
  });
}

export function useInterviewQuestions(query: string) {
  return useQuery<InterviewQuestionData[]>({
    queryKey: ["career", "interview-questions", query],
    queryFn: () =>
      api.get<InterviewQuestionData[]>(
        `/api/v1/career/interview-questions?q=${encodeURIComponent(query)}`,
      ),
  });
}
