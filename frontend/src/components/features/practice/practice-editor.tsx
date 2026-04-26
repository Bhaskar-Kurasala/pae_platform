"use client";

import { useCallback, useEffect, useImperativeHandle, useRef } from "react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import type { OnMount } from "@monaco-editor/react";
import * as React from "react";

const Monaco = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div
      data-testid="practice-editor-loading"
      className="flex h-full items-center justify-center text-xs text-muted-foreground"
    >
      Loading editor…
    </div>
  ),
});

type MonacoEditor = Parameters<OnMount>[0];
type MonacoInstance = Parameters<OnMount>[1];

export interface PracticeEditorHandle {
  revealLine: (line: number) => void;
  getValue: () => string;
  setValue: (value: string) => void;
}

interface PracticeEditorProps {
  value: string;
  onChange: (value: string) => void;
  onRun?: () => void;
  readOnly?: boolean;
}

export const PracticeEditor = React.forwardRef<
  PracticeEditorHandle,
  PracticeEditorProps
>(function PracticeEditor({ value, onChange, onRun, readOnly }, ref) {
  const { resolvedTheme } = useTheme();
  const editorRef = useRef<MonacoEditor | null>(null);
  const monacoRef = useRef<MonacoInstance | null>(null);
  const decorationIdsRef = useRef<string[]>([]);
  const onRunRef = useRef(onRun);

  useEffect(() => {
    onRunRef.current = onRun;
  }, [onRun]);

  useImperativeHandle(
    ref,
    () => ({
      revealLine: (line: number) => {
        const editor = editorRef.current;
        const monaco = monacoRef.current;
        if (!editor || !monaco || line <= 0) return;
        try {
          editor.revealLineInCenter(line);
          editor.setPosition({ lineNumber: line, column: 1 });
          editor.focus();
          decorationIdsRef.current = editor.deltaDecorations(
            decorationIdsRef.current,
            [
              {
                range: new monaco.Range(line, 1, line, 1),
                options: {
                  isWholeLine: true,
                  className: "practice-line-highlight",
                },
              },
            ],
          );
          window.setTimeout(() => {
            if (editorRef.current) {
              decorationIdsRef.current = editorRef.current.deltaDecorations(
                decorationIdsRef.current,
                [],
              );
            }
          }, 1500);
        } catch {
          /* editor may have unmounted */
        }
      },
      getValue: () => editorRef.current?.getValue() ?? value,
      // Imperative setter — @monaco-editor/react treats `value` as initial-only
      // once the editor mounts, so React-state updates don't propagate. Callers
      // (Reset, Try-in-Studio deep links) need this escape hatch.
      setValue: (next: string) => {
        const editor = editorRef.current;
        if (!editor) return;
        const pos = editor.getPosition();
        editor.setValue(next);
        if (pos) editor.setPosition(pos);
      },
    }),
    [value],
  );

  const handleMount: OnMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
    editor.addCommand(
      monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter,
      () => {
        onRunRef.current?.();
      },
    );
  }, []);

  return (
    <div
      data-testid="practice-editor"
      className="h-full w-full overflow-hidden rounded-md border border-border/60 bg-background"
    >
      <Monaco
        height="100%"
        defaultLanguage="python"
        language="python"
        value={value}
        onChange={(v) => onChange(v ?? "")}
        onMount={handleMount}
        theme={resolvedTheme === "dark" ? "vs-dark" : "light"}
        options={{
          minimap: { enabled: false },
          fontSize: 14,
          lineNumbers: "on",
          tabSize: 4,
          scrollBeyondLastLine: false,
          automaticLayout: true,
          wordWrap: "on",
          padding: { top: 8, bottom: 8 },
          readOnly: !!readOnly,
        }}
      />
      <style jsx global>{`
        .practice-line-highlight {
          background: rgba(29, 158, 117, 0.18);
          transition: background 0.6s ease-out;
        }
      `}</style>
    </div>
  );
});
