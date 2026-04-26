"use client";

/**
 * Lazy-load Pyodide on first use. ~10MB download cached after first load.
 *
 * The runtime is the same WebAssembly distribution the Python ecosystem uses
 * for browser-side execution. We deliberately avoid bundling it — Pyodide's
 * own loader resolves its WASM/JS files relative to the script URL we point
 * at the official CDN.
 */

import { useCallback, useEffect, useRef, useState } from "react";

const PYODIDE_VERSION = "0.26.4";
const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full`;

interface PyodideInstance {
  runPythonAsync: (code: string) => Promise<unknown>;
  setStdout: (opts: { batched?: (s: string) => void }) => void;
  setStderr: (opts: { batched?: (s: string) => void }) => void;
}

declare global {
  interface Window {
    loadPyodide?: (opts: {
      indexURL: string;
    }) => Promise<PyodideInstance>;
  }
}

export interface PyodideRunResult {
  stdout: string;
  stderr: string;
  result: string | null;
  durationMs: number;
}

let _scriptLoading: Promise<void> | null = null;
let _pyodideInstance: PyodideInstance | null = null;

async function loadScriptOnce(): Promise<void> {
  if (typeof window === "undefined") {
    throw new Error("Pyodide is browser-only.");
  }
  if (window.loadPyodide) return;
  if (_scriptLoading) return _scriptLoading;
  _scriptLoading = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `${PYODIDE_CDN}/pyodide.js`;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Pyodide."));
    document.head.appendChild(script);
  });
  return _scriptLoading;
}

async function loadInstance(): Promise<PyodideInstance> {
  if (_pyodideInstance) return _pyodideInstance;
  await loadScriptOnce();
  if (!window.loadPyodide) {
    throw new Error("Pyodide loader missing after script load.");
  }
  const py = await window.loadPyodide({ indexURL: PYODIDE_CDN });
  _pyodideInstance = py;
  return py;
}

export interface UsePyodideOptions {
  /** Auto-start the load on mount. Defaults to true. */
  eager?: boolean;
}

export function usePyodide(options: UsePyodideOptions = {}) {
  const { eager = true } = options;
  const [ready, setReady] = useState(_pyodideInstance !== null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const instanceRef = useRef<PyodideInstance | null>(_pyodideInstance);

  const init = useCallback(async () => {
    if (instanceRef.current) {
      setReady(true);
      return instanceRef.current;
    }
    setLoading(true);
    setError(null);
    try {
      const py = await loadInstance();
      instanceRef.current = py;
      setReady(true);
      return py;
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Pyodide failed to load.");
      throw exc;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!eager) return;
    void init();
  }, [eager, init]);

  const run = useCallback(
    async (code: string): Promise<PyodideRunResult> => {
      const py = instanceRef.current ?? (await init());
      let stdout = "";
      let stderr = "";
      py.setStdout({ batched: (s) => (stdout += s) });
      py.setStderr({ batched: (s) => (stderr += s) });
      const startedAt = performance.now();
      let result: unknown = null;
      try {
        result = await py.runPythonAsync(code);
      } catch (exc) {
        stderr += `\n${exc instanceof Error ? exc.message : String(exc)}`;
      }
      const durationMs = Math.round(performance.now() - startedAt);
      const stringified =
        result === null || result === undefined ? null : String(result);
      return { stdout, stderr, result: stringified, durationMs };
    },
    [init],
  );

  return { ready, loading, error, run };
}
