"use client";

import { use } from "react";
import { LessonPlayerScreen } from "@/components/v8/screens/lesson-player-screen";

interface Params {
  courseId: string;
}

export default function LearnCoursePage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { courseId } = use(params);
  return <LessonPlayerScreen courseId={courseId} />;
}
