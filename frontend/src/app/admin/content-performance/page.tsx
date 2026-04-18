import { cookies } from "next/headers";

interface LessonPerformance {
  lesson_id: string;
  lesson_title: string;
  question_count: number;
  confusion_count: number;
}

async function getContentPerformance(): Promise<LessonPerformance[]> {
  const cookieStore = await cookies();
  const token = cookieStore.get("access_token")?.value;
  const resp = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/admin/content-performance`,
    {
      headers: { Authorization: `Bearer ${token ?? ""}` },
      cache: "no-store",
    },
  );
  if (!resp.ok) return [];
  return resp.json() as Promise<LessonPerformance[]>;
}

function ConfusionBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const colour =
    pct >= 50 ? "bg-red-500" : pct >= 25 ? "bg-amber-400" : "bg-primary";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full ${colour}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
          aria-label={`Confusion rate: ${pct}%`}
        />
      </div>
      <span className="text-xs tabular-nums text-muted-foreground">{pct}%</span>
    </div>
  );
}

export default async function ContentPerformancePage() {
  const lessons = await getContentPerformance();

  return (
    <div className="p-6 md:p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Content Performance</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Per-lesson question and confusion counts (socratic tutor interactions)
        </p>
      </div>

      {lessons.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No lesson interaction data recorded yet.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm" aria-label="Content performance table">
            <thead>
              <tr className="border-b bg-muted/40">
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-muted-foreground">
                  Lesson
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase text-muted-foreground">
                  Questions
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase text-muted-foreground">
                  Confusions
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-muted-foreground">
                  Confusion Rate
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {lessons.map((lesson) => {
                const rate =
                  lesson.question_count > 0
                    ? lesson.confusion_count / lesson.question_count
                    : 0;
                return (
                  <tr key={lesson.lesson_id} className="hover:bg-muted/20 transition-colors">
                    <td className="px-4 py-3 font-medium">
                      {lesson.lesson_title}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                      {lesson.question_count}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                      {lesson.confusion_count}
                    </td>
                    <td className="px-4 py-3">
                      <ConfusionBar rate={rate} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
