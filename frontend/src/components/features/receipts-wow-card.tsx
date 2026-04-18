import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { WowData } from "@/lib/api-client";

export function ReceiptsWowCard({ wow }: { wow: WowData }) {
  if (wow.lessons_trend === "first_week") {
    return (
      <Card>
        <CardContent className="p-4 text-sm text-muted-foreground">
          First week — come back next week to see your progress trend.
        </CardContent>
      </Card>
    );
  }

  const Icon =
    wow.lessons_trend === "up"
      ? TrendingUp
      : wow.lessons_trend === "down"
        ? TrendingDown
        : Minus;
  const colour =
    wow.lessons_trend === "up"
      ? "text-green-600"
      : wow.lessons_trend === "down"
        ? "text-red-500"
        : "text-muted-foreground";

  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <Icon className={`h-5 w-5 ${colour}`} aria-hidden />
        <div>
          <p className="text-sm font-medium">
            {wow.lessons_delta !== null && wow.lessons_delta > 0 ? "+" : ""}
            {wow.lessons_delta} lessons vs last week
          </p>
          <p className="text-xs capitalize text-muted-foreground">
            {wow.lessons_trend}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
