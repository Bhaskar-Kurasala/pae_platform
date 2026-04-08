export default function Loading() {
  return (
    <div className="p-6 md:p-8 max-w-3xl mx-auto animate-pulse space-y-6">
      <div className="h-7 bg-muted rounded w-32" />
      <div className="grid grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => <div key={i} className="h-20 rounded-xl bg-muted" />)}
      </div>
      <div className="h-48 rounded-xl bg-muted" />
    </div>
  );
}
