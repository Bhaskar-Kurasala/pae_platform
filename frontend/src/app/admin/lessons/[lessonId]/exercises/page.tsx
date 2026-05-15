"use client";

/**
 * Admin per-lesson exercise editor.
 *
 * CRUD for Exercise rows that drive the student /practice screen.
 * Solution code is admin-discretion: leave blank → human review,
 * fill in → student gets it after pass or 3 failures.
 *
 * Test cases and rubric are stored as JSON; the form gives admin a
 * raw textarea (with helper hints) rather than a forced UI schema —
 * test_cases shape varies by exercise type and over-engineering it
 * would be premature.
 */

import { use, useState } from "react";
import Link from "next/link";
import {
  useAdminLessonExercises,
  useCreateExercise,
  useDeleteExercise,
  useUpdateExercise,
} from "@/lib/hooks/use-admin-content";
import type {
  AdminExerciseCreate,
  AdminExerciseOut,
  AdminExerciseUpdate,
  ExerciseDifficulty,
} from "@/lib/admin-content-api";

interface Params {
  lessonId: string;
}

const DIFFICULTY_OPTS: ReadonlyArray<{ value: ExerciseDifficulty; label: string }> = [
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
];

function tryStringify(value: unknown): string {
  if (value == null) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "";
  }
}

function tryParse(text: string): { ok: true; value: unknown } | { ok: false; error: string } {
  const trimmed = text.trim();
  if (!trimmed) return { ok: true, value: null };
  try {
    return { ok: true, value: JSON.parse(trimmed) };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

export default function AdminLessonExercisesPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { lessonId } = use(params);
  const { data: exercises = [], isLoading, error } = useAdminLessonExercises(lessonId);
  const createMut = useCreateExercise(lessonId);
  const updateMut = useUpdateExercise(lessonId);
  const deleteMut = useDeleteExercise(lessonId);

  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link
            href="/admin"
            className="text-sm text-primary hover:underline inline-block mb-2"
          >
            ← Admin console
          </Link>
          <h1
            className="font-medium leading-[1.1]"
            style={{
              fontFamily: "var(--font-fraunces), Georgia, serif",
              fontSize: "26px",
              letterSpacing: "-0.04em",
            }}
          >
            Exercises &amp; capstones
          </h1>
          <p className="text-muted-foreground text-[13px] leading-[1.58] mt-1">
            Lesson ID:{" "}
            <code className="text-[12px] bg-muted px-1.5 py-0.5 rounded">
              {lessonId}
            </code>
          </p>
        </div>
        <button
          type="button"
          className="px-3 py-2 rounded-md text-[13px] font-semibold bg-primary text-primary-foreground hover:opacity-90"
          onClick={() => setShowCreate(true)}
        >
          + Add exercise
        </button>
      </div>

      {isLoading && <div className="text-muted-foreground">Loading…</div>}
      {error && (
        <div
          role="alert"
          className="border border-rose-300 bg-rose-50 text-rose-900 p-4 rounded-md"
        >
          Couldn’t load exercises — {String(error.message)}
        </div>
      )}

      {showCreate && (
        <ExerciseForm
          mode="create"
          lessonId={lessonId}
          submitting={createMut.isPending}
          onCancel={() => setShowCreate(false)}
          onSubmit={(body) => {
            createMut.mutate(body, {
              onSuccess: () => setShowCreate(false),
              onError: (err) => alert(`Create failed: ${err.message}`),
            });
          }}
        />
      )}

      {exercises.length === 0 && !isLoading && (
        <div className="border border-dashed border-line rounded-md p-8 text-center text-muted-foreground">
          No exercises on this lesson yet. Use “+ Add exercise” to create
          a coding exercise or capstone.
        </div>
      )}

      <ul className="space-y-3">
        {exercises.map((ex) => (
          <li key={ex.id} className="border border-line rounded-md bg-background">
            {editingId === ex.id ? (
              <ExerciseForm
                mode="edit"
                lessonId={lessonId}
                initial={ex}
                submitting={updateMut.isPending}
                onCancel={() => setEditingId(null)}
                onSubmit={(body) => {
                  const patch: AdminExerciseUpdate = { ...body };
                  // lesson_id can't be changed — strip from create body
                  delete (patch as { lesson_id?: string }).lesson_id;
                  updateMut.mutate(
                    { exerciseId: ex.id, body: patch },
                    {
                      onSuccess: () => setEditingId(null),
                      onError: (err) => alert(`Update failed: ${err.message}`),
                    },
                  );
                }}
              />
            ) : (
              <ExerciseRow
                ex={ex}
                onEdit={() => setEditingId(ex.id)}
                onDelete={() => {
                  if (confirm(`Delete "${ex.title}"?`)) {
                    deleteMut.mutate(ex.id, {
                      onError: (err) =>
                        alert(`Delete failed: ${err.message}`),
                    });
                  }
                }}
              />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ExerciseRow({
  ex,
  onEdit,
  onDelete,
}: {
  ex: AdminExerciseOut;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="p-4 flex items-start justify-between gap-4">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10px] font-bold tracking-[0.2em] uppercase text-primary">
            {ex.is_capstone ? "Capstone" : ex.exercise_type}
          </span>
          <span
            className={`text-[11px] font-bold leading-none px-2 py-1 rounded-full ${
              ex.difficulty === "hard"
                ? "bg-rose-100 text-rose-800"
                : ex.difficulty === "medium"
                ? "bg-amber-100 text-amber-800"
                : "bg-emerald-100 text-emerald-800"
            }`}
          >
            {ex.difficulty}
          </span>
          <span className="text-[11px] font-bold leading-none px-2 py-1 rounded-full bg-muted text-foreground">
            {ex.points} pts · pass at {ex.pass_score}
          </span>
        </div>
        <div className="mt-1 font-semibold">{ex.title}</div>
        {ex.description && (
          <div className="text-sm text-muted-foreground mt-0.5 line-clamp-3">
            {ex.description}
          </div>
        )}
        <div className="mt-2 text-[11px] text-muted-foreground">
          {ex.test_cases ? "✓ test_cases" : "—"}
          {" · "}
          {ex.rubric ? "✓ rubric" : "—"}
          {" · "}
          {ex.solution_code ? "✓ solution_code" : "no solution"}
        </div>
      </div>
      <div className="flex flex-col gap-1 shrink-0">
        <button
          type="button"
          className="px-3 py-1.5 rounded text-[12px] font-semibold border border-line hover:bg-muted/50"
          onClick={onEdit}
        >
          Edit
        </button>
        <button
          type="button"
          className="px-3 py-1.5 rounded text-[12px] font-semibold text-rose-700 border border-rose-300 hover:bg-rose-50"
          onClick={onDelete}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

interface FormProps {
  mode: "create" | "edit";
  lessonId: string;
  initial?: AdminExerciseOut;
  submitting: boolean;
  onSubmit: (body: AdminExerciseCreate) => void;
  onCancel: () => void;
}

function ExerciseForm({
  mode,
  lessonId,
  initial,
  submitting,
  onSubmit,
  onCancel,
}: FormProps) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [difficulty, setDifficulty] = useState<ExerciseDifficulty>(
    (initial?.difficulty as ExerciseDifficulty) ?? "medium",
  );
  const [points, setPoints] = useState(initial?.points ?? 100);
  const [passScore, setPassScore] = useState(initial?.pass_score ?? 70);
  const [isCapstone, setIsCapstone] = useState(initial?.is_capstone ?? false);
  const [starterCode, setStarterCode] = useState(initial?.starter_code ?? "");
  const [solutionCode, setSolutionCode] = useState(initial?.solution_code ?? "");
  const [testCasesText, setTestCasesText] = useState(
    tryStringify(initial?.test_cases),
  );
  // Existing admin endpoint stores rubric as {criteria: [...]} but
  // accepts the criteria list under `rubric_criteria` on writes.
  const initialCriteria = (initial?.rubric as { criteria?: unknown } | null)?.criteria;
  const [rubricText, setRubricText] = useState(tryStringify(initialCriteria));

  return (
    <form
      className="p-4 space-y-3 bg-muted/30"
      onSubmit={(e) => {
        e.preventDefault();
        const tc = tryParse(testCasesText);
        if (!tc.ok) {
          alert(`test_cases is not valid JSON: ${tc.error}`);
          return;
        }
        const rb = tryParse(rubricText);
        if (!rb.ok) {
          alert(`rubric is not valid JSON: ${rb.error}`);
          return;
        }
        // The existing backend schema rejects rubric/test_cases shapes
        // that don't match — pass null when the admin leaves them blank
        // rather than an empty array, which would also fail validation.
        const tcArr = Array.isArray(tc.value)
          ? (tc.value as Array<Record<string, unknown>>)
          : null;
        const rbArr = Array.isArray(rb.value)
          ? (rb.value as Array<Record<string, unknown>>)
          : null;
        onSubmit({
          title: title.trim(),
          description: description.trim() || null,
          difficulty,
          points: Number(points),
          pass_score: Number(passScore),
          is_capstone: isCapstone,
          starter_code: starterCode || null,
          solution_code: solutionCode || null,
          // Existing backend types: array of {name, input, expected_output}
          test_cases: tcArr as never,
          // Existing backend wraps these as {criteria: [...]} on read,
          // but writes accept the raw list under `rubric_criteria`.
          rubric_criteria: rbArr as never,
        });
      }}
    >
      <label className="block text-sm">
        <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
          Title
        </span>
        <input
          type="text"
          required
          maxLength={500}
          className="w-full border border-line rounded px-2 py-1.5 bg-background"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>

      <label className="block text-sm">
        <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
          Description / problem statement (markdown supported)
        </span>
        <textarea
          className="w-full border border-line rounded px-2 py-1.5 bg-background font-mono text-[13px]"
          rows={6}
          value={description ?? ""}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <label className="text-sm">
          <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
            Difficulty
          </span>
          <select
            className="w-full border border-line rounded px-2 py-1.5 bg-background"
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value as ExerciseDifficulty)}
          >
            {DIFFICULTY_OPTS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
            Points
          </span>
          <input
            type="number"
            min={0}
            max={1000}
            className="w-full border border-line rounded px-2 py-1.5 bg-background"
            value={points}
            onChange={(e) => setPoints(Number(e.target.value))}
          />
        </label>
        <label className="text-sm">
          <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
            Pass score
          </span>
          <input
            type="number"
            min={0}
            max={100}
            className="w-full border border-line rounded px-2 py-1.5 bg-background"
            value={passScore}
            onChange={(e) => setPassScore(Number(e.target.value))}
          />
        </label>
      </div>

      <label className="text-sm flex items-center gap-2">
        <input
          type="checkbox"
          checked={isCapstone}
          onChange={(e) => setIsCapstone(e.target.checked)}
        />
        Mark as capstone (human-graded; appears in capstone mode on /practice)
      </label>

      <label className="block text-sm">
        <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
          Starter code (optional)
        </span>
        <textarea
          className="w-full border border-line rounded px-2 py-1.5 bg-background font-mono text-[12px]"
          rows={6}
          value={starterCode ?? ""}
          onChange={(e) => setStarterCode(e.target.value)}
        />
      </label>

      <label className="block text-sm">
        <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
          Solution code (optional — leave blank for human-only review)
        </span>
        <textarea
          className="w-full border border-line rounded px-2 py-1.5 bg-background font-mono text-[12px]"
          rows={6}
          value={solutionCode ?? ""}
          onChange={(e) => setSolutionCode(e.target.value)}
        />
      </label>

      <label className="block text-sm">
        <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
          test_cases (JSON array, optional)
        </span>
        <textarea
          className="w-full border border-line rounded px-2 py-1.5 bg-background font-mono text-[12px]"
          rows={4}
          value={testCasesText}
          onChange={(e) => setTestCasesText(e.target.value)}
          placeholder={`[\n  {"name": "case1", "input": "1\\n2", "expected_output": "3", "hidden": false}\n]`}
        />
      </label>

      <label className="block text-sm">
        <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
          rubric criteria (JSON array, optional)
        </span>
        <textarea
          className="w-full border border-line rounded px-2 py-1.5 bg-background font-mono text-[12px]"
          rows={3}
          value={rubricText}
          onChange={(e) => setRubricText(e.target.value)}
          placeholder={`[\n  {"name": "Correctness", "weight": 60, "description": "..."}\n]`}
        />
      </label>

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          className="px-3 py-2 rounded-md text-[13px] font-semibold border border-line bg-transparent"
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="submit"
          className="px-3 py-2 rounded-md text-[13px] font-semibold bg-primary text-primary-foreground hover:opacity-90"
          disabled={submitting}
        >
          {submitting
            ? "Saving…"
            : mode === "create"
            ? "Create exercise"
            : "Save changes"}
        </button>
      </div>
    </form>
  );
}
