import { redirect } from "next/navigation";

/**
 * P-Practice1: /exercises is now a permanent redirect to the unified
 * /practice surface. The Exercises mode in Practice carries the same
 * catalog rail plus the Monaco editor + senior review + save flow.
 */
export default function ExercisesRedirect() {
  redirect("/practice?mode=exercises");
}
