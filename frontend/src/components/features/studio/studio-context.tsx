"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { executeApi, type ExecuteResponse } from "@/lib/api-client";

interface StudioContextValue {
  code: string;
  setCode: (value: string) => void;
  result: ExecuteResponse | null;
  running: boolean;
  runError: string | null;
  stepIndex: number;
  setStepIndex: (i: number) => void;
  run: () => Promise<void>;
  hasRunOnce: boolean;
}

const StudioContext = createContext<StudioContextValue | null>(null);

export function StudioProvider({ children }: { children: React.ReactNode }) {
  const [code, setCode] = useState<string>("");
  const [result, setResult] = useState<ExecuteResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState<number>(0);
  const [hasRunOnce, setHasRunOnce] = useState(false);
  const codeRef = useRef(code);
  codeRef.current = code;

  const run = useCallback(async () => {
    setRunning(true);
    setRunError(null);
    try {
      const res = await executeApi.run({ code: codeRef.current });
      setResult(res);
      setStepIndex(Math.max(0, res.events.length - 1));
    } catch (err) {
      setRunError(err instanceof Error ? err.message : "Run failed");
      setResult(null);
    } finally {
      setRunning(false);
      // Flip hasRunOnce after any attempt (success OR failure) — the point of
      // ugly-draft mode is pushing through the first-attempt friction, not
      // gating on correctness.
      setHasRunOnce(true);
    }
  }, []);

  const value = useMemo(
    () => ({
      code,
      setCode,
      result,
      running,
      runError,
      stepIndex,
      setStepIndex,
      run,
      hasRunOnce,
    }),
    [code, result, running, runError, stepIndex, run, hasRunOnce],
  );
  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>;
}

export function useStudio(): StudioContextValue {
  const ctx = useContext(StudioContext);
  if (!ctx) {
    throw new Error("useStudio must be used inside <StudioProvider>");
  }
  return ctx;
}
