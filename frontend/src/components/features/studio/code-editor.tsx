"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import { Save } from "lucide-react";

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

interface CodeEditorProps {
  onCodeChange?: (code: string) => void;
}

export function CodeEditor({ onCodeChange }: CodeEditorProps) {
  const { resolvedTheme } = useTheme();
  const [code, setCode] = useState<string>(DEFAULT_CODE);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [dirty, setDirty] = useState(false);
  const saveTimerRef = useRef<number | null>(null);

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

  const handleChange = (value: string | undefined) => {
    const next = value ?? "";
    setCode(next);
    setDirty(true);
    onCodeChange?.(next);
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
    }
    saveTimerRef.current = window.setTimeout(() => persist(next), SAVE_DEBOUNCE_MS);
  };

  useEffect(() => {
    return () => {
      if (saveTimerRef.current !== null) {
        window.clearTimeout(saveTimerRef.current);
      }
    };
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
          theme={resolvedTheme === "dark" ? "vs-dark" : "light"}
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            tabSize: 4,
            scrollBeyondLastLine: false,
            automaticLayout: true,
            wordWrap: "on",
            padding: { top: 8, bottom: 8 },
          }}
        />
      </div>
    </div>
  );
}
