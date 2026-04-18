"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { GoalContractForm } from "@/components/features/goal-contract-form";
import { useMyGoal, useUpsertGoal } from "@/lib/hooks/use-goal";
import { useAuthStore } from "@/stores/auth-store";

export default function OnboardingPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { data: existingGoal, isLoading } = useMyGoal();
  const upsert = useUpsertGoal();

  // If user already has a goal, this page becomes an "edit" surface.
  // If they submit, we send them onward to /today (falls back to dashboard for now).
  useEffect(() => {
    // No-op — we let the form handle the submit redirect.
  }, []);

  if (isLoading) {
    return (
      <div
        className="flex min-h-[60vh] items-center justify-center"
        aria-busy="true"
        aria-live="polite"
      >
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const firstName = user?.full_name?.split(" ")[0] ?? "there";

  return (
    <div className="min-h-[calc(100vh-3.5rem)] md:min-h-screen flex flex-col">
      <div className="flex-1 flex items-center justify-center px-6 py-16">
        <div className="w-full max-w-2xl">
          <header className="mb-10 text-center">
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
              Goal Contract · 3 steps · ~60 seconds
            </p>
            <h1 className="mt-3 text-3xl md:text-4xl font-semibold tracking-tight">
              Let&rsquo;s make this real, {firstName}.
            </h1>
            <p className="mt-3 text-sm text-muted-foreground max-w-md mx-auto">
              Learners with a written goal are{" "}
              <span className="text-foreground font-medium">3.2× more likely</span>{" "}
              to finish. Three questions, then we build your path.
            </p>
          </header>

          <GoalContractForm
            defaultValues={
              existingGoal
                ? {
                    motivation: existingGoal.motivation,
                    deadline_months: existingGoal.deadline_months,
                    success_statement: existingGoal.success_statement,
                  }
                : undefined
            }
            onSubmit={async (values) => {
              await upsert.mutateAsync(values);
              router.push("/today");
            }}
            submitLabel={existingGoal ? "Update my goal" : "Lock in my goal"}
          />
        </div>
      </div>
    </div>
  );
}
