import Link from "next/link";
import { BookOpen, Clock } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ProgressBar } from "./progress-bar";

interface CourseCardProps {
  id: string;
  title: string;
  description?: string;
  difficulty: string;
  estimatedHours: number;
  lessonCount?: number;
  progressPct?: number;
  priceCents?: number;
}

const difficultyColor: Record<string, string> = {
  beginner: "bg-green-100 text-green-700",
  intermediate: "bg-yellow-100 text-yellow-700",
  advanced: "bg-red-100 text-red-700",
};

export function CourseCard({
  id,
  title,
  description,
  difficulty,
  estimatedHours,
  lessonCount,
  progressPct,
  priceCents = 0,
}: CourseCardProps) {
  return (
    <Link href={`/courses/${id}`} className="group">
      <Card className="h-full hover:shadow-md transition-shadow border-border">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-2">
            <h3 className="font-semibold text-base leading-tight group-hover:text-primary transition-colors">
              {title}
            </h3>
            {priceCents === 0 ? (
              <Badge variant="secondary" className="shrink-0 text-xs">
                Free
              </Badge>
            ) : (
              <Badge className="shrink-0 text-xs bg-[#7C3AED] text-white hover:bg-[#7C3AED]/90">
                ${(priceCents / 100).toFixed(0)}
              </Badge>
            )}
          </div>
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium w-fit ${
              difficultyColor[difficulty] ?? "bg-muted text-muted-foreground"
            }`}
          >
            {difficulty}
          </span>
        </CardHeader>
        <CardContent className="space-y-3">
          {description && (
            <p className="text-sm text-muted-foreground line-clamp-2">{description}</p>
          )}
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            {lessonCount !== undefined && (
              <span className="flex items-center gap-1">
                <BookOpen className="h-3 w-3" aria-hidden="true" />
                {lessonCount} lessons
              </span>
            )}
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" aria-hidden="true" />
              {estimatedHours}h
            </span>
          </div>
          {progressPct !== undefined && progressPct > 0 && (
            <ProgressBar value={progressPct} label="Progress" />
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
