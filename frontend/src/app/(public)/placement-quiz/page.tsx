import type { Metadata } from "next";
import { PlacementQuiz } from "./_quiz";

export const metadata: Metadata = {
  title: "Placement Quiz · Find your fastest path",
  description:
    "5 questions, 4 minutes. Get a personalized track recommendation based on where you are, where you want to go, and how fast you want to get there.",
};

export default function PlacementQuizPage() {
  return <PlacementQuiz />;
}
