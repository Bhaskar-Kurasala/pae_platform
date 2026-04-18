"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

export interface ResumeData {
  id: string;
  title: string;
  summary: string | null;
  skills_snapshot: string[] | null;
  linkedin_blurb: string | null;
}

export interface FitScoreData {
  fit_score: number;
  matched_skills: string[];
  skill_gap: string[];
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

export function useInterviewQuestions(query: string) {
  return useQuery<InterviewQuestionData[]>({
    queryKey: ["career", "interview-questions", query],
    queryFn: () =>
      api.get<InterviewQuestionData[]>(
        `/api/v1/career/interview-questions?q=${encodeURIComponent(query)}`,
      ),
  });
}
