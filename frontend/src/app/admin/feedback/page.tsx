"use client";

import { CheckCircle2, Clock, RefreshCw } from "lucide-react";
import { useAdminFeedback, useResolveFeedback, type FeedbackItem } from "@/lib/hooks/use-admin";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

function SentimentBadge({ sentiment }: { sentiment: string | null }) {
  if (!sentiment) return null;
  const styles: Record<string, string> = {
    positive: "bg-green-100 text-green-700",
    neutral: "bg-gray-100 text-gray-600",
    negative: "bg-red-100 text-red-700",
  };
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-xs font-medium capitalize",
        styles[sentiment] ?? "bg-muted text-muted-foreground",
      )}
    >
      {sentiment}
    </span>
  );
}

function FeedbackRow({ item }: { item: FeedbackItem }) {
  const { mutate: resolve, isPending } = useResolveFeedback();

  return (
    <tr className={cn("border-b last:border-0", item.resolved && "opacity-50")}>
      <td className="py-3 pr-4 text-xs text-muted-foreground">{item.route}</td>
      <td className="py-3 pr-4 text-sm">{item.body.slice(0, 120)}{item.body.length > 120 ? "…" : ""}</td>
      <td className="py-3 pr-4">
        <SentimentBadge sentiment={item.sentiment} />
      </td>
      <td className="py-3 pr-4 text-xs text-muted-foreground">
        {new Date(item.created_at).toLocaleDateString()}
      </td>
      <td className="py-3">
        {item.resolved ? (
          <span className="flex items-center gap-1 text-xs text-green-600">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Resolved
          </span>
        ) : (
          <Button
            variant="outline"
            size="sm"
            onClick={() => resolve(item.id)}
            disabled={isPending}
            aria-label={`Resolve feedback from ${item.route}`}
          >
            Resolve
          </Button>
        )}
      </td>
    </tr>
  );
}

function Skeleton() {
  return (
    <div className="animate-pulse space-y-3">
      {[1, 2, 3].map((n) => (
        <div key={n} className="h-12 rounded-lg bg-muted" />
      ))}
    </div>
  );
}

export default function AdminFeedbackPage() {
  const { data: items, isLoading, refetch } = useAdminFeedback();

  const open = items?.filter((i: FeedbackItem) => !i.resolved).length ?? 0;
  const total = items?.length ?? 0;

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Feedback Triage</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {open} open · {total} total
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void refetch()}
          aria-label="Refresh feedback list"
        >
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Clock className="h-4 w-4" />
            Latest feedback (newest first)
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton />
          ) : !items || items.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No feedback yet.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs font-medium text-muted-foreground">
                    <th className="pb-2 pr-4">Route</th>
                    <th className="pb-2 pr-4">Message</th>
                    <th className="pb-2 pr-4">Sentiment</th>
                    <th className="pb-2 pr-4">Date</th>
                    <th className="pb-2">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item: FeedbackItem) => (
                    <FeedbackRow key={item.id} item={item} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
