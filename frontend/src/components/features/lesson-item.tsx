import Link from "next/link";
import { CheckCircle2, Circle, Clock, PlayCircle } from "lucide-react";

interface LessonItemProps {
  id: string;
  title: string;
  durationSeconds: number;
  order: number;
  isCompleted?: boolean;
  isFreePreview?: boolean;
  isPortal?: boolean;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s > 0 ? `${s}s` : ""}`.trim() : `${s}s`;
}

export function LessonItem({
  id,
  title,
  durationSeconds,
  order,
  isCompleted = false,
  isFreePreview = false,
  isPortal = false,
}: LessonItemProps) {
  const href = isPortal ? `/lessons/${id}` : undefined;

  const inner = (
    <div className="flex items-center gap-3 p-3 rounded-lg hover:bg-muted transition-colors group">
      <span className="text-xs text-muted-foreground w-5 text-right shrink-0">{order}</span>
      <div className="shrink-0 text-muted-foreground">
        {isCompleted ? (
          <CheckCircle2 className="h-5 w-5 text-primary" aria-label="Completed" />
        ) : isPortal ? (
          <PlayCircle className="h-5 w-5 group-hover:text-primary transition-colors" aria-label="Play" />
        ) : (
          <Circle className="h-5 w-5" aria-label="Not started" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate group-hover:text-primary transition-colors">
          {title}
        </p>
        {isFreePreview && (
          <span className="text-xs text-[#1D9E75] font-medium">Free preview</span>
        )}
      </div>
      {durationSeconds > 0 && (
        <span className="text-xs text-muted-foreground flex items-center gap-1 shrink-0">
          <Clock className="h-3 w-3" aria-hidden="true" />
          {formatDuration(durationSeconds)}
        </span>
      )}
    </div>
  );

  if (href) {
    return (
      <Link href={href} aria-label={`Go to lesson: ${title}`}>
        {inner}
      </Link>
    );
  }
  return inner;
}
