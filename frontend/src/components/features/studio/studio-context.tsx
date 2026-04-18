"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { executeApi, type ExecuteResponse } from "@/lib/api-client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RunSnapshot {
  code: string;
  output: string;
  timestamp: number;
}

export interface TutorPin {
  lineNumber: number;
  message: string;
}

interface StudioContextValue {
  // Code
  code: string;
  setCode: (value: string) => void;

  // Run
  result: ExecuteResponse | null;
  running: boolean;
  runError: string | null;
  stepIndex: number;
  setStepIndex: (i: number) => void;
  run: () => Promise<void>;
  hasRunOnce: boolean;

  // #39 — Diff view
  previousCode: string | null;
  showDiff: boolean;
  setShowDiff: (v: boolean) => void;

  // #40 — Tutor pins
  tutorPins: TutorPin[];
  addTutorPin: (lineNumber: number, message: string) => void;
  clearTutorPins: () => void;

  // #41 — Run history
  history: RunSnapshot[];
  restoreSnapshot: (snap: RunSnapshot) => void;

  // #50 — Exercise context (injected by parent page if available)
  exerciseTitle: string | null;
  setExerciseTitle: (title: string | null) => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_HISTORY = 20;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function historyKey(exerciseId: string): string {
  return `studio-history-${exerciseId}`;
}

function draftKey(exerciseId: string): string {
  return `studio-draft-${exerciseId}`;
}

function loadHistory(exerciseId: string): RunSnapshot[] {
  try {
    const raw = localStorage.getItem(historyKey(exerciseId));
    return raw ? (JSON.parse(raw) as RunSnapshot[]) : [];
  } catch {
    return [];
  }
}

function saveHistory(exerciseId: string, history: RunSnapshot[]): void {
  try {
    localStorage.setItem(historyKey(exerciseId), JSON.stringify(history));
  } catch {
    // quota exceeded — silent
  }
}

// We use a stable "global" exercise ID for the generic studio (no exercise).
const GLOBAL_EXERCISE_ID = "studio-global";

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const StudioContext = createContext<StudioContextValue | null>(null);

export function StudioProvider({ children }: { children: React.ReactNode }) {
  const [code, setCodeState] = useState<string>("");
  const [result, setResult] = useState<ExecuteResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState<number>(0);
  const [hasRunOnce, setHasRunOnce] = useState(false);

  // #39
  const [previousCode, setPreviousCode] = useState<string | null>(null);
  const [showDiff, setShowDiff] = useState(false);

  // #40
  const [tutorPins, setTutorPins] = useState<TutorPin[]>([]);

  // #41 — run history
  const [history, setHistory] = useState<RunSnapshot[]>(() => {
    if (typeof window === "undefined") return [];
    return loadHistory(GLOBAL_EXERCISE_ID);
  });

  // #50 — exercise context
  const [exerciseTitle, setExerciseTitle] = useState<string | null>(null);

  const codeRef = useRef(code);
  codeRef.current = code;

  // #42 — autosave timer ref
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---------------------------------------------------------------------------
  // #42 — restore draft on mount
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (typeof window === "undefined") return;
    const draft = localStorage.getItem(draftKey(GLOBAL_EXERCISE_ID));
    if (draft) {
      setCodeState(draft);
    }
  }, []);

  // ---------------------------------------------------------------------------
  // setCode — with autosave (#42) and lint scheduling (handled in code-editor)
  // ---------------------------------------------------------------------------
  const setCode = useCallback((value: string) => {
    setCodeState(value);
    // #42 — debounced autosave (1 s)
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      try {
        localStorage.setItem(draftKey(GLOBAL_EXERCISE_ID), value);
      } catch {
        // quota exceeded — silent
      }
    }, 1000);
  }, []);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  // ---------------------------------------------------------------------------
  // run — snapshot before run (#39), add history on success (#41)
  // ---------------------------------------------------------------------------
  const run = useCallback(async () => {
    // #39 — snapshot before run
    setPreviousCode(codeRef.current);
    setShowDiff(false);

    setRunning(true);
    setRunError(null);
    try {
      const res = await executeApi.run({ code: codeRef.current });
      setResult(res);
      setStepIndex(Math.max(0, res.events.length - 1));

      // #41 — prepend to run history
      const snapshot: RunSnapshot = {
        code: codeRef.current,
        output: res.stdout,
        timestamp: Date.now(),
      };
      setHistory((prev) => {
        const updated = [snapshot, ...prev].slice(0, MAX_HISTORY);
        saveHistory(GLOBAL_EXERCISE_ID, updated);
        return updated;
      });
    } catch (err) {
      setRunError(err instanceof Error ? err.message : "Run failed");
      setResult(null);
    } finally {
      setRunning(false);
      setHasRunOnce(true);
    }
  }, []);

  // ---------------------------------------------------------------------------
  // #41 — restore snapshot
  // ---------------------------------------------------------------------------
  const restoreSnapshot = useCallback((snap: RunSnapshot) => {
    setCode(snap.code);
  }, [setCode]);

  // ---------------------------------------------------------------------------
  // #40 — tutor pins
  // ---------------------------------------------------------------------------
  const addTutorPin = useCallback((lineNumber: number, message: string) => {
    setTutorPins((prev) => {
      // replace existing pin on same line
      const filtered = prev.filter((p) => p.lineNumber !== lineNumber);
      return [...filtered, { lineNumber, message }];
    });
  }, []);

  const clearTutorPins = useCallback(() => {
    setTutorPins([]);
  }, []);

  // ---------------------------------------------------------------------------
  // Context value
  // ---------------------------------------------------------------------------
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
      previousCode,
      showDiff,
      setShowDiff,
      tutorPins,
      addTutorPin,
      clearTutorPins,
      history,
      restoreSnapshot,
      exerciseTitle,
      setExerciseTitle,
    }),
    [
      code,
      setCode,
      result,
      running,
      runError,
      stepIndex,
      run,
      hasRunOnce,
      previousCode,
      showDiff,
      tutorPins,
      addTutorPin,
      clearTutorPins,
      history,
      restoreSnapshot,
      exerciseTitle,
    ],
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
