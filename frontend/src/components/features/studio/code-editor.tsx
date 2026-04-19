"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import { Save } from "lucide-react";
import type { OnMount } from "@monaco-editor/react";
import { useStudio } from "./studio-context";

const SAVE_DEBOUNCE_MS = 600;

const Monaco = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
      Loading editor…
    </div>
  ),
});

const STORAGE_KEY = "studio.code";
const DEFAULT_CODE = `# Write Python here — try calling Claude or building a small agent.\nimport os\n\ndef greet(name: str) -> str:\n    return f"Hello, {name}!"\n\nprint(greet("PAE"))\n`;

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("auth-storage");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { state?: { token?: string } };
    return parsed.state?.token ?? null;
  } catch {
    return null;
  }
}

interface CodeEditorProps {
  onCodeChange?: (code: string) => void;
}

// We use `unknown` + type assertion for Monaco internals since the
// `monaco-editor` package isn't installed as a direct dep (it's a peer dep of
// @monaco-editor/react). All Monaco API calls are narrowed at call-site.
type MonacoEditor = Parameters<OnMount>[0];
type MonacoInstance = Parameters<OnMount>[1];

export function CodeEditor({ onCodeChange }: CodeEditorProps) {
  const { resolvedTheme } = useTheme();
  const { tutorPins } = useStudio();
  const [code, setCode] = useState<string>(DEFAULT_CODE);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [dirty, setDirty] = useState(false);
  const saveTimerRef = useRef<number | null>(null);
  const lintTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const editorRef = useRef<MonacoEditor | null>(null);
  const monacoRef = useRef<MonacoInstance | null>(null);
  const pinDecorationIdsRef = useRef<string[]>([]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved) {
      setCode(saved);
      onCodeChange?.(saved);
    } else {
      onCodeChange?.(DEFAULT_CODE);
    }
  }, [onCodeChange]);

  const persist = useCallback((value: string) => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEY, value);
    setSavedAt(new Date());
    setDirty(false);
  }, []);

  // #43 — format on Ctrl+S via backend ruff
  const formatCode = useCallback(
    async (editorInstance: MonacoEditor) => {
      const currentCode = editorInstance.getValue();
      const token = getToken();
      try {
        const resp = await fetch(`${API_BASE}/api/v1/format`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ code: currentCode, language: "python" }),
        });
        if (!resp.ok) return;
        const data = (await resp.json()) as { code: string; changed: boolean };
        if (data.changed) {
          const position = editorInstance.getPosition();
          editorInstance.setValue(data.code);
          if (position) editorInstance.setPosition(position);
          persist(data.code);
          setCode(data.code);
          onCodeChange?.(data.code);
        }
      } catch {
        // Format failed — keep original
      }
    },
    [persist, onCodeChange],
  );

  // #44 — lint as you type via ruff markers
  const scheduleLint = useCallback(
    (value: string, monacoInstance: MonacoInstance, editorInstance: MonacoEditor) => {
      if (lintTimerRef.current) clearTimeout(lintTimerRef.current);
      lintTimerRef.current = setTimeout(async () => {
        const token = getToken();
        try {
          const resp = await fetch(`${API_BASE}/api/v1/format`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ code: value, language: "python", lint_only: true }),
          });
          if (!resp.ok) return;
          const result = (await resp.json()) as {
            markers?: {
              startLineNumber: number;
              startColumn: number;
              endLineNumber: number;
              endColumn: number;
              message: string;
              severity: number;
            }[];
          };
          const model = editorInstance.getModel();
          if (model && result.markers) {
            monacoInstance.editor.setModelMarkers(model, "ruff", result.markers);
          }
        } catch {
          // Lint failed silently
        }
      }, 800);
    },
    [],
  );

  const handleChange = (value: string | undefined) => {
    const next = value ?? "";
    setCode(next);
    setDirty(true);
    onCodeChange?.(next);
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
    }
    saveTimerRef.current = window.setTimeout(() => persist(next), SAVE_DEBOUNCE_MS);

    // #44 — schedule lint
    if (editorRef.current && monacoRef.current) {
      scheduleLint(next, monacoRef.current, editorRef.current);
    }
  };

  // #40 — sync tutor pins as gutter decorations
  useEffect(() => {
    if (!editorRef.current || !monacoRef.current) return;
    const monaco = monacoRef.current;
    const editor = editorRef.current;

    pinDecorationIdsRef.current = editor.deltaDecorations(
      pinDecorationIdsRef.current,
      tutorPins.map((pin) => ({
        range: new monaco.Range(pin.lineNumber, 1, pin.lineNumber, 1),
        options: {
          isWholeLine: false,
          glyphMarginClassName: "tutor-pin-glyph",
          glyphMarginHoverMessage: { value: `**Tutor:** ${pin.message}` },
        },
      })),
    );
  }, [tutorPins]);

  const handleEditorMount: OnMount = useCallback(
    (editorInstance, monacoInstance) => {
      editorRef.current = editorInstance;
      monacoRef.current = monacoInstance;

      // #43 — Ctrl+S / Cmd+S → format on save
      editorInstance.addCommand(
        monacoInstance.KeyMod.CtrlCmd | monacoInstance.KeyCode.KeyS,
        () => {
          void formatCode(editorInstance);
        },
      );

      // Enable glyph margin for tutor pins (#40)
      editorInstance.updateOptions({ glyphMargin: true });
    },
    [formatCode],
  );

  useEffect(() => {
    return () => {
      if (saveTimerRef.current !== null) {
        window.clearTimeout(saveTimerRef.current);
      }
      if (lintTimerRef.current !== null) {
        clearTimeout(lintTimerRef.current);
      }
    };
  }, []);

  // DISC-39 — click-to-jump from traceback frames dispatched by execution-trace.
  useEffect(() => {
    function onRevealLine(e: Event) {
      const detail = (e as CustomEvent<{ lineNumber?: number }>).detail;
      const line = detail?.lineNumber;
      const editor = editorRef.current;
      if (!editor || typeof line !== "number" || line <= 0) return;
      try {
        editor.revealLineInCenter(line);
        editor.setPosition({ lineNumber: line, column: 1 });
        editor.focus();
      } catch {
        /* ignore — editor may be unmounted or line out of range */
      }
    }
    window.addEventListener("studio.reveal_line", onRevealLine);
    return () => window.removeEventListener("studio.reveal_line", onRevealLine);
  }, []);

  let savedLabel = "Not saved yet";
  if (dirty) {
    savedLabel = "Saving…";
  } else if (savedAt) {
    savedLabel = `Saved ${savedAt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-7 shrink-0 items-center justify-between border-b border-border/60 bg-background px-3 text-[11px] text-muted-foreground">
        <span className="font-mono">main.py</span>
        <span className="flex items-center gap-1">
          <Save className="h-3 w-3" aria-hidden="true" />
          <span>{savedLabel}</span>
        </span>
      </div>
      <div className="flex-1">
        <Monaco
          height="100%"
          defaultLanguage="python"
          language="python"
          value={code}
          onChange={handleChange}
          onMount={handleEditorMount}
          theme={resolvedTheme === "dark" ? "vs-dark" : "light"}
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            tabSize: 4,
            scrollBeyondLastLine: false,
            automaticLayout: true,
            wordWrap: "on",
            padding: { top: 8, bottom: 8 },
            glyphMargin: true,
          }}
        />
      </div>
      {/* Tutor pin glyph CSS for #40 */}
      <style>{`
        .tutor-pin-glyph {
          background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='%231D9E75'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Ctext x='12' y='16' text-anchor='middle' fill='white' font-size='12' font-family='sans-serif'%3E!%3C/text%3E%3C/svg%3E");
          background-repeat: no-repeat;
          background-position: center;
          background-size: 12px 12px;
          cursor: pointer;
        }
      `}</style>
    </div>
  );
}
