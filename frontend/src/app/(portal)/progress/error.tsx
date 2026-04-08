"use client";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="p-8 text-center">
      <p className="text-muted-foreground mb-4">Failed to load progress data.</p>
      <button
        onClick={reset}
        className="h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
      >
        Retry
      </button>
    </div>
  );
}
