"use client";

import { Fragment, useCallback, useMemo } from "react";
import { AlertCircle, Clock, HelpCircle, Loader2 } from "lucide-react";
import { useStudio } from "./studio-context";

const TENSOR_SHAPE_RE = /\b(?:shape|size)=?\s*\(([^)]+)\)|torch\.Size\(\[([^\]]+)\]\)/i;

// Matches CPython-style traceback frame headers, e.g.
//   File "<student>", line 12, in <module>
//   File "/tmp/foo.py", line 3
const TRACEBACK_FRAME_RE = /File "([^"]*)", line (\d+)(?:, in [^\n]*)?/g;

function isTensorLike(repr: string): boolean {
  return /\b(tensor|ndarray|array|Tensor)\b/.test(repr) || TENSOR_SHAPE_RE.test(repr);
}

function extractShape(repr: string): string | null {
  const match = repr.match(TENSOR_SHAPE_RE);
  if (!match) return null;
  return (match[1] ?? match[2] ?? "").trim();
}

function revealLine(lineNumber: number) {
  if (typeof window === "undefined") return;
  try {
    window.dispatchEvent(
      new CustomEvent("studio.reveal_line", { detail: { lineNumber } }),
    );
  } catch {
    /* ignore */
  }
}

type TracebackSegment =
  | { kind: "text"; value: string }
  | { kind: "frame"; file: string; line: number; raw: string };

function parseTraceback(input: string): TracebackSegment[] {
  const segments: TracebackSegment[] = [];
  let lastIndex = 0;
  // Reset regex state — the `g` flag keeps state across calls otherwise.
  const re = new RegExp(TRACEBACK_FRAME_RE.source, "g");
  let match: RegExpExecArray | null;
  while ((match = re.exec(input)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ kind: "text", value: input.slice(lastIndex, match.index) });
    }
    segments.push({
      kind: "frame",
      file: match[1] ?? "",
      line: Number.parseInt(match[2] ?? "0", 10),
      raw: match[0],
    });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < input.length) {
    segments.push({ kind: "text", value: input.slice(lastIndex) });
  }
  return segments;
}

function dispatchAsk(question: string): void {
  if (typeof window === "undefined") return;
  try {
    window.dispatchEvent(new CustomEvent("studio:ask", { detail: { question } }));
  } catch {
    /* ignore */
  }
}

export function ExecutionTrace() {
  const { result, running, runError, stepIndex, setStepIndex, code } = useStudio();

  const handleExplainError = useCallback(
    (errorText: string) => {
      const question = `Explain this error:\n\`\`\`\n${errorText}\n\`\`\`\nMy code:\n\`\`\`python\n${code}\n\`\`\``;
      dispatchAsk(question);
    },
    [code],
  );

  const events = result?.events ?? [];
  const currentEvent = events[stepIndex] ?? null;
  const totalSteps = events.length;

  const stdoutLines = useMemo(() => {
    if (!result?.stdout) return [];
    return result.stdout.split("\n");
  }, [result?.stdout]);

  const errorSegments = useMemo(() => {
    if (!result?.error) return [];
    return parseTraceback(result.error);
  }, [result?.error]);

  const stderrSegments = useMemo(() => {
    if (!result?.stderr) return [];
    return parseTraceback(result.stderr);
  }, [result?.stderr]);

  if (running) {
    return (
      <div className="flex h-full items-center justify-center gap-2 p-4 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        <span>Running…</span>
      </div>
    );
  }

  if (runError) {
    return (
      <div className="flex h-full items-start gap-2 p-4 text-sm text-destructive">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <div>
          <div className="font-medium">Run failed</div>
          <div className="text-xs text-destructive/80">{runError}</div>
        </div>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-xs text-muted-foreground">
        Click <span className="mx-1 font-mono">Run</span> to execute and trace your code.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-2 overflow-hidden p-3 text-sm">
      {result.timed_out && (
        <div className="flex items-center gap-2 rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
          <Clock className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Execution hit the timeout — showing partial trace.</span>
        </div>
      )}

      {result.error && (
        <div className="flex items-start gap-2 rounded-md bg-destructive/10 px-2 py-1.5 text-xs text-destructive">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <pre className="whitespace-pre-wrap break-words font-mono">
              {errorSegments.length > 0
                ? errorSegments.map((seg, i) =>
                    seg.kind === "text" ? (
                      <Fragment key={i}>{seg.value}</Fragment>
                    ) : (
                      <button
                        key={i}
                        type="button"
                        onClick={() => revealLine(seg.line)}
                        title={`Jump to line ${seg.line}`}
                        className="inline rounded px-1 text-destructive underline decoration-destructive/40 underline-offset-2 hover:bg-destructive/15 hover:decoration-destructive focus:outline-none focus-visible:ring-2 focus-visible:ring-destructive"
                      >
                        {seg.raw}
                      </button>
                    ),
                  )
                : result.error}
            </pre>
            <button
              type="button"
              onClick={() => handleExplainError(result.error ?? "")}
              aria-label="Ask the tutor to explain this error"
              className="mt-1.5 inline-flex items-center gap-1 rounded-md border border-destructive/30 bg-background px-2 py-0.5 text-[11px] font-medium text-destructive hover:bg-destructive/10 transition"
            >
              <HelpCircle className="h-3 w-3" aria-hidden="true" />
              Why did this break?
            </button>
          </div>
        </div>
      )}

      {totalSteps > 0 && (
        <div className="shrink-0 space-y-1">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              Step <span className="font-mono text-foreground">{stepIndex + 1}</span> of{" "}
              <span className="font-mono">{totalSteps}</span>
            </span>
            {currentEvent && (
              <span>
                line <span className="font-mono text-foreground">{currentEvent.line}</span>
              </span>
            )}
          </div>
          <input
            type="range"
            min={0}
            max={totalSteps - 1}
            value={stepIndex}
            onChange={(e) => setStepIndex(Number(e.target.value))}
            aria-label="Step through execution"
            className="w-full accent-primary"
          />
        </div>
      )}

      <div className="grid flex-1 grid-cols-1 gap-3 overflow-hidden md:grid-cols-2">
        <section className="flex min-h-0 flex-col gap-1">
          <header className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Variables
          </header>
          <div className="flex-1 overflow-auto rounded-md border border-border bg-muted/30 p-2 text-xs">
            {currentEvent && Object.keys(currentEvent.locals).length > 0 ? (
              <table className="w-full border-collapse font-mono">
                <tbody>
                  {Object.entries(currentEvent.locals).map(([name, value]) => {
                    const tensor = isTensorLike(value);
                    const shape = tensor ? extractShape(value) : null;
                    return (
                      <tr key={name} className="border-b border-border/50 last:border-0">
                        <td className="py-1 pr-3 align-top text-primary">{name}</td>
                        <td className="py-1 align-top">
                          <span className="break-all text-foreground">{value}</span>
                          {shape && (
                            <span className="ml-2 inline-block rounded bg-secondary/20 px-1.5 py-0.5 text-[10px] font-medium text-secondary">
                              shape: {shape}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="text-muted-foreground">No variables at this step.</div>
            )}
          </div>
        </section>

        <section className="flex min-h-0 flex-col gap-1">
          <header className="flex items-center justify-between text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <span>Output</span>
            <span className="font-mono text-[10px] lowercase">
              exit {result.exit_code}
            </span>
          </header>
          <pre className="flex-1 overflow-auto rounded-md border border-border bg-muted/30 p-2 font-mono text-xs">
            {stdoutLines.length > 0 ? (
              stdoutLines.join("\n")
            ) : (
              <span className="text-muted-foreground">(no stdout)</span>
            )}
            {result.stderr && (
              <>
                {"\n"}
                <span className="text-destructive">
                  {stderrSegments.length > 0
                    ? stderrSegments.map((seg, i) =>
                        seg.kind === "text" ? (
                          <Fragment key={i}>{seg.value}</Fragment>
                        ) : (
                          <button
                            key={i}
                            type="button"
                            onClick={() => revealLine(seg.line)}
                            title={`Jump to line ${seg.line}`}
                            className="inline rounded px-1 underline decoration-destructive/40 underline-offset-2 hover:bg-destructive/15 hover:decoration-destructive focus:outline-none focus-visible:ring-2 focus-visible:ring-destructive"
                          >
                            {seg.raw}
                          </button>
                        ),
                      )
                    : result.stderr}
                </span>
                {"\n"}
                <button
                  type="button"
                  onClick={() => handleExplainError(result.stderr ?? "")}
                  aria-label="Ask the tutor to explain this stderr output"
                  className="mt-1 inline-flex items-center gap-1 rounded-md border border-destructive/30 bg-background px-2 py-0.5 text-[11px] font-medium text-destructive hover:bg-destructive/10 transition not-italic"
                >
                  <HelpCircle className="h-3 w-3" aria-hidden="true" />
                  Why did this break?
                </button>
              </>
            )}
          </pre>
        </section>
      </div>
    </div>
  );
}
