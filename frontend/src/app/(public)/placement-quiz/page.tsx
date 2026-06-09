"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";
import { PlacementQuiz } from "./_quiz";

export default function PlacementQuizPage() {
  const router = useRouter();
  const { isAuthenticated, _hasHydrated } = useAuthStore();

  useEffect(() => {
    if (_hasHydrated && isAuthenticated) {
      router.replace("/quiz");
    }
  }, [isAuthenticated, _hasHydrated, router]);

  // While hydrating or if logged in (redirect pending), show nothing
  if (!_hasHydrated || isAuthenticated) return null;

  return <PlacementQuiz />;
}
