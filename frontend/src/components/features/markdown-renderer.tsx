"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CodeBlock } from "@/components/ui/code-block";
import type { Components } from "react-markdown";

const components: Components = {
  // ── Headings ─────────────────────────────────────────────────
  h1: ({ children }) => (
    <h1 className="text-xl font-bold text-foreground mt-5 mb-3 pb-2 border-b border-border/40 first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-base font-semibold text-foreground mt-5 mb-2.5 first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-sm font-semibold text-foreground mt-4 mb-2 first:mt-0">
      {children}
    </h3>
  ),

  // ── Paragraph ────────────────────────────────────────────────
  p: ({ children }) => (
    <p className="text-sm text-foreground leading-7 my-2.5 first:mt-0 last:mb-0">
      {children}
    </p>
  ),

  // ── Bold / Italic ────────────────────────────────────────────
  strong: ({ children }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  em: ({ children }) => (
    <em className="italic text-foreground/80">{children}</em>
  ),

  // ── Lists ────────────────────────────────────────────────────
  ul: ({ children }) => (
    <ul className="my-3 space-y-1.5 pl-1">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="my-3 space-y-1.5 pl-1 list-decimal list-inside">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="flex items-start gap-2.5 text-sm text-foreground leading-6 [&>p]:my-0 [&>p]:leading-6">
      <span className="mt-2 h-1.5 w-1.5 rounded-full bg-primary/60 shrink-0" aria-hidden="true" />
      <span className="flex-1 min-w-0">{children}</span>
    </li>
  ),

  // ── Inline code ──────────────────────────────────────────────
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  code: ({ className, children, ...props }: any) => {
    const match = /language-(\w+)/.exec(className ?? "");
    const isBlock = Boolean(match);
    const codeString = String(children).replace(/\n$/, "");

    if (isBlock) {
      return <CodeBlock code={codeString} language={match?.[1] ?? "text"} />;
    }

    return (
      <code
        className="rounded-md bg-muted px-1.5 py-0.5 text-[0.8em] font-mono text-foreground border border-border/30"
        {...props}
      >
        {children}
      </code>
    );
  },

  // ── Blockquote ───────────────────────────────────────────────
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-4 border-primary/40 pl-4 py-1 bg-primary/5 rounded-r-lg">
      <div className="text-sm text-muted-foreground italic leading-6">{children}</div>
    </blockquote>
  ),

  // ── Horizontal rule ──────────────────────────────────────────
  hr: () => <hr className="my-5 border-border/40" />,

  // ── Table ────────────────────────────────────────────────────
  table: ({ children }) => (
    <div className="my-4 overflow-x-auto rounded-xl border border-border/50 shadow-sm">
      <table className="w-full text-sm border-collapse">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="bg-muted/70">{children}</thead>
  ),
  tbody: ({ children }) => (
    <tbody className="divide-y divide-border/30">{children}</tbody>
  ),
  tr: ({ children }) => (
    <tr className="hover:bg-muted/30 transition-colors">{children}</tr>
  ),
  th: ({ children }) => (
    <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground whitespace-nowrap">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-4 py-3 text-sm text-foreground align-top">{children}</td>
  ),

  // ── Links ────────────────────────────────────────────────────
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary underline underline-offset-2 hover:text-primary/80 transition-colors"
    >
      {children}
    </a>
  ),
};

export function MarkdownRenderer({ content, isStreaming = false }: { content: string; isStreaming?: boolean }) {
  return (
    <div className="min-w-0">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
      {isStreaming && (
        <span
          className="inline-block w-0.5 h-4 bg-primary animate-pulse rounded-full ml-0.5 align-middle"
          aria-hidden="true"
        />
      )}
    </div>
  );
}
