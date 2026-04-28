import { Suspense } from "react";
import { PracticeScreen } from "@/components/v8/screens/practice-screen";

export const metadata = {
  title: "Practice · CareerForge",
};

/**
 * Unified Practice surface (P-Practice1).
 *
 * Replaces the old shadcn-style catalog. The new screen is a full v8
 * workspace with a Monaco editor, real run+review against the backend
 * sandbox, and Save-to-Notebook with a free-form student note. Exercises
 * and Capstone share the same code state and only differ in the rail.
 *
 * Deep-links honored:
 *   ?mode=exercises|capstone — opens that mode
 *   ?task=<exercise_id>      — pre-selects an exercise (Exercises mode)
 *   ?lab=A|B|C               — legacy My Path link; resolves to ordinal
 */
export default function PracticePage() {
  return (
    <Suspense fallback={null}>
      <PracticeScreen />
    </Suspense>
  );
}
