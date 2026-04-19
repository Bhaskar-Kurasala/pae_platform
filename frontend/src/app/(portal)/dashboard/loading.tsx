import { PageShell } from "@/components/layouts/page-shell";

export default function Loading() {
  return (
    <PageShell className="space-y-6 animate-pulse">
      <div className="h-7 bg-muted rounded w-48" />
      <div className="grid grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-24 rounded-xl bg-muted" />
        ))}
      </div>
      <div className="space-y-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-16 rounded-xl bg-muted" />
        ))}
      </div>
    </PageShell>
  );
}
