import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { SkillCoverageItem } from "@/lib/api-client";

function masteryColour(m: number): string {
  if (m >= 0.8) return "bg-primary text-primary-foreground";
  if (m >= 0.4) return "bg-yellow-400 text-yellow-900";
  return "bg-muted text-muted-foreground";
}

export function ReceiptsSkillCoverage({ skills }: { skills: SkillCoverageItem[] }) {
  if (skills.length === 0) {
    return (
      <Card>
        <CardContent className="p-4 text-sm text-muted-foreground">
          No skills touched this week.
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Skills this week</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2 pb-4">
        {skills.map((s) => (
          <span
            key={s.id}
            className={cn(
              "rounded-full px-2.5 py-0.5 text-xs font-medium",
              masteryColour(s.mastery),
            )}
            title={`Mastery: ${Math.round(s.mastery * 100)}%`}
          >
            {s.name}
          </span>
        ))}
      </CardContent>
    </Card>
  );
}
