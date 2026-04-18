"use client";

import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { DayActivity } from "@/lib/api-client";

export function ReceiptsTimeChart({ data }: { data: DayActivity[] }) {
  if (data.length === 0) {
    return (
      <Card>
        <CardContent className="p-4 text-sm text-muted-foreground">
          No activity logged this week yet.
        </CardContent>
      </Card>
    );
  }

  const chartData = data.map((d) => ({
    ...d,
    label: new Date(`${d.day}T00:00:00Z`).toLocaleDateString("en", {
      weekday: "short",
      timeZone: "UTC",
    }),
  }));

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Time this week</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={120}>
          <BarChart data={chartData}>
            <XAxis dataKey="label" tick={{ fontSize: 10 }} />
            <YAxis unit="m" tick={{ fontSize: 10 }} />
            <Tooltip
              formatter={(v) => [`${String(v)} min`, "Active time"]}
            />
            <Bar
              dataKey="minutes"
              fill="hsl(var(--primary))"
              radius={[4, 4, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
