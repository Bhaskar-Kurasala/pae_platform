"use client";

import { useStudio } from "./studio-context";

/** Return a human-readable relative time string without date-fns. */
function relativeTime(timestamp: number): string {
  const diffMs = Date.now() - timestamp;
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} minute${diffMin === 1 ? "" : "s"} ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} hour${diffHr === 1 ? "" : "s"} ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay} day${diffDay === 1 ? "" : "s"} ago`;
}

export function RunHistoryPanel() {
  const { history, restoreSnapshot } = useStudio();

  if (history.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        No run history yet. Run your code to start recording history.
      </p>
    );
  }

  return (
    <ul className="divide-y divide-border" role="list" aria-label="Run history">
      {history.map((snap) => (
        <li
          key={snap.timestamp}
          className="flex items-center justify-between px-4 py-2"
        >
          <div className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground">
              {relativeTime(snap.timestamp)}
            </span>
            {snap.output && (
              <span className="max-w-[200px] truncate font-mono text-[10px] text-muted-foreground/70">
                {snap.output.slice(0, 60)}
              </span>
            )}
          </div>
          <button
            type="button"
            className="text-xs text-primary underline hover:text-primary/80"
            onClick={() => restoreSnapshot(snap)}
            aria-label={`Restore run from ${relativeTime(snap.timestamp)}`}
          >
            Restore
          </button>
        </li>
      ))}
    </ul>
  );
}
