"use client";

import dynamic from "next/dynamic";
import { useTheme } from "next-themes";

const DiffEditor = dynamic(
  () => import("@monaco-editor/react").then((m) => m.DiffEditor),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        Loading diff viewer…
      </div>
    ),
  },
);

interface DiffViewerProps {
  original: string;
  modified: string;
  language?: string;
}

export function DiffViewer({
  original,
  modified,
  language = "python",
}: DiffViewerProps) {
  const { resolvedTheme } = useTheme();

  return (
    <div className="h-full w-full" aria-label="Code diff viewer" role="region">
      <DiffEditor
        height="100%"
        language={language}
        original={original}
        modified={modified}
        theme={resolvedTheme === "dark" ? "vs-dark" : "light"}
        options={{
          readOnly: true,
          renderSideBySide: true,
          minimap: { enabled: false },
          fontSize: 13,
          scrollBeyondLastLine: false,
          automaticLayout: true,
        }}
      />
    </div>
  );
}
