"use client";

import { Suspense, useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useIsFetching, useIsMutating } from "@tanstack/react-query";

function RouteLoadingBarInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const fetching = useIsFetching();
  const mutating = useIsMutating();
  const [visible, setVisible] = useState(false);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    setVisible(true);
    setProgress(15);
    const t1 = setTimeout(() => setProgress(60), 120);
    const t2 = setTimeout(() => setProgress(85), 360);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [pathname, searchParams]);

  const busy = fetching > 0 || mutating > 0;

  useEffect(() => {
    if (busy) return;
    if (!visible) return;
    setProgress(100);
    const t = setTimeout(() => {
      setVisible(false);
      setProgress(0);
    }, 220);
    return () => clearTimeout(t);
  }, [busy, visible]);

  if (!visible) return null;

  return (
    <div
      role="progressbar"
      aria-label="Loading"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={progress}
      className="pointer-events-none fixed left-0 right-0 top-0 z-[100] h-0.5 bg-transparent"
    >
      <div
        className="h-full bg-primary shadow-[0_0_8px_rgba(29,158,117,0.6)] transition-all duration-200 ease-out"
        style={{ width: `${progress}%`, opacity: progress === 100 ? 0 : 1 }}
      />
    </div>
  );
}

// Next 15 forces any component that calls useSearchParams() to be wrapped in a
// Suspense boundary so pages using the App Router can statically prerender.
export function RouteLoadingBar() {
  return (
    <Suspense fallback={null}>
      <RouteLoadingBarInner />
    </Suspense>
  );
}
