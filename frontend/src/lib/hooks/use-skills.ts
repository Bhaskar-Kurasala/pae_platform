"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  skillsApi,
  type SkillGraph,
  type SkillPath,
  type UserSkillState,
} from "@/lib/api-client";

export function useSkillGraph() {
  return useQuery<SkillGraph>({
    queryKey: ["skills", "graph"],
    queryFn: () => skillsApi.graph(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useMySkillStates() {
  return useQuery<UserSkillState[]>({
    queryKey: ["skills", "mine"],
    queryFn: () => skillsApi.mine(),
  });
}

export function useSkillPath() {
  return useQuery<SkillPath>({
    queryKey: ["skills", "path"],
    queryFn: () => skillsApi.path(),
    staleTime: 60 * 1000,
  });
}

export function useTouchSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (skillId: string) => skillsApi.touch(skillId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["skills", "mine"] });
    },
  });
}
