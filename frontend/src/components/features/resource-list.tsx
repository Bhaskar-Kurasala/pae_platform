"use client";

import { useMemo, useState } from "react";
import {
  BookOpen,
  ExternalLink,
  FileText,
  GitBranch,
  Lock,
  Loader2,
  PlaySquare,
  Presentation,
  Notebook,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  ApiError,
  type LessonResourceResponse,
  type ResourceKind,
} from "@/lib/api-client";
import { useOpenResource } from "@/lib/hooks/use-resources";

interface Lesson {
  id: string;
  title: string;
  order: number;
}

interface ResourceListProps {
  resources: LessonResourceResponse[];
  lessons: Lesson[];
  enrolled: boolean;
  isPaid: boolean;
}

const KIND_META: Record<
  ResourceKind,
  { icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>; label: string; cta: string }
> = {
  notebook: { icon: Notebook, label: "Notebook", cta: "Open in Colab" },
  repo: { icon: GitBranch, label: "Repo", cta: "Open on GitHub" },
  video: { icon: PlaySquare, label: "Video", cta: "Watch" },
  pdf: { icon: FileText, label: "PDF", cta: "Open" },
  slides: { icon: Presentation, label: "Slides", cta: "Open" },
  link: { icon: ExternalLink, label: "Link", cta: "Open" },
};

interface ResourceGroup {
  key: string;
  heading: string;
  items: LessonResourceResponse[];
}

function groupResources(
  resources: LessonResourceResponse[],
  lessons: Lesson[],
): ResourceGroup[] {
  const lessonsById = new Map(lessons.map((l) => [l.id, l]));
  const courseLevel: LessonResourceResponse[] = [];
  const byLesson = new Map<string, LessonResourceResponse[]>();

  for (const r of resources) {
    if (r.lesson_id === null) {
      courseLevel.push(r);
    } else {
      const arr = byLesson.get(r.lesson_id) ?? [];
      arr.push(r);
      byLesson.set(r.lesson_id, arr);
    }
  }

  const groups: ResourceGroup[] = [];
  if (courseLevel.length > 0) {
    groups.push({
      key: "__course__",
      heading: "Course-wide resources",
      items: courseLevel.sort((a, b) => a.order - b.order),
    });
  }

  const sortedLessonIds = [...byLesson.keys()].sort((a, b) => {
    const oa = lessonsById.get(a)?.order ?? 9999;
    const ob = lessonsById.get(b)?.order ?? 9999;
    return oa - ob;
  });
  for (const lessonId of sortedLessonIds) {
    const lesson = lessonsById.get(lessonId);
    groups.push({
      key: lessonId,
      heading: lesson ? `${lesson.order}. ${lesson.title}` : "Lesson resources",
      items: (byLesson.get(lessonId) ?? []).sort((a, b) => a.order - b.order),
    });
  }
  return groups;
}

export function ResourceList({
  resources,
  lessons,
  enrolled,
  isPaid,
}: ResourceListProps) {
  const groups = useMemo(() => groupResources(resources, lessons), [resources, lessons]);
  const openMutation = useOpenResource();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errorByResource, setErrorByResource] = useState<Record<string, string>>({});

  if (resources.length === 0) {
    return (
      <div className="rounded-xl ring-1 ring-foreground/10 bg-card p-8 text-center text-sm text-muted-foreground">
        No materials published yet for this course.
      </div>
    );
  }

  const locked = isPaid && !enrolled;

  async function handleOpen(resource: LessonResourceResponse) {
    if (resource.locked) return;
    setBusyId(resource.id);
    setErrorByResource((prev) => {
      if (!(resource.id in prev)) return prev;
      const next = { ...prev };
      delete next[resource.id];
      return next;
    });
    try {
      const data = await openMutation.mutateAsync(resource.id);
      if (typeof window !== "undefined") {
        window.open(data.open_url, "_blank", "noopener,noreferrer");
      }
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : "Could not open this resource. Try again.";
      setErrorByResource((prev) => ({ ...prev, [resource.id]: msg }));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      {locked && (
        <div
          role="status"
          className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
        >
          <Lock className="inline h-4 w-4 mr-1.5 -mt-0.5" aria-hidden /> Enroll to
          unlock notebooks, repos, and downloads.
        </div>
      )}

      {groups.map((group) => (
        <div key={group.key} className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground">{group.heading}</h3>
          <ul className="rounded-xl ring-1 ring-foreground/10 bg-card divide-y overflow-hidden">
            {group.items.map((resource) => {
              const meta = KIND_META[resource.kind];
              const Icon = meta.icon;
              const isLocked = resource.locked;
              const isBusy = busyId === resource.id;
              const errorMsg = errorByResource[resource.id];
              return (
                <li key={resource.id} className="flex items-center gap-3 px-4 py-3">
                  <Icon className="h-5 w-5 text-muted-foreground" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="font-medium text-sm truncate">{resource.title}</p>
                      <Badge variant="secondary" className="text-[10px]">
                        {meta.label}
                      </Badge>
                      {resource.is_required && (
                        <Badge className="bg-primary/10 text-primary hover:bg-primary/10 text-[10px]">
                          Required
                        </Badge>
                      )}
                    </div>
                    {resource.description && (
                      <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                        {resource.description}
                      </p>
                    )}
                    {errorMsg && (
                      <p className="text-xs text-destructive mt-1" role="alert">
                        {errorMsg}
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleOpen(resource)}
                    disabled={isLocked || isBusy}
                    className="inline-flex items-center gap-1.5 h-8 rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    aria-label={
                      isLocked
                        ? `Locked — enroll to open ${resource.title}`
                        : `${meta.cta}: ${resource.title}`
                    }
                  >
                    {isLocked ? (
                      <Lock className="h-3.5 w-3.5" aria-hidden />
                    ) : isBusy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    ) : (
                      <BookOpen className="h-3.5 w-3.5" aria-hidden />
                    )}
                    {isLocked ? "Locked" : meta.cta}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}
