"use client";

import * as React from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * CodeBlock — styled, interactive code viewer.
 *
 * Features:
 *   - Header bar with language badge + optional filename + copy button
 *   - Line numbers (toggleable; auto-on when >5 lines)
 *   - Line-hover highlight via :hover on the line wrapper
 *   - Line-linking: click a line number to copy a URL with #L{n} hash
 *   - Line highlight ranges via `highlightLines` prop or initial URL hash
 *
 * Styling:
 *   - Rounded-xl dark chrome; whisper border
 *   - Header tint: zinc-800/80 for contrast against canvas
 *   - Font: JetBrains-ish via existing mono stack
 */

export interface CodeBlockProps {
  code: string;
  /** Prism-compatible language id, e.g. "ts", "python". */
  language?: string;
  /** Filename shown in the header (italic, next to the language chip). */
  filename?: string;
  /** Force line numbers on. Default: auto — on when the block has >5 lines. */
  showLineNumbers?: boolean;
  /** Array of 1-based line numbers to highlight. */
  highlightLines?: number[];
  /** Disable the copy button (e.g. when the code is snippet-only). */
  copyable?: boolean;
  /** Disable the click-to-link behavior on line numbers. */
  linkable?: boolean;
  /** Wrapper className. */
  className?: string;
  /** Max height; when set, block scrolls internally. */
  maxHeight?: number | string;
}

function parseHash(): Set<number> {
  if (typeof window === "undefined") return new Set();
  const hash = window.location.hash;
  const m = hash.match(/^#L(\d+)(?:-L(\d+))?$/);
  if (!m) return new Set();
  const start = Number(m[1]);
  const end = m[2] ? Number(m[2]) : start;
  const set = new Set<number>();
  for (let i = Math.min(start, end); i <= Math.max(start, end); i++) set.add(i);
  return set;
}

export function CodeBlock({
  code,
  language = "text",
  filename,
  showLineNumbers,
  highlightLines,
  copyable = true,
  linkable = true,
  className,
  maxHeight,
}: CodeBlockProps) {
  const trimmed = code.replace(/\n$/, "");
  const lineCount = trimmed.split("\n").length;
  const withLineNumbers = showLineNumbers ?? lineCount > 5;
  const [copied, setCopied] = React.useState(false);
  const [hashLines, setHashLines] = React.useState<Set<number>>(new Set());

  React.useEffect(() => {
    setHashLines(parseHash());
    const onHash = () => setHashLines(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const highlightSet = React.useMemo(() => {
    const s = new Set<number>(highlightLines ?? []);
    for (const n of hashLines) s.add(n);
    return s;
  }, [highlightLines, hashLines]);

  const handleCopy = async () => {
    // SSR / unsupported browser guard — modern HTTPS / localhost envs have
    // this; older contexts get a console warning and a no-op.
    if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
      console.warn("[CodeBlock] navigator.clipboard unavailable; copy skipped");
      return;
    }
    try {
      await navigator.clipboard.writeText(trimmed);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable — silently ignore
    }
  };

  const copyLineLink = async (lineNumber: number) => {
    if (typeof window === "undefined") return;
    const url = `${window.location.origin}${window.location.pathname}${window.location.search}#L${lineNumber}`;
    try {
      await navigator.clipboard.writeText(url);
      window.history.replaceState(null, "", `#L${lineNumber}`);
      setHashLines(new Set([lineNumber]));
    } catch {
      // ignore
    }
  };

  return (
    <div
      data-slot="code-block"
      className={cn(
        "group/code my-4 rounded-xl overflow-hidden border border-zinc-700/60 bg-[#1e1e2e] shadow-md",
        className,
      )}
    >
      <div className="flex items-center justify-between px-4 py-2 bg-zinc-800/80 border-b border-zinc-700/40">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[11px] font-mono font-medium text-zinc-400 uppercase tracking-widest">
            {language}
          </span>
          {filename ? (
            <>
              <span className="text-zinc-600" aria-hidden="true">
                ·
              </span>
              <span className="truncate text-[11px] text-zinc-400 font-mono">
                {filename}
              </span>
            </>
          ) : null}
        </div>
        {copyable ? (
          <>
            <button
              type="button"
              onClick={() => void handleCopy()}
              aria-label={copied ? "Copied" : "Copy code"}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium transition-all duration-fast",
                copied
                  ? "bg-emerald-500/20 text-emerald-400"
                  : "bg-white/10 text-zinc-400 hover:bg-white/20 hover:text-white",
              )}
            >
              {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
              {copied ? "Copied" : "Copy"}
            </button>
            <span role="status" aria-live="polite" className="sr-only">
              {copied ? "Copied" : ""}
            </span>
          </>
        ) : null}
      </div>
      <div
        className="overflow-auto"
        style={maxHeight ? { maxHeight } : undefined}
      >
        <SyntaxHighlighter
          language={language}
          style={oneDark}
          customStyle={{
            margin: 0,
            padding: "0.75rem 0",
            background: "transparent",
            fontSize: "0.8rem",
            lineHeight: "1.7",
          }}
          showLineNumbers={withLineNumbers}
          wrapLines
          lineProps={(lineNumber) => {
            const active = highlightSet.has(lineNumber);
            return {
              style: {
                display: "block",
                padding: "0 1.25rem",
                backgroundColor: active ? "rgba(94, 106, 210, 0.12)" : undefined,
                borderLeft: active
                  ? "2px solid rgba(94, 106, 210, 0.9)"
                  : "2px solid transparent",
              },
              className: "code-line",
              onMouseEnter: (e: React.MouseEvent<HTMLElement>) => {
                if (!active) e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.03)";
              },
              onMouseLeave: (e: React.MouseEvent<HTMLElement>) => {
                if (!active) e.currentTarget.style.backgroundColor = "";
              },
            } as React.HTMLAttributes<HTMLElement>;
          }}
          lineNumberStyle={{
            color: "#4a4a6a",
            minWidth: "2.5em",
            paddingRight: "1em",
            userSelect: "none",
            cursor: linkable ? "pointer" : undefined,
          }}
          lineNumberContainerStyle={{ float: "left" }}
          PreTag={({ children, ...rest }: React.HTMLAttributes<HTMLPreElement>) => (
            <pre
              {...rest}
              onClick={(e) => {
                if (!linkable) return;
                const target = e.target as HTMLElement;
                const text = target.textContent?.trim();
                if (target.tagName === "SPAN" && text && /^\d+$/.test(text)) {
                  void copyLineLink(Number(text));
                }
              }}
            >
              {children}
            </pre>
          )}
        >
          {trimmed}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}
