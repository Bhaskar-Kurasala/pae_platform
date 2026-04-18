"use client";

import { use, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api-client";
import { toast } from "@/lib/toast";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function CourseEditPage({ params }: PageProps) {
  const { id } = use(params);
  const [courseJson, setCourseJson] = useState("{}");
  const [rubricJson, setRubricJson] = useState("{}");
  const [savingCourse, setSavingCourse] = useState(false);
  const [savingRubric, setSavingRubric] = useState(false);
  const [rubricExerciseId, setRubricExerciseId] = useState("");

  const saveMetadata = async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(courseJson);
    } catch {
      toast.error("Invalid JSON — please fix before saving.");
      return;
    }
    setSavingCourse(true);
    try {
      await api.patch(`/api/v1/admin/courses/${id}`, parsed);
      toast.success("Course metadata saved.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSavingCourse(false);
    }
  };

  const saveRubric = async () => {
    if (!rubricExerciseId.trim()) {
      toast.error("Enter an exercise ID first.");
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(rubricJson);
    } catch {
      toast.error("Invalid JSON — please fix before saving.");
      return;
    }
    setSavingRubric(true);
    try {
      await api.patch(
        `/api/v1/admin/exercises/${rubricExerciseId.trim()}/rubric`,
        parsed,
      );
      toast.success("Rubric saved.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSavingRubric(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-8 p-6 md:p-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Edit Course</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Course ID: <span className="font-mono">{id}</span>
        </p>
      </div>

      {/* Course metadata section */}
      <section className="space-y-3 rounded-lg border p-5">
        <div>
          <h2 className="text-base font-semibold">Course Metadata (JSON)</h2>
          <p className="text-xs text-muted-foreground">
            Accepts: <code>title</code>, <code>description</code>
          </p>
        </div>
        <label htmlFor="course-json" className="sr-only">
          Course metadata JSON
        </label>
        <Textarea
          id="course-json"
          value={courseJson}
          onChange={(e) => setCourseJson(e.target.value)}
          rows={8}
          className="font-mono text-xs"
          aria-label="Course metadata JSON"
          placeholder={'{\n  "title": "New title",\n  "description": "Updated description"\n}'}
          spellCheck={false}
        />
        <Button
          onClick={() => void saveMetadata()}
          disabled={savingCourse}
          aria-label="Save course metadata"
        >
          {savingCourse ? "Saving…" : "Save metadata"}
        </Button>
      </section>

      {/* Rubric section */}
      <section className="space-y-3 rounded-lg border p-5">
        <div>
          <h2 className="text-base font-semibold">Exercise Rubric (JSON)</h2>
          <p className="text-xs text-muted-foreground">
            Enter the exercise UUID and paste the rubric JSON (and optional test cases).
          </p>
        </div>
        <div>
          <label htmlFor="exercise-id" className="mb-1 block text-xs font-medium">
            Exercise ID
          </label>
          <input
            id="exercise-id"
            type="text"
            value={rubricExerciseId}
            onChange={(e) => setRubricExerciseId(e.target.value)}
            className="w-full rounded-md border bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-primary"
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            aria-label="Exercise UUID"
          />
        </div>
        <label htmlFor="rubric-json" className="sr-only">
          Rubric JSON
        </label>
        <Textarea
          id="rubric-json"
          value={rubricJson}
          onChange={(e) => setRubricJson(e.target.value)}
          rows={10}
          className="font-mono text-xs"
          aria-label="Rubric JSON"
          placeholder={'{\n  "rubric": {\n    "criteria": []\n  },\n  "test_cases": []\n}'}
          spellCheck={false}
        />
        <Button
          onClick={() => void saveRubric()}
          disabled={savingRubric}
          aria-label="Save exercise rubric"
        >
          {savingRubric ? "Saving…" : "Save rubric"}
        </Button>
      </section>
    </div>
  );
}
