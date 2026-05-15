"use client";

/**
 * Admin lesson assets editor — CRUD for the LessonAsset rows that
 * power the student lesson player at /path/[courseId].
 *
 * Designed as a focused stand-alone page rather than a tab inside the
 * existing 700-line lesson editor — keeps the new asset surface
 * reviewable in isolation.
 *
 * Convention used everywhere on this page:
 *   - storage_ref is admin-pasted: Mux playback_id for video, R2 key
 *     for notebooks, GitHub URL for git_repo. Backend never auto-uploads.
 *   - Sync-from-legacy button surfaces the youtube_video_id → video
 *     asset bridge so admins don't re-enter every existing lesson.
 */

import { use, useMemo, useState } from "react";
import Link from "next/link";
import {
  useAdminLessonAssets,
  useCreateLessonAsset,
  useDeleteLessonAsset,
  useSyncLegacyAssets,
  useUpdateLessonAsset,
} from "@/lib/hooks/use-admin-content";
import type {
  AdminAssetCreate,
  AdminAssetKind,
  AdminAssetOut,
} from "@/lib/admin-content-api";

interface Params {
  lessonId: string;
}

const KIND_OPTIONS: ReadonlyArray<{
  value: AdminAssetKind;
  label: string;
  hint: string;
}> = [
  {
    value: "video",
    label: "Video",
    hint: "storage_ref = Mux playback_id (e.g. 'abc123def456'). Upload to Mux outside the app first.",
  },
  {
    value: "learning_notebook",
    label: "Learning notebook",
    hint: "storage_ref = R2 object key (e.g. 'courses/data-analyst/lesson-3/intro.ipynb'). Upload .ipynb to R2 first.",
  },
  {
    value: "practice_notebook",
    label: "Practice notebook",
    hint: "storage_ref = R2 object key for the practice .ipynb.",
  },
  {
    value: "capstone_brief",
    label: "Capstone brief",
    hint: "storage_ref = R2 object key for the markdown brief.",
  },
  {
    value: "reading",
    label: "Reading",
    hint: "storage_ref = R2 object key for the markdown reading.",
  },
  {
    value: "git_repo",
    label: "Git repo",
    hint: "storage_ref = public GitHub URL (e.g. 'https://github.com/org/repo'). Player renders 'Open in GitHub'.",
  },
];

function placeholderForKind(kind: AdminAssetKind): string {
  return KIND_OPTIONS.find((k) => k.value === kind)?.hint ?? "";
}

export default function AdminLessonAssetsPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { lessonId } = use(params);
  const { data: assets = [], isLoading, error } = useAdminLessonAssets(lessonId);
  const createMut = useCreateLessonAsset(lessonId);
  const updateMut = useUpdateLessonAsset(lessonId);
  const deleteMut = useDeleteLessonAsset(lessonId);
  const syncMut = useSyncLegacyAssets(lessonId);

  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const sorted = useMemo(
    () => [...assets].sort((a, b) => a.order - b.order),
    [assets],
  );

  const handleSync = () => {
    syncMut.mutate(undefined, {
      onSuccess: (res) => {
        const created = res.created_assets.length;
        const skipped = res.skipped_reasons.length;
        if (created > 0) {
          alert(`Created ${created} asset(s). Refreshing list.`);
        } else if (skipped > 0) {
          alert(`Nothing to sync:\n• ${res.skipped_reasons.join("\n• ")}`);
        }
      },
    });
  };

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
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
            Lesson assets
          </h1>
          <p className="text-muted-foreground text-[13px] leading-[1.58] mt-1">
            Lesson ID:{" "}
            <code className="text-[12px] bg-muted px-1.5 py-0.5 rounded">
              {lessonId}
            </code>
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="px-3 py-2 rounded-md text-[13px] font-semibold border border-line bg-transparent hover:bg-muted/50"
            onClick={handleSync}
            disabled={syncMut.isPending}
          >
            {syncMut.isPending ? "Syncing…" : "Sync from legacy"}
          </button>
          <button
            type="button"
            className="px-3 py-2 rounded-md text-[13px] font-semibold bg-primary text-primary-foreground hover:opacity-90"
            onClick={() => setShowCreate(true)}
          >
            + Add asset
          </button>
        </div>
      </div>

      {isLoading && <div className="text-muted-foreground">Loading…</div>}
      {error && (
        <div
          role="alert"
          className="border border-rose-300 bg-rose-50 text-rose-900 p-4 rounded-md"
        >
          Couldn’t load assets — {String(error.message)}
        </div>
      )}

      {showCreate && (
        <AssetForm
          mode="create"
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

      {sorted.length === 0 && !isLoading && (
        <div className="border border-dashed border-line rounded-md p-8 text-center text-muted-foreground">
          No assets yet. Use “+ Add asset” to attach a video, notebook, or
          repo. Or click “Sync from legacy” to bootstrap from the lesson’s
          existing youtube_video_id.
        </div>
      )}

      <ul className="space-y-3">
        {sorted.map((asset) => (
          <li
            key={asset.id}
            className="border border-line rounded-md bg-background"
          >
            {editingId === asset.id ? (
              <AssetForm
                mode="edit"
                initial={asset}
                submitting={updateMut.isPending}
                onCancel={() => setEditingId(null)}
                onSubmit={(body) => {
                  updateMut.mutate(
                    { assetId: asset.id, body },
                    {
                      onSuccess: () => setEditingId(null),
                      onError: (err) => alert(`Update failed: ${err.message}`),
                    },
                  );
                }}
              />
            ) : (
              <AssetRow
                asset={asset}
                onEdit={() => setEditingId(asset.id)}
                onDelete={() => {
                  if (
                    confirm(
                      `Delete "${asset.title}"? This is permanent and the player will no longer show it.`,
                    )
                  ) {
                    deleteMut.mutate(asset.id, {
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

function AssetRow({
  asset,
  onEdit,
  onDelete,
}: {
  asset: AdminAssetOut;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="p-4 flex items-start justify-between gap-4">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10px] font-bold tracking-[0.2em] uppercase text-primary">
            {asset.kind.replace(/_/g, " ")}
          </span>
          <span className="text-[11px] font-bold leading-none px-2 py-1 rounded-full bg-muted text-foreground">
            order {asset.order}
          </span>
          {!asset.is_published && (
            <span className="text-[11px] font-bold leading-none px-2 py-1 rounded-full bg-amber-100 text-amber-800">
              Draft
            </span>
          )}
        </div>
        <div className="mt-1 font-semibold">{asset.title}</div>
        {asset.description && (
          <div className="text-sm text-muted-foreground mt-0.5">
            {asset.description}
          </div>
        )}
        <div className="mt-2 text-[12px] font-mono break-all text-muted-foreground">
          {asset.storage_ref}
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
  initial?: AdminAssetOut;
  submitting: boolean;
  onSubmit: (body: AdminAssetCreate) => void;
  onCancel: () => void;
}

function AssetForm({ mode, initial, submitting, onSubmit, onCancel }: FormProps) {
  const [kind, setKind] = useState<AdminAssetKind>(initial?.kind ?? "video");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [storageRef, setStorageRef] = useState(initial?.storage_ref ?? "");
  const [order, setOrder] = useState(initial?.order ?? 0);
  const [duration, setDuration] = useState<number | "">(
    initial?.duration_seconds ?? "",
  );
  const [isPublished, setIsPublished] = useState(initial?.is_published ?? true);

  return (
    <form
      className="p-4 space-y-3 bg-muted/30"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          kind,
          title: title.trim(),
          description: description.trim() || null,
          storage_ref: storageRef.trim(),
          order: Number(order) || 0,
          duration_seconds: duration === "" ? null : Number(duration),
          is_published: isPublished,
        });
      }}
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="text-sm">
          <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
            Kind
          </span>
          <select
            className="w-full border border-line rounded px-2 py-1.5 bg-background"
            value={kind}
            onChange={(e) => setKind(e.target.value as AdminAssetKind)}
          >
            {KIND_OPTIONS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
            Order
          </span>
          <input
            type="number"
            className="w-full border border-line rounded px-2 py-1.5 bg-background"
            value={order}
            onChange={(e) => setOrder(Number(e.target.value))}
          />
        </label>
      </div>

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
          Description
        </span>
        <textarea
          className="w-full border border-line rounded px-2 py-1.5 bg-background"
          rows={2}
          value={description ?? ""}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>

      <label className="block text-sm">
        <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
          Storage ref
        </span>
        <input
          type="text"
          required
          maxLength={500}
          className="w-full border border-line rounded px-2 py-1.5 bg-background font-mono text-[12px]"
          value={storageRef}
          onChange={(e) => setStorageRef(e.target.value)}
        />
        <span className="block text-[12px] text-muted-foreground mt-1">
          {placeholderForKind(kind)}
        </span>
      </label>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="text-sm">
          <span className="block text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-1">
            Duration (seconds, optional)
          </span>
          <input
            type="number"
            min={0}
            className="w-full border border-line rounded px-2 py-1.5 bg-background"
            value={duration}
            onChange={(e) =>
              setDuration(e.target.value === "" ? "" : Number(e.target.value))
            }
          />
        </label>
        <label className="text-sm flex items-end gap-2 pb-1">
          <input
            type="checkbox"
            checked={isPublished}
            onChange={(e) => setIsPublished(e.target.checked)}
          />
          Published (visible to students)
        </label>
      </div>

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
            ? "Create asset"
            : "Save changes"}
        </button>
      </div>
    </form>
  );
}
