"use client";

/**
 * /admin/courses/[id]/edit — Deep course workspace.
 *
 * Five tabs: Lessons · Exercises · MCQs · Settings · Analytics.
 * Inline-expand editing on every card. v8 cream/forest aesthetic.
 */

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, Pencil, Star, Trash2, X } from "lucide-react";
import {
  useCoursesHealth,
  useAdminCourseLessons,
  useCreateLesson,
  useUpdateLesson,
  useDeleteLesson,
  useReorderLessons,
  useAdminLessonExercises,
  useCreateExercise,
  useUpdateExercise,
  useDeleteExercise,
  useAdminLessonMCQs,
  useCreateMCQ,
  useUpdateMCQ,
  useDeleteMCQ,
  useCourseAnalytics,
  type AdminLessonRead,
  type AdminLessonCreate,
  type AdminLessonUpdate,
  type AdminExerciseRead,
  type AdminExerciseCreate,
  type AdminExerciseUpdate,
  type AdminMCQRead,
  type AdminMCQCreate,
  type AdminMCQUpdate,
  type RubricCriterion,
  type TestCase,
} from "@/lib/hooks/use-courses";
import { useAdminTheme } from "@/lib/hooks/use-admin-theme";
import { api } from "@/lib/api-client";
import { toast } from "@/lib/toast";
import { showErrorToast } from "@/lib/error-toast";

type TabKey = "lessons" | "exercises" | "mcqs" | "settings" | "analytics";

const TABS: { key: TabKey; label: string }[] = [
  { key: "lessons", label: "Lessons" },
  { key: "exercises", label: "Exercises" },
  { key: "mcqs", label: "MCQs" },
  { key: "settings", label: "Settings" },
  { key: "analytics", label: "Analytics" },
];

const DIFFICULTIES = ["easy", "medium", "hard"] as const;
const COURSE_DIFFICULTIES = ["beginner", "intermediate", "advanced"] as const;

// ============================================================
// Page
// ============================================================

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function CourseEditPage({ params }: PageProps) {
  const { id } = use(params);
  const { theme } = useAdminTheme();
  const isDark = theme === "dark";
  const [tab, setTab] = useState<TabKey>("lessons");

  const pageBg = isDark
    ? "linear-gradient(180deg, #0b110e 0%, #10120e 100%)"
    : "#FBF7EE";
  const ink = isDark ? "#f0ece1" : "#10120e";
  const muted = isDark ? "#9a9588" : "#686559";
  const line = isDark ? "#2c3830" : "#dbd1bf";
  const eyebrow = isDark ? "#8fd6b1" : "#356d50";
  const cardBg = isDark ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.7)";

  const healthQ = useCoursesHealth();
  const course = useMemo(
    () => healthQ.data?.items.find((c) => c.course_id === id),
    [healthQ.data, id],
  );

  const styleCtx: StyleCtx = { isDark, ink, muted, line, eyebrow, cardBg };

  return (
    <div
      className="min-h-screen w-full"
      style={{
        background: pageBg,
        color: ink,
        fontFamily: "var(--font-inter), Inter, system-ui, sans-serif",
      }}
    >
      <div className="max-w-[1400px] mx-auto p-6 md:p-8 space-y-6">
        <Link
          href="/admin/courses"
          style={{
            fontSize: 12,
            color: muted,
            textDecoration: "none",
            display: "inline-block",
          }}
        >
          ← Back to courses
        </Link>

        <header className="flex flex-col gap-2">
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: eyebrow,
            }}
          >
            Admin · Catalog · Edit
          </span>
          <h1
            style={{
              fontFamily: "var(--font-fraunces), Georgia, serif",
              fontSize: 28,
              fontWeight: 500,
              letterSpacing: "-0.04em",
              lineHeight: 1.1,
            }}
          >
            {course?.title ?? (healthQ.isLoading ? "Loading…" : "Course")}
          </h1>
          {course ? (
            <div
              className="flex flex-wrap items-center gap-2"
              style={{ fontSize: 12, color: muted }}
            >
              <code
                style={{
                  fontFamily:
                    "var(--font-jetbrains-mono), ui-monospace, monospace",
                  background: cardBg,
                  border: `1px solid ${line}`,
                  borderRadius: 4,
                  padding: "2px 6px",
                }}
              >
                {course.slug}
              </code>
              <Pill bg={isDark ? "rgba(255,255,255,0.06)" : "#efe9d8"} color={ink}>
                {course.difficulty}
              </Pill>
              <span>
                {course.price_cents === 0
                  ? "Free"
                  : `$${(course.price_cents / 100).toFixed(0)}`}
              </span>
              <span>·</span>
              <code
                style={{
                  fontFamily:
                    "var(--font-jetbrains-mono), ui-monospace, monospace",
                  fontSize: 11,
                  opacity: 0.7,
                }}
              >
                {id}
              </code>
              <span>·</span>
              <PublishToggle
                value={course.is_published}
                onToggle={async () => {
                  try {
                    await api.patch(`/api/v1/admin/courses/${id}`, {
                      is_published: !course.is_published,
                    });
                    healthQ.refetch();
                  } catch (err) {
                    showErrorToast(err, undefined);
                  }
                }}
                label={course.title}
              />
              <span>·</span>
              <a
                href={`/courses/${course.slug}`}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: eyebrow,
                  textDecoration: "none",
                  border: `1px solid ${line}`,
                  borderRadius: 999,
                  padding: "3px 9px",
                  background: cardBg,
                }}
                title="Open this course on the student portal in a new tab"
              >
                Preview as student
              </a>
            </div>
          ) : null}
        </header>

        {/* Tabs */}
        <div
          role="tablist"
          aria-label="Course workspace tabs"
          className="inline-flex items-center gap-1 rounded-full p-1"
          style={{
            background: isDark
              ? "rgba(255,255,255,0.04)"
              : "rgba(255,255,255,0.7)",
            border: `1px solid ${line}`,
          }}
        >
          {TABS.map((t) => {
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setTab(t.key)}
                className="px-4 py-1.5 rounded-full transition"
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  background: active ? "#1D9E75" : "transparent",
                  color: active ? "#ffffff" : ink,
                  cursor: "pointer",
                  border: "none",
                }}
              >
                {t.label}
              </button>
            );
          })}
        </div>

        {tab === "lessons" ? (
          <LessonsTab courseId={id} ctx={styleCtx} />
        ) : tab === "exercises" ? (
          <ExercisesTab courseId={id} ctx={styleCtx} />
        ) : tab === "mcqs" ? (
          <MCQsTab courseId={id} ctx={styleCtx} />
        ) : tab === "settings" ? (
          <SettingsTab
            courseId={id}
            initial={course ?? null}
            onSaved={() => healthQ.refetch()}
            ctx={styleCtx}
          />
        ) : (
          <AnalyticsTab courseId={id} ctx={styleCtx} />
        )}
      </div>
    </div>
  );
}

// ============================================================
// Shared style context + tiny atoms
// ============================================================

interface StyleCtx {
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
  eyebrow: string;
  cardBg: string;
}

function Pill({
  children,
  bg,
  color,
}: {
  children: React.ReactNode;
  bg: string;
  color: string;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        background: bg,
        color,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        borderRadius: 999,
        padding: "2px 8px",
      }}
    >
      {children}
    </span>
  );
}

function SectionHeader({
  title,
  action,
  ctx,
}: {
  title: string;
  action?: React.ReactNode;
  ctx: StyleCtx;
}) {
  return (
    <div className="flex items-center justify-between">
      <h2
        style={{
          fontFamily: "var(--font-fraunces), Georgia, serif",
          fontSize: 18,
          fontWeight: 500,
          letterSpacing: "-0.02em",
          color: ctx.ink,
        }}
      >
        {title}
      </h2>
      {action}
    </div>
  );
}

function PrimaryButton({
  children,
  onClick,
  type = "button",
  disabled,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  disabled?: boolean;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="rounded-full px-4 py-1.5 transition disabled:opacity-50"
      style={{
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        background: "#1D9E75",
        color: "#fff",
        border: "none",
        cursor: disabled ? "default" : "pointer",
      }}
    >
      {children}
    </button>
  );
}

function GhostButton({
  children,
  onClick,
  ctx,
  danger,
  type = "button",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  ctx: StyleCtx;
  danger?: boolean;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      className="rounded-full px-3 py-1 transition"
      style={{
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        border: `1px solid ${danger ? "#d96252" : ctx.line}`,
        background: "transparent",
        color: danger ? "#d96252" : ctx.ink,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function IconBtn({
  children,
  onClick,
  ariaLabel,
  ctx,
  danger,
}: {
  children: React.ReactNode;
  onClick: (e: React.MouseEvent) => void;
  ariaLabel: string;
  ctx: StyleCtx;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className="inline-flex items-center justify-center rounded-md p-1.5"
      style={{
        background: "transparent",
        border: `1px solid ${ctx.line}`,
        color: danger ? "#d96252" : ctx.ink,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function Switch({
  value,
  onToggle,
  label,
}: {
  value: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      aria-label={label}
      onClick={onToggle}
      style={{
        position: "relative",
        width: 34,
        height: 18,
        borderRadius: 999,
        border: "none",
        background: value ? "#1D9E75" : "rgba(120,120,120,0.4)",
        cursor: "pointer",
        transition: "background 0.15s",
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 2,
          left: value ? 18 : 2,
          width: 14,
          height: 14,
          borderRadius: 999,
          background: "#fff",
          transition: "left 0.15s",
        }}
      />
    </button>
  );
}

function PublishToggle({
  value,
  onToggle,
  label,
}: {
  value: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      aria-label={`Toggle publish for ${label}`}
      onClick={onToggle}
      className="rounded-full"
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        padding: "3px 10px",
        border: "1px solid currentColor",
        background: value ? "#1D9E75" : "transparent",
        color: value ? "#fff" : "currentColor",
        cursor: "pointer",
      }}
    >
      {value ? "Published" : "Draft"}
    </button>
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement> & {
  ctx: StyleCtx;
  mono?: boolean;
}) {
  const { ctx, mono, style, ...rest } = props;
  return (
    <input
      {...rest}
      style={{
        width: "100%",
        background: ctx.isDark ? "rgba(0,0,0,0.25)" : "#fff",
        border: `1px solid ${ctx.line}`,
        borderRadius: 6,
        padding: "8px 10px",
        fontSize: 13,
        color: ctx.ink,
        fontFamily: mono
          ? "var(--font-jetbrains-mono), ui-monospace, monospace"
          : "inherit",
        outline: "none",
        ...style,
      }}
    />
  );
}

function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  ctx: StyleCtx;
  mono?: boolean;
}) {
  const { ctx, mono, style, ...rest } = props;
  return (
    <textarea
      {...rest}
      style={{
        width: "100%",
        background: ctx.isDark ? "rgba(0,0,0,0.25)" : "#fff",
        border: `1px solid ${ctx.line}`,
        borderRadius: 6,
        padding: "8px 10px",
        fontSize: 13,
        lineHeight: 1.5,
        color: ctx.ink,
        fontFamily: mono
          ? "var(--font-jetbrains-mono), ui-monospace, monospace"
          : "inherit",
        outline: "none",
        resize: "vertical",
        ...style,
      }}
    />
  );
}

function FieldLabel({
  children,
  ctx,
}: {
  children: React.ReactNode;
  ctx: StyleCtx;
}) {
  return (
    <label
      style={{
        display: "block",
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        color: ctx.muted,
        marginBottom: 4,
      }}
    >
      {children}
    </label>
  );
}

function DifficultyPills({
  value,
  onChange,
  ctx,
  options = DIFFICULTIES as readonly string[],
}: {
  value: string;
  onChange: (v: string) => void;
  ctx: StyleCtx;
  options?: readonly string[];
}) {
  return (
    <div className="inline-flex items-center gap-1">
      {options.map((d) => {
        const active = value === d;
        return (
          <button
            key={d}
            type="button"
            onClick={() => onChange(d)}
            className="rounded-full px-3 py-1"
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              background: active ? "#1D9E75" : "transparent",
              color: active ? "#fff" : ctx.ink,
              border: `1px solid ${active ? "transparent" : ctx.line}`,
              cursor: "pointer",
            }}
          >
            {d}
          </button>
        );
      })}
    </div>
  );
}

function Card({
  children,
  ctx,
  style,
}: {
  children: React.ReactNode;
  ctx: StyleCtx;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        background: ctx.cardBg,
        border: `1px solid ${ctx.line}`,
        borderRadius: 12,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function EmptyState({ text, ctx }: { text: string; ctx: StyleCtx }) {
  return (
    <Card ctx={ctx} style={{ padding: 24, textAlign: "center" }}>
      <p style={{ fontSize: 13, color: ctx.muted }}>{text}</p>
    </Card>
  );
}

// ============================================================
// LESSONS TAB
// ============================================================

function LessonsTab({ courseId, ctx }: { courseId: string; ctx: StyleCtx }) {
  const q = useAdminCourseLessons(courseId);
  const createMut = useCreateLesson();
  const updateMut = useUpdateLesson();
  const deleteMut = useDeleteLesson();
  const reorderMut = useReorderLessons();
  const [creating, setCreating] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const items = useMemo(
    () => [...(q.data?.items ?? [])].sort((a, b) => a.order - b.order),
    [q.data],
  );

  const move = async (idx: number, dir: -1 | 1) => {
    const target = idx + dir;
    if (target < 0 || target >= items.length) return;
    const ids = items.map((l) => l.id);
    [ids[idx], ids[target]] = [ids[target], ids[idx]];
    try {
      await reorderMut.mutateAsync({ courseId, lesson_ids: ids });
    } catch (err) {
      showErrorToast(err, undefined);
    }
  };

  const publishedCount = items.filter((l) => l.is_published).length;
  const draftCount = items.length - publishedCount;
  const summary =
    items.length === 0
      ? null
      : publishedCount === 0
        ? `${draftCount} draft${draftCount === 1 ? "" : "s"} — students see none until published`
        : draftCount === 0
          ? `${publishedCount} published · visible to enrolled students`
          : `${publishedCount} published · ${draftCount} draft${draftCount === 1 ? "" : "s"}`;
  const summaryTone =
    items.length === 0
      ? ctx.muted
      : publishedCount === 0
        ? "#d6a54d"
        : ctx.muted;

  return (
    <div className="space-y-4">
      <SectionHeader
        title="All lessons"
        ctx={ctx}
        action={
          !creating ? (
            <PrimaryButton onClick={() => setCreating(true)}>
              + New lesson
            </PrimaryButton>
          ) : null
        }
      />

      {summary ? (
        <div
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: summaryTone,
          }}
        >
          {summary}
        </div>
      ) : null}

      {creating ? (
        <LessonForm
          ctx={ctx}
          mode="create"
          onCancel={() => setCreating(false)}
          onSubmit={async (body) => {
            try {
              await createMut.mutateAsync({ courseId, body });
              toast.success("Lesson created.");
              setCreating(false);
            } catch (err) {
              showErrorToast(err, undefined);
            }
          }}
        />
      ) : null}

      {q.isLoading ? (
        <EmptyState text="Loading lessons…" ctx={ctx} />
      ) : items.length === 0 && !creating ? (
        <EmptyState
          text="No lessons yet. Click '+ New lesson' to add one."
          ctx={ctx}
        />
      ) : (
        <div className="space-y-2">
          {items.map((lesson, idx) => (
            <LessonCard
              key={lesson.id}
              lesson={lesson}
              ctx={ctx}
              expanded={expandedId === lesson.id}
              onToggle={() =>
                setExpandedId(expandedId === lesson.id ? null : lesson.id)
              }
              onMoveUp={() => move(idx, -1)}
              onMoveDown={() => move(idx, 1)}
              canUp={idx > 0}
              canDown={idx < items.length - 1}
              onPatch={async (patch) => {
                try {
                  await updateMut.mutateAsync({
                    id: lesson.id,
                    courseId,
                    patch,
                  });
                } catch (err) {
                  showErrorToast(err, undefined);
                }
              }}
              onDelete={async () => {
                if (!window.confirm(`Delete lesson "${lesson.title}"?`)) return;
                try {
                  await deleteMut.mutateAsync({ id: lesson.id, courseId });
                  toast.success("Lesson deleted.");
                } catch (err) {
                  showErrorToast(err, undefined);
                }
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function LessonCard({
  lesson,
  ctx,
  expanded,
  onToggle,
  onMoveUp,
  onMoveDown,
  canUp,
  canDown,
  onPatch,
  onDelete,
}: {
  lesson: AdminLessonRead;
  ctx: StyleCtx;
  expanded: boolean;
  onToggle: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  canUp: boolean;
  canDown: boolean;
  onPatch: (patch: AdminLessonUpdate) => Promise<void>;
  onDelete: () => void;
}) {
  return (
    <Card ctx={ctx}>
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer"
        onClick={onToggle}
      >
        <div
          className="flex flex-col gap-1"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            aria-label="Move up"
            onClick={onMoveUp}
            disabled={!canUp}
            style={{
              background: "transparent",
              border: "none",
              cursor: canUp ? "pointer" : "default",
              color: canUp ? ctx.ink : ctx.muted,
              opacity: canUp ? 1 : 0.3,
              padding: 2,
            }}
          >
            <ArrowUp size={14} />
          </button>
          <button
            type="button"
            aria-label="Move down"
            onClick={onMoveDown}
            disabled={!canDown}
            style={{
              background: "transparent",
              border: "none",
              cursor: canDown ? "pointer" : "default",
              color: canDown ? ctx.ink : ctx.muted,
              opacity: canDown ? 1 : 0.3,
              padding: 2,
            }}
          >
            <ArrowDown size={14} />
          </button>
        </div>

        <div className="flex-1 min-w-0">
          <div
            style={{
              fontFamily: "var(--font-fraunces), Georgia, serif",
              fontSize: 16,
              fontWeight: 500,
              color: ctx.ink,
            }}
          >
            {lesson.title}
          </div>
          <div
            style={{
              fontSize: 11,
              color: ctx.muted,
              fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
            }}
          >
            {lesson.slug}
          </div>
        </div>

        <div
          className="flex items-center gap-2"
          onClick={(e) => e.stopPropagation()}
        >
          <PublishToggle
            value={lesson.is_published}
            onToggle={() => onPatch({ is_published: !lesson.is_published })}
            label={lesson.title}
          />
          {lesson.is_free_preview ? (
            <Pill bg="#d6a54d" color="#fff">
              Preview
            </Pill>
          ) : null}
          <Pill bg={ctx.isDark ? "rgba(255,255,255,0.06)" : "#efe9d8"} color={ctx.muted}>
            {lesson.exercise_count} ex
          </Pill>
          <Pill bg={ctx.isDark ? "rgba(255,255,255,0.06)" : "#efe9d8"} color={ctx.muted}>
            {lesson.mcq_count} q
          </Pill>
          <span style={{ fontSize: 11, color: ctx.muted }}>
            {Math.round(lesson.duration_seconds / 60)}m
          </span>
          <IconBtn ctx={ctx} onClick={onToggle} ariaLabel="Edit lesson">
            <Pencil size={13} />
          </IconBtn>
          <IconBtn
            ctx={ctx}
            danger
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            ariaLabel="Delete lesson"
          >
            <Trash2 size={13} />
          </IconBtn>
        </div>
      </div>

      {expanded ? (
        <div style={{ borderTop: `1px solid ${ctx.line}`, padding: 16 }}>
          <LessonForm
            ctx={ctx}
            mode="edit"
            initial={lesson}
            onCancel={onToggle}
            onSubmit={async (patch) => {
              await onPatch(patch);
              toast.success("Lesson updated.");
              onToggle();
            }}
          />
        </div>
      ) : null}
    </Card>
  );
}

function LessonForm({
  ctx,
  mode,
  initial,
  onSubmit,
  onCancel,
}: {
  ctx: StyleCtx;
  mode: "create" | "edit";
  initial?: AdminLessonRead;
  onSubmit: (body: AdminLessonCreate & AdminLessonUpdate) => Promise<void>;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [slug, setSlug] = useState(initial?.slug ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [content, setContent] = useState(initial?.content ?? "");
  const [videoUrl, setVideoUrl] = useState(initial?.video_url ?? "");
  const [youtubeId, setYoutubeId] = useState(initial?.youtube_video_id ?? "");
  const [duration, setDuration] = useState(initial?.duration_seconds ?? 0);
  const [isPublished, setIsPublished] = useState(initial?.is_published ?? false);
  const [isFreePreview, setIsFreePreview] = useState(
    initial?.is_free_preview ?? false,
  );
  const [githubBranch, setGithubBranch] = useState(initial?.github_branch ?? "");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!title.trim()) {
      toast.error("Title is required.");
      return;
    }
    setSaving(true);
    try {
      await onSubmit({
        title: title.trim(),
        slug: slug.trim() || undefined,
        description: description || undefined,
        content: content || undefined,
        video_url: videoUrl || undefined,
        youtube_video_id: youtubeId || undefined,
        duration_seconds: Number(duration) || 0,
        is_published: isPublished,
        is_free_preview: isFreePreview,
        github_branch: githubBranch || undefined,
      });
    } finally {
      setSaving(false);
    }
  };

  const formBody = (
    <div className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <FieldLabel ctx={ctx}>Title</FieldLabel>
          <Input
            ctx={ctx}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Lesson title"
          />
        </div>
        <div>
          <FieldLabel ctx={ctx}>Slug</FieldLabel>
          <Input
            ctx={ctx}
            mono
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="auto-generated if empty"
          />
        </div>
      </div>
      <div>
        <FieldLabel ctx={ctx}>Description</FieldLabel>
        <TextArea
          ctx={ctx}
          rows={3}
          value={description ?? ""}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div>
        <FieldLabel ctx={ctx}>Content (markdown)</FieldLabel>
        <TextArea
          ctx={ctx}
          mono
          rows={8}
          value={content ?? ""}
          onChange={(e) => setContent(e.target.value)}
        />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <FieldLabel ctx={ctx}>Video URL</FieldLabel>
          <Input
            ctx={ctx}
            value={videoUrl ?? ""}
            onChange={(e) => setVideoUrl(e.target.value)}
          />
        </div>
        <div>
          <FieldLabel ctx={ctx}>YouTube video ID</FieldLabel>
          <Input
            ctx={ctx}
            mono
            value={youtubeId ?? ""}
            onChange={(e) => setYoutubeId(e.target.value)}
          />
        </div>
        <div>
          <FieldLabel ctx={ctx}>Duration (seconds)</FieldLabel>
          <Input
            ctx={ctx}
            type="number"
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
          />
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
        <div className="flex items-center gap-3">
          <Switch
            value={isPublished}
            onToggle={() => setIsPublished(!isPublished)}
            label="Published"
          />
          <span style={{ fontSize: 12, color: ctx.ink }}>Published</span>
        </div>
        <div className="flex items-center gap-3">
          <Switch
            value={isFreePreview}
            onToggle={() => setIsFreePreview(!isFreePreview)}
            label="Free preview"
          />
          <span style={{ fontSize: 12, color: ctx.ink }}>Free preview</span>
        </div>
        <div>
          <FieldLabel ctx={ctx}>GitHub branch</FieldLabel>
          <Input
            ctx={ctx}
            mono
            value={githubBranch ?? ""}
            onChange={(e) => setGithubBranch(e.target.value)}
          />
        </div>
      </div>
      <div className="flex items-center gap-2 pt-2">
        <PrimaryButton onClick={submit} disabled={saving}>
          {saving ? "Saving…" : mode === "create" ? "Create" : "Save changes"}
        </PrimaryButton>
        <GhostButton ctx={ctx} onClick={onCancel}>
          Cancel
        </GhostButton>
      </div>
    </div>
  );

  return (
    <div>
      {mode === "create" ? (
        <Card ctx={ctx} style={{ padding: 16, marginBottom: 8 }}>
          {formBody}
        </Card>
      ) : (
        formBody
      )}
    </div>
  );
}

// ============================================================
// EXERCISES TAB
// ============================================================

function ExercisesTab({
  courseId,
  ctx,
}: {
  courseId: string;
  ctx: StyleCtx;
}) {
  const lessonsQ = useAdminCourseLessons(courseId);
  const lessons = useMemo(
    () => [...(lessonsQ.data?.items ?? [])].sort((a, b) => a.order - b.order),
    [lessonsQ.data],
  );
  const [selectedLesson, setSelectedLesson] = useState<string>("");

  useEffect(() => {
    if (!selectedLesson && lessons.length) {
      setSelectedLesson(lessons[0].id);
    }
  }, [lessons, selectedLesson]);

  return (
    <div className="space-y-4">
      <LessonPicker
        lessons={lessons}
        value={selectedLesson}
        onChange={setSelectedLesson}
        ctx={ctx}
      />
      {selectedLesson ? (
        <ExerciseList lessonId={selectedLesson} ctx={ctx} />
      ) : (
        <EmptyState text="Add a lesson first to create exercises." ctx={ctx} />
      )}
    </div>
  );
}

function LessonPicker({
  lessons,
  value,
  onChange,
  ctx,
}: {
  lessons: AdminLessonRead[];
  value: string;
  onChange: (v: string) => void;
  ctx: StyleCtx;
}) {
  return (
    <div className="flex items-center gap-2">
      <FieldLabel ctx={ctx}>Lesson</FieldLabel>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          background: ctx.isDark ? "rgba(0,0,0,0.25)" : "#fff",
          border: `1px solid ${ctx.line}`,
          borderRadius: 6,
          padding: "6px 10px",
          fontSize: 13,
          color: ctx.ink,
          minWidth: 280,
        }}
      >
        {lessons.length === 0 ? <option value="">No lessons</option> : null}
        {lessons.map((l) => (
          <option key={l.id} value={l.id}>
            {l.title}
          </option>
        ))}
      </select>
    </div>
  );
}

function ExerciseList({
  lessonId,
  ctx,
}: {
  lessonId: string;
  ctx: StyleCtx;
}) {
  const q = useAdminLessonExercises(lessonId);
  const createMut = useCreateExercise();
  const updateMut = useUpdateExercise();
  const deleteMut = useDeleteExercise();
  const [creating, setCreating] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const items = useMemo(
    () => [...(q.data?.items ?? [])].sort((a, b) => a.order - b.order),
    [q.data],
  );

  return (
    <div className="space-y-3">
      <SectionHeader
        title="Exercises"
        ctx={ctx}
        action={
          !creating ? (
            <PrimaryButton onClick={() => setCreating(true)}>
              + New exercise
            </PrimaryButton>
          ) : null
        }
      />

      {creating ? (
        <Card ctx={ctx} style={{ padding: 16 }}>
          <ExerciseForm
            ctx={ctx}
            mode="create"
            onCancel={() => setCreating(false)}
            onSubmit={async (body) => {
              try {
                await createMut.mutateAsync({ lessonId, body });
                toast.success("Exercise created.");
                setCreating(false);
              } catch (err) {
                showErrorToast(err, undefined);
              }
            }}
          />
        </Card>
      ) : null}

      {q.isLoading ? (
        <EmptyState text="Loading exercises…" ctx={ctx} />
      ) : items.length === 0 && !creating ? (
        <EmptyState text="No exercises for this lesson yet." ctx={ctx} />
      ) : (
        <div className="space-y-2">
          {items.map((ex) => (
            <Card key={ex.id} ctx={ctx}>
              <div
                className="flex items-center gap-3 px-4 py-3 cursor-pointer"
                onClick={() =>
                  setExpandedId(expandedId === ex.id ? null : ex.id)
                }
              >
                <div className="flex-1 min-w-0">
                  <div
                    style={{
                      fontFamily: "var(--font-fraunces), Georgia, serif",
                      fontSize: 15,
                      fontWeight: 500,
                      color: ctx.ink,
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    {ex.title}
                    {ex.is_capstone ? (
                      <Star size={14} fill="#d6a54d" stroke="#d6a54d" />
                    ) : null}
                  </div>
                </div>
                <div
                  className="flex items-center gap-2"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Pill
                    bg={
                      ex.difficulty === "hard"
                        ? "#d96252"
                        : ex.difficulty === "medium"
                          ? "#d6a54d"
                          : "#1D9E75"
                    }
                    color="#fff"
                  >
                    {ex.difficulty}
                  </Pill>
                  <span style={{ fontSize: 11, color: ctx.muted }}>
                    {ex.points} pts
                  </span>
                  <Pill bg={ctx.isDark ? "rgba(255,255,255,0.06)" : "#efe9d8"} color={ctx.muted}>
                    {ex.submission_count} sub
                  </Pill>
                  <IconBtn
                    ctx={ctx}
                    onClick={() =>
                      setExpandedId(expandedId === ex.id ? null : ex.id)
                    }
                    ariaLabel="Edit exercise"
                  >
                    <Pencil size={13} />
                  </IconBtn>
                  <IconBtn
                    ctx={ctx}
                    danger
                    onClick={async (e) => {
                      e.stopPropagation();
                      if (!window.confirm(`Delete "${ex.title}"?`)) return;
                      try {
                        await deleteMut.mutateAsync({ id: ex.id, lessonId });
                        toast.success("Exercise deleted.");
                      } catch (err) {
                        showErrorToast(err, undefined);
                      }
                    }}
                    ariaLabel="Delete exercise"
                  >
                    <Trash2 size={13} />
                  </IconBtn>
                </div>
              </div>
              {expandedId === ex.id ? (
                <div
                  style={{
                    borderTop: `1px solid ${ctx.line}`,
                    padding: 16,
                  }}
                >
                  <ExerciseForm
                    ctx={ctx}
                    mode="edit"
                    initial={ex}
                    onCancel={() => setExpandedId(null)}
                    onSubmit={async (patch) => {
                      try {
                        await updateMut.mutateAsync({
                          id: ex.id,
                          lessonId,
                          patch,
                        });
                        toast.success("Exercise updated.");
                        setExpandedId(null);
                      } catch (err) {
                        showErrorToast(err, undefined);
                      }
                    }}
                  />
                </div>
              ) : null}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function ExerciseForm({
  ctx,
  mode,
  initial,
  onSubmit,
  onCancel,
}: {
  ctx: StyleCtx;
  mode: "create" | "edit";
  initial?: AdminExerciseRead;
  onSubmit: (body: AdminExerciseCreate & AdminExerciseUpdate) => Promise<void>;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [difficulty, setDifficulty] = useState(initial?.difficulty ?? "medium");
  const [exerciseType, setExerciseType] = useState(
    initial?.exercise_type ?? "coding",
  );
  const [isCapstone, setIsCapstone] = useState(initial?.is_capstone ?? false);
  const [passScore, setPassScore] = useState(initial?.pass_score ?? 70);
  const [dueAt, setDueAt] = useState(
    initial?.due_at ? initial.due_at.slice(0, 16) : "",
  );
  const [points, setPoints] = useState(initial?.points ?? 10);
  const [githubUrl, setGithubUrl] = useState(
    initial?.github_template_url ?? "",
  );
  const [starter, setStarter] = useState(initial?.starter_code ?? "");
  const [solution, setSolution] = useState(initial?.solution_code ?? "");
  const [criteria, setCriteria] = useState<RubricCriterion[]>(
    initial?.rubric?.criteria ?? [],
  );
  const [tests, setTests] = useState<TestCase[]>(initial?.test_cases ?? []);
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!title.trim()) {
      toast.error("Title is required.");
      return;
    }
    setSaving(true);
    try {
      await onSubmit({
        title: title.trim(),
        description: description || undefined,
        exercise_type: exerciseType || undefined,
        difficulty,
        starter_code: starter || undefined,
        solution_code: solution || undefined,
        test_cases: tests.length ? tests : undefined,
        rubric_criteria: criteria.length ? criteria : undefined,
        points: Number(points),
        is_capstone: isCapstone,
        pass_score: Number(passScore),
        due_at: dueAt ? new Date(dueAt).toISOString() : null,
        github_template_url: githubUrl || undefined,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <div>
        <FieldLabel ctx={ctx}>Title</FieldLabel>
        <Input
          ctx={ctx}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>
      <div>
        <FieldLabel ctx={ctx}>Description</FieldLabel>
        <TextArea
          ctx={ctx}
          rows={3}
          value={description ?? ""}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <FieldLabel ctx={ctx}>Difficulty</FieldLabel>
          <DifficultyPills
            value={difficulty}
            onChange={setDifficulty}
            ctx={ctx}
          />
        </div>
        <div>
          <FieldLabel ctx={ctx}>Exercise type</FieldLabel>
          <Input
            ctx={ctx}
            value={exerciseType}
            onChange={(e) => setExerciseType(e.target.value)}
          />
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
        <div className="flex items-center gap-2">
          <Switch
            value={isCapstone}
            onToggle={() => setIsCapstone(!isCapstone)}
            label="Capstone"
          />
          <span style={{ fontSize: 12, color: ctx.ink }}>Capstone</span>
        </div>
        <div>
          <FieldLabel ctx={ctx}>Pass score</FieldLabel>
          <Input
            ctx={ctx}
            type="number"
            value={passScore}
            onChange={(e) => setPassScore(Number(e.target.value))}
          />
        </div>
        <div>
          <FieldLabel ctx={ctx}>Due at</FieldLabel>
          <Input
            ctx={ctx}
            type="datetime-local"
            value={dueAt}
            onChange={(e) => setDueAt(e.target.value)}
          />
        </div>
        <div>
          <FieldLabel ctx={ctx}>Points</FieldLabel>
          <Input
            ctx={ctx}
            type="number"
            value={points}
            onChange={(e) => setPoints(Number(e.target.value))}
          />
        </div>
      </div>
      <div>
        <FieldLabel ctx={ctx}>GitHub template URL</FieldLabel>
        <Input
          ctx={ctx}
          mono
          value={githubUrl}
          onChange={(e) => setGithubUrl(e.target.value)}
        />
      </div>
      <div>
        <FieldLabel ctx={ctx}>Starter code</FieldLabel>
        <TextArea
          ctx={ctx}
          mono
          rows={8}
          value={starter ?? ""}
          onChange={(e) => setStarter(e.target.value)}
        />
      </div>
      <div>
        <FieldLabel ctx={ctx}>Solution code</FieldLabel>
        <TextArea
          ctx={ctx}
          mono
          rows={8}
          value={solution ?? ""}
          onChange={(e) => setSolution(e.target.value)}
        />
      </div>

      <RubricEditor
        ctx={ctx}
        criteria={criteria}
        onChange={setCriteria}
      />
      <TestCasesEditor ctx={ctx} cases={tests} onChange={setTests} />

      <div className="flex items-center gap-2 pt-2">
        <PrimaryButton onClick={submit} disabled={saving}>
          {saving ? "Saving…" : mode === "create" ? "Create" : "Save changes"}
        </PrimaryButton>
        <GhostButton ctx={ctx} onClick={onCancel}>
          Cancel
        </GhostButton>
      </div>
    </div>
  );
}

function RubricEditor({
  ctx,
  criteria,
  onChange,
}: {
  ctx: StyleCtx;
  criteria: RubricCriterion[];
  onChange: (next: RubricCriterion[]) => void;
}) {
  const update = (idx: number, patch: Partial<RubricCriterion>) => {
    onChange(criteria.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
  };
  const remove = (idx: number) =>
    onChange(criteria.filter((_, i) => i !== idx));
  const add = () =>
    onChange([...criteria, { name: "", weight: 1, description: "" }]);

  return (
    <div
      style={{
        border: `1px solid ${ctx.line}`,
        borderRadius: 8,
        padding: 12,
        background: ctx.isDark ? "rgba(0,0,0,0.15)" : "rgba(255,255,255,0.4)",
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <FieldLabel ctx={ctx}>Rubric criteria</FieldLabel>
        <GhostButton ctx={ctx} onClick={add}>
          + Add criterion
        </GhostButton>
      </div>
      {criteria.length === 0 ? (
        <p style={{ fontSize: 12, color: ctx.muted }}>No criteria yet.</p>
      ) : (
        <div className="space-y-2">
          {criteria.map((c, idx) => (
            <div
              key={idx}
              className="grid grid-cols-12 gap-2 items-center"
            >
              <div className="col-span-3">
                <Input
                  ctx={ctx}
                  value={c.name}
                  placeholder="Name"
                  onChange={(e) => update(idx, { name: e.target.value })}
                />
              </div>
              <div className="col-span-2">
                <Input
                  ctx={ctx}
                  type="number"
                  min={1}
                  max={10}
                  value={c.weight}
                  onChange={(e) =>
                    update(idx, { weight: Number(e.target.value) })
                  }
                />
              </div>
              <div className="col-span-6">
                <Input
                  ctx={ctx}
                  value={c.description ?? ""}
                  placeholder="Description"
                  onChange={(e) =>
                    update(idx, { description: e.target.value })
                  }
                />
              </div>
              <div className="col-span-1 flex justify-end">
                <IconBtn
                  ctx={ctx}
                  danger
                  onClick={() => remove(idx)}
                  ariaLabel="Remove criterion"
                >
                  <X size={13} />
                </IconBtn>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TestCasesEditor({
  ctx,
  cases,
  onChange,
}: {
  ctx: StyleCtx;
  cases: TestCase[];
  onChange: (next: TestCase[]) => void;
}) {
  const update = (idx: number, patch: Partial<TestCase>) => {
    onChange(cases.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
  };
  const remove = (idx: number) => onChange(cases.filter((_, i) => i !== idx));
  const add = () =>
    onChange([
      ...cases,
      { name: "", input: "", expected_output: "", hidden: false },
    ]);

  return (
    <div
      style={{
        border: `1px solid ${ctx.line}`,
        borderRadius: 8,
        padding: 12,
        background: ctx.isDark ? "rgba(0,0,0,0.15)" : "rgba(255,255,255,0.4)",
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <FieldLabel ctx={ctx}>Test cases</FieldLabel>
        <GhostButton ctx={ctx} onClick={add}>
          + Add test case
        </GhostButton>
      </div>
      {cases.length === 0 ? (
        <p style={{ fontSize: 12, color: ctx.muted }}>No test cases yet.</p>
      ) : (
        <div className="space-y-3">
          {cases.map((tc, idx) => (
            <div
              key={idx}
              style={{
                border: `1px solid ${ctx.line}`,
                borderRadius: 6,
                padding: 8,
              }}
            >
              <div className="grid grid-cols-12 gap-2 items-start">
                <div className="col-span-4">
                  <Input
                    ctx={ctx}
                    value={tc.name}
                    placeholder="Name"
                    onChange={(e) => update(idx, { name: e.target.value })}
                  />
                </div>
                <div className="col-span-4">
                  <TextArea
                    ctx={ctx}
                    mono
                    rows={2}
                    value={tc.input}
                    placeholder="Input"
                    onChange={(e) => update(idx, { input: e.target.value })}
                  />
                </div>
                <div className="col-span-3">
                  <TextArea
                    ctx={ctx}
                    mono
                    rows={2}
                    value={tc.expected_output}
                    placeholder="Expected output"
                    onChange={(e) =>
                      update(idx, { expected_output: e.target.value })
                    }
                  />
                </div>
                <div className="col-span-1 flex flex-col gap-1 items-center">
                  <label
                    style={{
                      fontSize: 10,
                      color: ctx.muted,
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={tc.hidden}
                      onChange={(e) =>
                        update(idx, { hidden: e.target.checked })
                      }
                    />
                    Hidden
                  </label>
                  <IconBtn
                    ctx={ctx}
                    danger
                    onClick={() => remove(idx)}
                    ariaLabel="Remove test case"
                  >
                    <X size={13} />
                  </IconBtn>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// MCQs TAB
// ============================================================

function MCQsTab({ courseId, ctx }: { courseId: string; ctx: StyleCtx }) {
  const lessonsQ = useAdminCourseLessons(courseId);
  const lessons = useMemo(
    () => [...(lessonsQ.data?.items ?? [])].sort((a, b) => a.order - b.order),
    [lessonsQ.data],
  );
  const [selectedLesson, setSelectedLesson] = useState<string>("");

  useEffect(() => {
    if (!selectedLesson && lessons.length) {
      setSelectedLesson(lessons[0].id);
    }
  }, [lessons, selectedLesson]);

  return (
    <div className="space-y-4">
      <LessonPicker
        lessons={lessons}
        value={selectedLesson}
        onChange={setSelectedLesson}
        ctx={ctx}
      />
      {selectedLesson ? (
        <MCQList lessonId={selectedLesson} courseId={courseId} ctx={ctx} />
      ) : (
        <EmptyState text="Add a lesson first to create questions." ctx={ctx} />
      )}
    </div>
  );
}

function MCQList({
  lessonId,
  courseId,
  ctx,
}: {
  lessonId: string;
  courseId: string;
  ctx: StyleCtx;
}) {
  const q = useAdminLessonMCQs(lessonId);
  const createMut = useCreateMCQ();
  const updateMut = useUpdateMCQ();
  const deleteMut = useDeleteMCQ();
  const [creating, setCreating] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const items = q.data?.items ?? [];

  return (
    <div className="space-y-3">
      <SectionHeader
        title="Question bank"
        ctx={ctx}
        action={
          !creating ? (
            <PrimaryButton onClick={() => setCreating(true)}>
              + New question
            </PrimaryButton>
          ) : null
        }
      />

      {creating ? (
        <Card ctx={ctx} style={{ padding: 16 }}>
          <MCQForm
            ctx={ctx}
            mode="create"
            onCancel={() => setCreating(false)}
            onSubmit={async (body) => {
              try {
                await createMut.mutateAsync({ lessonId, courseId, body });
                toast.success("Question created.");
                setCreating(false);
              } catch (err) {
                showErrorToast(err, undefined);
              }
            }}
          />
        </Card>
      ) : null}

      {q.isLoading ? (
        <EmptyState text="Loading questions…" ctx={ctx} />
      ) : items.length === 0 && !creating ? (
        <EmptyState text="No questions for this lesson yet." ctx={ctx} />
      ) : (
        <div className="space-y-2">
          {items.map((m) => (
            <Card key={m.id} ctx={ctx}>
              <div
                className="flex items-start gap-3 px-4 py-3 cursor-pointer"
                onClick={() =>
                  setExpandedId(expandedId === m.id ? null : m.id)
                }
              >
                <div className="flex-1 min-w-0">
                  <div
                    style={{
                      fontSize: 13,
                      color: ctx.ink,
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                    }}
                  >
                    {m.question}
                  </div>
                  <div className="flex items-center gap-2 mt-1.5">
                    <Pill
                      bg={
                        m.difficulty === "hard"
                          ? "#d96252"
                          : m.difficulty === "medium"
                            ? "#d6a54d"
                            : "#1D9E75"
                      }
                      color="#fff"
                    >
                      {m.difficulty}
                    </Pill>
                    {(m.tags ?? []).map((t) => (
                      <Pill
                        key={t}
                        bg={ctx.isDark ? "rgba(255,255,255,0.06)" : "#efe9d8"}
                        color={ctx.muted}
                      >
                        {t}
                      </Pill>
                    ))}
                  </div>
                </div>
                <div
                  className="flex items-center gap-2"
                  onClick={(e) => e.stopPropagation()}
                >
                  <IconBtn
                    ctx={ctx}
                    onClick={() =>
                      setExpandedId(expandedId === m.id ? null : m.id)
                    }
                    ariaLabel="Edit question"
                  >
                    <Pencil size={13} />
                  </IconBtn>
                  <IconBtn
                    ctx={ctx}
                    danger
                    onClick={async (e) => {
                      e.stopPropagation();
                      if (!window.confirm("Delete this question?")) return;
                      try {
                        await deleteMut.mutateAsync({
                          id: m.id,
                          lessonId,
                          courseId,
                        });
                        toast.success("Question deleted.");
                      } catch (err) {
                        showErrorToast(err, undefined);
                      }
                    }}
                    ariaLabel="Delete question"
                  >
                    <Trash2 size={13} />
                  </IconBtn>
                </div>
              </div>
              {expandedId === m.id ? (
                <div
                  style={{
                    borderTop: `1px solid ${ctx.line}`,
                    padding: 16,
                  }}
                >
                  <MCQForm
                    ctx={ctx}
                    mode="edit"
                    initial={m}
                    onCancel={() => setExpandedId(null)}
                    onSubmit={async (patch) => {
                      try {
                        await updateMut.mutateAsync({
                          id: m.id,
                          lessonId,
                          courseId,
                          patch,
                        });
                        toast.success("Question updated.");
                        setExpandedId(null);
                      } catch (err) {
                        showErrorToast(err, undefined);
                      }
                    }}
                  />
                </div>
              ) : null}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function MCQForm({
  ctx,
  mode,
  initial,
  onSubmit,
  onCancel,
}: {
  ctx: StyleCtx;
  mode: "create" | "edit";
  initial?: AdminMCQRead;
  onSubmit: (body: AdminMCQCreate & AdminMCQUpdate) => Promise<void>;
  onCancel: () => void;
}) {
  const [question, setQuestion] = useState(initial?.question ?? "");
  const [optA, setOptA] = useState(initial?.options?.A ?? "");
  const [optB, setOptB] = useState(initial?.options?.B ?? "");
  const [optC, setOptC] = useState(initial?.options?.C ?? "");
  const [optD, setOptD] = useState(initial?.options?.D ?? "");
  const [correct, setCorrect] = useState(initial?.correct_answer ?? "A");
  const [explanation, setExplanation] = useState(initial?.explanation ?? "");
  const [difficulty, setDifficulty] = useState(initial?.difficulty ?? "medium");
  const [tagsStr, setTagsStr] = useState((initial?.tags ?? []).join(", "));
  const [saving, setSaving] = useState(false);

  const availableOptions: { key: string; value: string }[] = [
    { key: "A", value: optA },
    { key: "B", value: optB },
    { key: "C", value: optC },
    { key: "D", value: optD },
  ].filter((o) => o.value.trim().length > 0);

  const submit = async () => {
    if (!question.trim()) {
      toast.error("Question text is required.");
      return;
    }
    if (availableOptions.length < 2) {
      toast.error("At least two options are required.");
      return;
    }
    if (!availableOptions.some((o) => o.key === correct)) {
      toast.error("Correct answer must reference a filled option.");
      return;
    }
    const options: Record<string, string> = {};
    for (const o of availableOptions) options[o.key] = o.value.trim();
    const tags = tagsStr
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    setSaving(true);
    try {
      await onSubmit({
        question: question.trim(),
        options,
        correct_answer: correct,
        explanation: explanation || undefined,
        difficulty,
        tags: tags.length ? tags : undefined,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <div>
        <FieldLabel ctx={ctx}>Question</FieldLabel>
        <TextArea
          ctx={ctx}
          rows={3}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <FieldLabel ctx={ctx}>Option A</FieldLabel>
          <Input ctx={ctx} value={optA} onChange={(e) => setOptA(e.target.value)} />
        </div>
        <div>
          <FieldLabel ctx={ctx}>Option B</FieldLabel>
          <Input ctx={ctx} value={optB} onChange={(e) => setOptB(e.target.value)} />
        </div>
        <div>
          <FieldLabel ctx={ctx}>Option C (optional)</FieldLabel>
          <Input ctx={ctx} value={optC} onChange={(e) => setOptC(e.target.value)} />
        </div>
        <div>
          <FieldLabel ctx={ctx}>Option D (optional)</FieldLabel>
          <Input ctx={ctx} value={optD} onChange={(e) => setOptD(e.target.value)} />
        </div>
      </div>
      <div>
        <FieldLabel ctx={ctx}>Correct answer</FieldLabel>
        <div className="flex items-center gap-3">
          {availableOptions.map((o) => (
            <label
              key={o.key}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                fontSize: 13,
                color: ctx.ink,
              }}
            >
              <input
                type="radio"
                name="correct-answer"
                value={o.key}
                checked={correct === o.key}
                onChange={() => setCorrect(o.key)}
              />
              {o.key}
            </label>
          ))}
        </div>
      </div>
      <div>
        <FieldLabel ctx={ctx}>Explanation</FieldLabel>
        <TextArea
          ctx={ctx}
          rows={2}
          value={explanation ?? ""}
          onChange={(e) => setExplanation(e.target.value)}
        />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <FieldLabel ctx={ctx}>Difficulty</FieldLabel>
          <DifficultyPills
            value={difficulty}
            onChange={setDifficulty}
            ctx={ctx}
          />
        </div>
        <div>
          <FieldLabel ctx={ctx}>Tags (comma-separated)</FieldLabel>
          <Input
            ctx={ctx}
            value={tagsStr}
            onChange={(e) => setTagsStr(e.target.value)}
            placeholder="rag, embeddings, vectors"
          />
        </div>
      </div>
      <div className="flex items-center gap-2 pt-2">
        <PrimaryButton onClick={submit} disabled={saving}>
          {saving ? "Saving…" : mode === "create" ? "Create" : "Save changes"}
        </PrimaryButton>
        <GhostButton ctx={ctx} onClick={onCancel}>
          Cancel
        </GhostButton>
      </div>
    </div>
  );
}

// ============================================================
// SETTINGS TAB
// ============================================================

function SettingsTab({
  courseId,
  initial,
  onSaved,
  ctx,
}: {
  courseId: string;
  initial: {
    title: string;
    slug: string;
    difficulty: string;
    price_cents: number;
    is_published: boolean;
  } | null;
  onSaved: () => void;
  ctx: StyleCtx;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [slug, setSlug] = useState(initial?.slug ?? "");
  const [description, setDescription] = useState("");
  const [difficulty, setDifficulty] = useState(initial?.difficulty ?? "beginner");
  const [priceDollars, setPriceDollars] = useState(
    initial ? (initial.price_cents / 100).toFixed(2) : "0",
  );
  const [currency, setCurrency] = useState("USD");
  const [isFeatured, setIsFeatured] = useState(false);
  const [isPublished, setIsPublished] = useState(initial?.is_published ?? false);
  const [saving, setSaving] = useState(false);
  const [loadedDetail, setLoadedDetail] = useState(false);

  useEffect(() => {
    if (initial && !title) {
      setTitle(initial.title);
      setSlug(initial.slug);
      setDifficulty(initial.difficulty);
      setPriceDollars((initial.price_cents / 100).toFixed(2));
      setIsPublished(initial.is_published);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  useEffect(() => {
    if (loadedDetail) return;
    let active = true;
    (async () => {
      try {
        const c = await api.get<{
          title?: string;
          slug?: string;
          description?: string | null;
          difficulty?: string;
          price_cents?: number;
          is_published?: boolean;
          is_featured?: boolean;
        }>(`/api/v1/admin/courses/${courseId}`);
        if (!active) return;
        if (typeof c.title === "string") setTitle(c.title);
        if (typeof c.slug === "string") setSlug(c.slug);
        if (typeof c.description === "string") setDescription(c.description);
        if (typeof c.difficulty === "string") setDifficulty(c.difficulty);
        if (typeof c.price_cents === "number")
          setPriceDollars((c.price_cents / 100).toFixed(2));
        if (typeof c.is_published === "boolean") setIsPublished(c.is_published);
        if (typeof c.is_featured === "boolean") setIsFeatured(c.is_featured);
        setLoadedDetail(true);
      } catch {
        // ignore — fall back to summary
      }
    })();
    return () => {
      active = false;
    };
  }, [courseId, loadedDetail]);

  const submit = async () => {
    if (!title.trim()) {
      toast.error("Title is required.");
      return;
    }
    const cents = Math.round(Number(priceDollars) * 100);
    if (!Number.isFinite(cents) || cents < 0) {
      toast.error("Price must be a positive number.");
      return;
    }
    setSaving(true);
    try {
      await api.patch(`/api/v1/admin/courses/${courseId}`, {
        title: title.trim(),
        slug: slug.trim() || undefined,
        description: description || null,
        difficulty,
        price_cents: cents,
        is_published: isPublished,
        is_featured: isFeatured,
      });
      toast.success("Settings saved.");
      onSaved();
    } catch (err) {
      showErrorToast(err, undefined);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <SectionHeader title="Course settings" ctx={ctx} />
      <Card ctx={ctx} style={{ padding: 20 }}>
        <div className="space-y-3">
          <div>
            <FieldLabel ctx={ctx}>Title</FieldLabel>
            <Input
              ctx={ctx}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              style={{ fontSize: 16 }}
            />
          </div>
          <div>
            <FieldLabel ctx={ctx}>Slug</FieldLabel>
            <Input
              ctx={ctx}
              mono
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
            />
          </div>
          <div>
            <FieldLabel ctx={ctx}>Description (markdown)</FieldLabel>
            <TextArea
              ctx={ctx}
              rows={6}
              value={description ?? ""}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
            <div>
              <FieldLabel ctx={ctx}>Difficulty</FieldLabel>
              <DifficultyPills
                value={difficulty}
                onChange={setDifficulty}
                ctx={ctx}
                options={COURSE_DIFFICULTIES}
              />
            </div>
            <div>
              <FieldLabel ctx={ctx}>Price (in dollars)</FieldLabel>
              <Input
                ctx={ctx}
                type="number"
                step="0.01"
                value={priceDollars}
                onChange={(e) => setPriceDollars(e.target.value)}
              />
            </div>
            <div>
              <FieldLabel ctx={ctx}>Currency</FieldLabel>
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                style={{
                  width: "100%",
                  background: ctx.isDark ? "rgba(0,0,0,0.25)" : "#fff",
                  border: `1px solid ${ctx.line}`,
                  borderRadius: 6,
                  padding: "8px 10px",
                  fontSize: 13,
                  color: ctx.ink,
                }}
              >
                <option value="USD">USD</option>
                <option value="INR">INR</option>
              </select>
            </div>
          </div>
          <div className="flex items-center gap-6 pt-2">
            <div className="flex items-center gap-2">
              <Switch
                value={isFeatured}
                onToggle={() => setIsFeatured(!isFeatured)}
                label="Featured"
              />
              <span style={{ fontSize: 13, color: ctx.ink }}>Featured</span>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                value={isPublished}
                onToggle={() => setIsPublished(!isPublished)}
                label="Published"
              />
              <span style={{ fontSize: 13, color: ctx.ink }}>Published</span>
            </div>
          </div>
          <div className="pt-2">
            <PrimaryButton onClick={submit} disabled={saving}>
              {saving ? "Saving…" : "Save settings"}
            </PrimaryButton>
          </div>
        </div>
      </Card>
    </div>
  );
}

// ============================================================
// ANALYTICS TAB
// ============================================================

function AnalyticsTab({
  courseId,
  ctx,
}: {
  courseId: string;
  ctx: StyleCtx;
}) {
  const q = useCourseAnalytics(courseId);
  const a = q.data;

  if (q.isLoading) return <EmptyState text="Loading analytics…" ctx={ctx} />;
  if (q.isError || !a)
    return (
      <EmptyState
        text={`Failed to load analytics: ${(q.error as Error)?.message ?? "unknown"}`}
        ctx={ctx}
      />
    );

  const completionPct = Math.round(a.completion_rate * 100);
  const confusionPct = Math.round(a.avg_confusion_rate * 100);
  const avgProgPct = Math.round(a.avg_progress_pct);
  const deltaSign = a.enrollments_delta_pct > 0 ? "+" : "";

  return (
    <div className="space-y-5">
      {/* Health Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricTile
          ctx={ctx}
          label="Enrolled"
          value={String(a.enrolled_count)}
        />
        <MetricTile
          ctx={ctx}
          label="Completion"
          value={`${completionPct}%`}
          sub={`${a.completion_count} / ${a.enrolled_count}`}
        />
        <MetricTile ctx={ctx} label="Avg progress" value={`${avgProgPct}%`} />
        <MetricTile
          ctx={ctx}
          label="Confusion rate"
          value={`${confusionPct}%`}
          accent={
            confusionPct > 30 ? "#d96252" : confusionPct > 15 ? "#d6a54d" : undefined
          }
        />
      </div>

      <div style={{ fontSize: 12, color: ctx.muted }}>
        {a.lesson_count} lessons · {a.exercise_count} exercises ·{" "}
        {a.mcq_count} MCQs
      </div>

      {/* Enrollment trend */}
      <Card ctx={ctx} style={{ padding: 16 }}>
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: ctx.muted,
            marginBottom: 8,
          }}
        >
          Enrollment trend
        </div>
        <div style={{ fontSize: 14, color: ctx.ink }}>
          Last 30d:{" "}
          <strong>{a.enrollments_last_30d}</strong> · Prior 30d:{" "}
          <strong>{a.enrollments_prior_30d}</strong> · Delta:{" "}
          <span
            style={{
              color:
                a.enrollments_delta_pct >= 0 ? "#1D9E75" : "#d96252",
              fontWeight: 700,
            }}
          >
            {deltaSign}
            {a.enrollments_delta_pct.toFixed(1)}%
          </span>
        </div>
      </Card>

      {/* Top students */}
      <Card ctx={ctx} style={{ padding: 16 }}>
        <SectionHeader title="Top students" ctx={ctx} />
        {a.top_students.length === 0 ? (
          <p style={{ fontSize: 13, color: ctx.muted, marginTop: 8 }}>
            No students enrolled yet.
          </p>
        ) : (
          <table className="w-full text-sm mt-3">
            <thead>
              <tr style={{ borderBottom: `1px solid ${ctx.line}` }}>
                <Th2>Name</Th2>
                <Th2 align="right">Progress</Th2>
                <Th2>Last active</Th2>
                <Th2 align="center">Done</Th2>
              </tr>
            </thead>
            <tbody>
              {a.top_students.map((s) => (
                <tr
                  key={s.student_id}
                  style={{ borderBottom: `1px solid ${ctx.line}` }}
                >
                  <td className="px-2 py-2" style={{ color: ctx.ink }}>
                    <div style={{ fontWeight: 600 }}>{s.name}</div>
                    <div style={{ fontSize: 11, color: ctx.muted }}>
                      {s.email}
                    </div>
                  </td>
                  <td
                    className="px-2 py-2 text-right"
                    style={{ fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace" }}
                  >
                    {Math.round(s.progress_pct)}%
                  </td>
                  <td
                    className="px-2 py-2"
                    style={{ fontSize: 12, color: ctx.muted }}
                  >
                    {s.last_active_at
                      ? new Date(s.last_active_at).toLocaleDateString()
                      : "—"}
                  </td>
                  <td className="px-2 py-2 text-center">
                    {s.completed_at ? "✓" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Recent feedback */}
      <Card ctx={ctx} style={{ padding: 16 }}>
        <SectionHeader title="Recent feedback" ctx={ctx} />
        {a.recent_feedback.length === 0 ? (
          <p style={{ fontSize: 13, color: ctx.muted, marginTop: 8 }}>
            No feedback for this course yet.
          </p>
        ) : (
          <ul className="space-y-2 mt-3">
            {a.recent_feedback.map((f) => (
              <li
                key={f.id}
                className="flex items-start gap-3"
                style={{
                  borderTop: `1px solid ${ctx.line}`,
                  paddingTop: 8,
                }}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 999,
                    marginTop: 6,
                    background:
                      f.sentiment === "negative"
                        ? "#d96252"
                        : f.sentiment === "positive"
                          ? "#1D9E75"
                          : "#d6a54d",
                  }}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    {f.category ? (
                      <Pill bg={ctx.isDark ? "rgba(255,255,255,0.06)" : "#efe9d8"} color={ctx.muted}>
                        {f.category}
                      </Pill>
                    ) : null}
                    {f.route ? (
                      <code
                        style={{
                          fontSize: 11,
                          color: ctx.muted,
                          fontFamily:
                            "var(--font-jetbrains-mono), ui-monospace, monospace",
                        }}
                      >
                        {f.route}
                      </code>
                    ) : null}
                    <span style={{ fontSize: 11, color: ctx.muted }}>
                      {new Date(f.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      color: ctx.ink,
                      marginTop: 4,
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                    }}
                  >
                    {f.body}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Agent activity */}
      <Card ctx={ctx} style={{ padding: 16 }}>
        <SectionHeader title="Recent agent activity" ctx={ctx} />
        {a.recent_agent_activity.length === 0 ? (
          <p style={{ fontSize: 13, color: ctx.muted, marginTop: 8 }}>
            No agent activity yet.
          </p>
        ) : (
          <ul className="space-y-2 mt-3">
            {a.recent_agent_activity.map((act) => (
              <li
                key={act.action_id}
                className="flex items-start gap-3"
                style={{
                  borderTop: `1px solid ${ctx.line}`,
                  paddingTop: 8,
                }}
              >
                <Pill bg="#1D9E75" color="#fff">
                  {act.agent_name}
                </Pill>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span style={{ fontSize: 12, color: ctx.ink, fontWeight: 600 }}>
                      {act.student_name ?? act.student_id}
                    </span>
                    {act.evaluation_score != null ? (
                      <Pill
                        bg={
                          act.evaluation_score >= 0.7
                            ? "#1D9E75"
                            : act.evaluation_score >= 0.4
                              ? "#d6a54d"
                              : "#d96252"
                        }
                        color="#fff"
                      >
                        {Math.round(act.evaluation_score * 100)}
                      </Pill>
                    ) : null}
                    {act.has_error ? (
                      <Pill bg="#d96252" color="#fff">
                        error
                      </Pill>
                    ) : null}
                    <span style={{ fontSize: 11, color: ctx.muted }}>
                      {new Date(act.created_at).toLocaleString()}
                    </span>
                  </div>
                  {act.input_preview ? (
                    <div
                      style={{
                        fontSize: 12,
                        color: ctx.muted,
                        marginTop: 4,
                        display: "-webkit-box",
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: "vertical",
                        overflow: "hidden",
                      }}
                    >
                      {act.input_preview}
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function MetricTile({
  ctx,
  label,
  value,
  sub,
  accent,
}: {
  ctx: StyleCtx;
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <Card ctx={ctx} style={{ padding: 16 }}>
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: ctx.muted,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: "var(--font-fraunces), Georgia, serif",
          fontSize: 26,
          fontWeight: 500,
          letterSpacing: "-0.03em",
          color: accent ?? ctx.ink,
          marginTop: 4,
        }}
      >
        {value}
      </div>
      {sub ? (
        <div style={{ fontSize: 11, color: ctx.muted, marginTop: 2 }}>
          {sub}
        </div>
      ) : null}
    </Card>
  );
}

function Th2({
  children,
  align = "left",
}: {
  children?: React.ReactNode;
  align?: "left" | "right" | "center";
}) {
  return (
    <th
      className="px-2 py-2"
      style={{
        textAlign: align,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        opacity: 0.6,
      }}
    >
      {children}
    </th>
  );
}
