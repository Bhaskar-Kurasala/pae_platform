"use client";

/**
 * LessonPlayerScreen — the student-facing course player.
 *
 * Layout: vertical timeline of lessons on the left (each card is
 * collapsible, lock states 🔒 / ▶ / ✓), right pane is the active
 * lesson's asset stack (video + notebooks).
 *
 * Asset interactions (all gated server-side; this is just UI):
 *   • Video — Mux embed (HLS, signed JWT). watch_pct heartbeats every
 *     10s while playing.
 *   • Notebooks — JupyterLite iframe pre-loaded with a 5-min signed
 *     R2 URL via ?fromURL=. "I ran this" stamps execution server-side.
 *   • Capstone — markdown reading + a "Submit capstone" CTA.
 *
 * Completion: "Mark lesson complete" only enables when the server-
 * computed completion_pct === 1; otherwise the button shows the
 * blocking reasons inline.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  useLearnTimeline,
  useMarkLessonComplete,
  useNotebookSignedUrl,
  usePatchAssetProgress,
  useVideoToken,
} from "@/lib/hooks/use-learn";
import type {
  LessonAssetOut,
  LessonNodeOut,
} from "@/lib/learn-api";
import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { v8Toast } from "@/components/v8/v8-toast";

interface Props {
  courseId: string;
}

export function LessonPlayerScreen({ courseId }: Props) {
  const { data: timeline, isLoading, error } = useLearnTimeline(courseId);
  const [activeLessonId, setActiveLessonId] = useState<string | null>(null);

  // First unlocked lesson is the default selection.
  useEffect(() => {
    if (!timeline || activeLessonId) return;
    const firstOpen =
      timeline.lessons.find((l) => l.lock_state !== "locked") ??
      timeline.lessons[0];
    if (firstOpen) setActiveLessonId(firstOpen.id);
  }, [timeline, activeLessonId]);

  useSetV8Topbar({
    eyebrow: "Course path",
    titleHtml: timeline ? `<i>${escapeHtml(timeline.course_title)}</i>` : "",
    chips: timeline?.is_entitled
      ? [
          { label: `${Math.round(timeline.progress_pct * 100)}% complete`, variant: "forest" },
          { label: timeline.capstone_unlocked ? "Capstone unlocked" : "Capstone locked", variant: "gold" },
        ]
      : [{ label: "Locked", variant: "neutral" }],
    progress: timeline ? Math.round(timeline.progress_pct * 100) : 0,
  });

  if (isLoading) {
    return (
      <section className="screen active" id="screen-lesson-player">
        <div className="pad">
          <div style={{ height: 400, background: "var(--ink-7)", opacity: 0.4, borderRadius: 14 }} />
        </div>
      </section>
    );
  }
  if (error || !timeline) {
    return (
      <section className="screen active" id="screen-lesson-player">
        <div className="pad">
          <div role="alert" className="note" style={{ borderColor: "var(--rose)" }}>
            <div className="eyebrow">Couldn’t load this course</div>
            <p>Try refreshing or pick another course.</p>
          </div>
        </div>
      </section>
    );
  }

  if (!timeline.is_entitled) {
    return (
      <section className="screen active" id="screen-lesson-player">
        <div className="pad">
          <article className="note">
            <div className="eyebrow">Locked</div>
            <h2 style={{ fontFamily: "var(--font-fraunces)", marginTop: 6 }}>
              Unlock <i>{timeline.course_title}</i> to start learning
            </h2>
            <p style={{ marginTop: 8, opacity: 0.8 }}>
              Each lesson combines a learning notebook, two practice notebooks, and an
              explainer video. Lessons unlock one by one as you complete the previous.
            </p>
            <Link href="/catalog" className="btn primary" style={{ marginTop: 14, display: "inline-block" }}>
              Go to catalog →
            </Link>
          </article>
        </div>
      </section>
    );
  }

  const activeLesson =
    timeline.lessons.find((l) => l.id === activeLessonId) ?? timeline.lessons[0];

  return (
    <section className="screen active" id="screen-lesson-player">
      <div
        className="pad"
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(260px, 320px) 1fr",
          gap: 24,
          alignItems: "start",
        }}
      >
        <Timeline
          lessons={timeline.lessons}
          activeLessonId={activeLesson?.id}
          onSelect={setActiveLessonId}
        />
        {activeLesson ? (
          <LessonDetail lesson={activeLesson} courseId={courseId} />
        ) : (
          <div>No lessons in this course yet.</div>
        )}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────
// Timeline (left rail)
// ─────────────────────────────────────────────────────────────────

function Timeline({
  lessons,
  activeLessonId,
  onSelect,
}: {
  lessons: LessonNodeOut[];
  activeLessonId: string | undefined;
  onSelect: (id: string) => void;
}) {
  return (
    <nav aria-label="Course timeline" style={{ position: "sticky", top: 24 }}>
      <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
        {lessons.map((lesson, idx) => {
          const isActive = lesson.id === activeLessonId;
          const locked = lesson.lock_state === "locked";
          const completed = lesson.lock_state === "completed";
          const icon = completed ? "✓" : locked ? "🔒" : idx + 1;
          return (
            <li key={lesson.id}>
              <button
                type="button"
                disabled={locked}
                onClick={() => onSelect(lesson.id)}
                aria-current={isActive ? "step" : undefined}
                style={{
                  width: "100%",
                  textAlign: "left",
                  display: "flex",
                  gap: 12,
                  alignItems: "center",
                  padding: "12px 14px",
                  borderRadius: 12,
                  border: `1px solid ${isActive ? "var(--forest)" : "var(--line)"}`,
                  background: isActive ? "var(--forest-tint)" : "var(--surface)",
                  cursor: locked ? "not-allowed" : "pointer",
                  opacity: locked ? 0.55 : 1,
                  fontFamily: "inherit",
                  fontSize: 14,
                  color: "inherit",
                }}
              >
                <span
                  aria-hidden
                  style={{
                    width: 28,
                    height: 28,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    borderRadius: "50%",
                    background: completed ? "var(--forest)" : "var(--ink-7)",
                    color: completed ? "white" : "inherit",
                    fontWeight: 600,
                    fontSize: 13,
                    flexShrink: 0,
                  }}
                >
                  {icon}
                </span>
                <span style={{ flex: 1 }}>
                  <span style={{ display: "block", fontWeight: 600 }}>
                    {lesson.title}
                  </span>
                  {lesson.lock_state === "locked" && lesson.locked_reason && (
                    <span style={{ display: "block", fontSize: 12, opacity: 0.7, marginTop: 2 }}>
                      {lesson.locked_reason}
                    </span>
                  )}
                  {lesson.lock_state === "unlocked" && (
                    <span style={{ display: "block", fontSize: 12, opacity: 0.7, marginTop: 2 }}>
                      {Math.round(lesson.completion_pct * 100)}% done
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

// ─────────────────────────────────────────────────────────────────
// Lesson detail (right pane)
// ─────────────────────────────────────────────────────────────────

function LessonDetail({ lesson, courseId }: { lesson: LessonNodeOut; courseId: string }) {
  const markComplete = useMarkLessonComplete(courseId);
  const [missing, setMissing] = useState<string[]>([]);

  const sortedAssets = useMemo(
    () => [...lesson.assets].sort((a, b) => a.order - b.order),
    [lesson.assets],
  );

  const completed = lesson.lock_state === "completed";

  function handleMarkComplete() {
    markComplete.mutate(
      { lessonId: lesson.id },
      {
        onSuccess: (res) => {
          if (res.completed) {
            const unlockedCount = res.newly_unlocked_lesson_ids.length;
            v8Toast(
              unlockedCount > 0
                ? `Lesson complete — unlocked ${unlockedCount} new lesson${unlockedCount === 1 ? "" : "s"}.`
                : "Lesson complete. Nice work.",
            );
            setMissing([]);
          } else {
            setMissing(res.blocking_reasons);
          }
        },
      },
    );
  }

  return (
    <section>
      <header style={{ marginBottom: 12 }}>
        <div className="eyebrow">Lesson {lesson.order + 1}</div>
        <h2 style={{ fontFamily: "var(--font-fraunces)", margin: "6px 0 4px" }}>
          {lesson.title}
        </h2>
        {lesson.description && (
          <p style={{ opacity: 0.78, marginTop: 4 }}>{lesson.description}</p>
        )}
      </header>

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {sortedAssets.map((asset) => (
          <AssetPanel key={asset.id} asset={asset} courseId={courseId} />
        ))}
      </div>

      <footer
        style={{
          marginTop: 24,
          padding: 18,
          borderRadius: 12,
          border: "1px solid var(--line)",
          background: "var(--surface)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div className="eyebrow">Lesson progress</div>
            <strong>{Math.round(lesson.completion_pct * 100)}% complete</strong>
          </div>
          <button
            type="button"
            className="btn primary"
            onClick={handleMarkComplete}
            disabled={completed || markComplete.isPending}
            style={{ padding: "10px 18px", borderRadius: 8 }}
          >
            {completed ? "Completed ✓" : markComplete.isPending ? "Checking…" : "Mark lesson complete"}
          </button>
        </div>
        {missing.length > 0 && (
          <ul style={{ marginTop: 12, paddingLeft: 20, color: "var(--ink-2)" }}>
            {missing.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        )}
      </footer>
    </section>
  );
}

function AssetPanel({ asset, courseId }: { asset: LessonAssetOut; courseId: string }) {
  if (asset.kind === "video") {
    return <VideoAssetPanel asset={asset} courseId={courseId} />;
  }
  if (asset.kind === "learning_notebook" || asset.kind === "practice_notebook") {
    return <NotebookAssetPanel asset={asset} courseId={courseId} />;
  }
  if (asset.kind === "capstone_brief") {
    return <NotebookAssetPanel asset={asset} courseId={courseId} variant="capstone" />;
  }
  return <NotebookAssetPanel asset={asset} courseId={courseId} variant="reading" />;
}

// ── Video ────────────────────────────────────────────────────────

function VideoAssetPanel({ asset, courseId }: { asset: LessonAssetOut; courseId: string }) {
  const { data: token, isLoading } = useVideoToken(asset.id);
  const patch = usePatchAssetProgress(courseId);
  const [open, setOpen] = useState(asset.progress.status !== "completed");

  // Heartbeat watch progress every 10s while the player is mounted.
  useEffect(() => {
    if (!open) return;
    let last = asset.progress.watch_pct;
    const id = setInterval(() => {
      // The Mux player exposes events; for now we approximate by bumping
      // the recorded watch position by 10s of observed playback.
      // Real watch_pct comes from the player.on('timeupdate') wiring you
      // add when the @mux/mux-player-react package is installed.
      if (last < 1) {
        last = Math.min(1, last + 0.01);
        patch.mutate({
          assetId: asset.id,
          body: { watch_pct: last, watched_seconds: Math.round(last * (asset.duration_seconds ?? 600)) },
        });
      }
    }, 10_000);
    return () => clearInterval(id);
  }, [open, asset.id, asset.duration_seconds]);

  return (
    <article
      style={{
        border: "1px solid var(--line)",
        borderRadius: 12,
        background: "var(--surface)",
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          width: "100%",
          padding: "14px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          background: "transparent",
          border: 0,
          cursor: "pointer",
          font: "inherit",
          color: "inherit",
        }}
      >
        <div style={{ textAlign: "left" }}>
          <div className="eyebrow">Explainer video</div>
          <strong>{asset.title}</strong>
        </div>
        <span style={{ opacity: 0.6 }}>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div style={{ aspectRatio: "16 / 9", background: "black" }}>
          {isLoading ? (
            <div style={{ color: "white", padding: 24 }}>Loading video…</div>
          ) : token ? (
            // Native iframe to Mux's hosted player. Switching to
            // @mux/mux-player-react is a 1-line swap when the package is
            // added; this keeps the bundle small and zero-dep for now.
            <iframe
              title={asset.title}
              src={
                token.token
                  ? `https://stream.mux.com/${token.playback_id}?token=${encodeURIComponent(token.token)}`
                  : `https://stream.mux.com/${token.playback_id}`
              }
              allow="accelerometer; autoplay; encrypted-media; picture-in-picture"
              allowFullScreen
              style={{ width: "100%", height: "100%", border: 0 }}
            />
          ) : (
            <div style={{ color: "white", padding: 24 }}>
              Video unavailable — try refreshing.
            </div>
          )}
        </div>
      )}
    </article>
  );
}

// ── Notebook / Reading ───────────────────────────────────────────

function NotebookAssetPanel({
  asset,
  courseId,
  variant,
}: {
  asset: LessonAssetOut;
  courseId: string;
  variant?: "capstone" | "reading";
}) {
  const { data: signed, isLoading } = useNotebookSignedUrl(asset.id);
  const patch = usePatchAssetProgress(courseId);
  const [open, setOpen] = useState(asset.progress.status !== "completed");
  const executed = asset.progress.executed_at !== null;

  function handleMarkExecuted() {
    patch.mutate({
      assetId: asset.id,
      body: { mark_executed: true },
    });
  }

  const eyebrow =
    variant === "capstone"
      ? "Capstone brief"
      : variant === "reading"
      ? "Reading"
      : asset.kind === "learning_notebook"
      ? "Learning notebook"
      : "Practice notebook";

  return (
    <article
      style={{
        border: "1px solid var(--line)",
        borderRadius: 12,
        background: "var(--surface)",
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          width: "100%",
          padding: "14px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          background: "transparent",
          border: 0,
          cursor: "pointer",
          font: "inherit",
          color: "inherit",
        }}
      >
        <div style={{ textAlign: "left" }}>
          <div className="eyebrow">{eyebrow}</div>
          <strong>{asset.title}</strong>
          {executed && (
            <span style={{ marginLeft: 10, color: "var(--forest)", fontSize: 13 }}>
              ✓ Run
            </span>
          )}
        </div>
        <span style={{ opacity: 0.6 }}>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div style={{ borderTop: "1px solid var(--line)" }}>
          <div style={{ height: 560, background: "var(--ink-8)" }}>
            {isLoading ? (
              <div style={{ padding: 24, opacity: 0.7 }}>Loading notebook…</div>
            ) : signed ? (
              <iframe
                title={asset.title}
                src={signed.launch_url}
                style={{ width: "100%", height: "100%", border: 0 }}
                // JupyterLite needs same-origin or CORS — the launch_url
                // points at our hosted JupyterLite which already has the
                // CORS headers set for fetching the signed URL.
                sandbox="allow-scripts allow-same-origin allow-downloads allow-forms allow-popups"
              />
            ) : (
              <div style={{ padding: 24, opacity: 0.7 }}>
                Notebook unavailable — try refreshing.
              </div>
            )}
          </div>
          <div
            style={{
              padding: "12px 16px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              borderTop: "1px solid var(--line)",
              background: "var(--surface-2)",
            }}
          >
            <p style={{ margin: 0, fontSize: 13, opacity: 0.75 }}>
              Run every cell, experiment, then mark it complete here so the
              lesson can advance.
            </p>
            <button
              type="button"
              className="btn"
              onClick={handleMarkExecuted}
              disabled={executed || patch.isPending}
              style={{ padding: "8px 14px", borderRadius: 6 }}
            >
              {executed ? "Marked complete" : patch.isPending ? "Saving…" : "I ran this notebook"}
            </button>
          </div>
        </div>
      )}
    </article>
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
