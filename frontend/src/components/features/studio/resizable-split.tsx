"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Direction = "horizontal" | "vertical";

interface ResizableSplitProps {
  direction: Direction;
  initial: number;
  min: number;
  max: number;
  first: React.ReactNode;
  second: React.ReactNode;
  storageKey?: string;
  collapsedSecond?: boolean;
}

export function ResizableSplit({
  direction,
  initial,
  min,
  max,
  first,
  second,
  storageKey,
  collapsedSecond = false,
}: ResizableSplitProps) {
  const [pct, setPct] = useState<number>(initial);
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  useEffect(() => {
    if (!storageKey || typeof window === "undefined") return;
    const saved = window.localStorage.getItem(storageKey);
    if (saved) {
      const parsed = Number(saved);
      if (!Number.isNaN(parsed) && parsed >= min && parsed <= max) {
        setPct(parsed);
      }
    }
  }, [storageKey, min, max]);

  const persist = useCallback(
    (value: number) => {
      if (!storageKey || typeof window === "undefined") return;
      window.localStorage.setItem(storageKey, String(value));
    },
    [storageKey],
  );

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    draggingRef.current = true;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const raw =
      direction === "horizontal"
        ? ((e.clientX - rect.left) / rect.width) * 100
        : ((e.clientY - rect.top) / rect.height) * 100;
    const clamped = Math.max(min, Math.min(max, raw));
    setPct(clamped);
    persist(clamped);
  };

  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    draggingRef.current = false;
    try {
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      // ignore
    }
  };

  if (collapsedSecond) {
    return <div className="h-full w-full">{first}</div>;
  }

  const flexDir = direction === "horizontal" ? "flex-row" : "flex-col";
  const handleClasses =
    direction === "horizontal"
      ? "w-1 cursor-col-resize hover:bg-primary/40"
      : "h-1 cursor-row-resize hover:bg-primary/40";

  return (
    <div ref={containerRef} className={`flex h-full w-full ${flexDir} overflow-hidden`}>
      <div
        className="overflow-hidden"
        style={
          direction === "horizontal"
            ? { width: `${pct}%` }
            : { height: `${pct}%` }
        }
      >
        {first}
      </div>
      <div
        role="separator"
        aria-orientation={direction}
        tabIndex={-1}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        className={`shrink-0 bg-border transition-colors ${handleClasses}`}
      />
      <div
        className="overflow-hidden"
        style={
          direction === "horizontal"
            ? { width: `${100 - pct}%` }
            : { height: `${100 - pct}%` }
        }
      >
        {second}
      </div>
    </div>
  );
}
