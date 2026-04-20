"use client";

import { useRef, useState } from "react";
import { ChevronDown, Code2, X } from "lucide-react";

const SNIPPETS = [
  {
    label: "Import anthropic",
    tag: "setup",
    hint: "Start every script — create the client",
    code: "import anthropic\nclient = anthropic.Anthropic()\n",
  },
  {
    label: "Claude message",
    tag: "basics",
    hint: "Send a message and print the reply",
    code: 'message = client.messages.create(\n    model="claude-sonnet-4-6",\n    max_tokens=1024,\n    messages=[{"role": "user", "content": "Hello"}],\n)\nprint(message.content)\n',
  },
  {
    label: "Streaming",
    tag: "streaming",
    hint: "Stream tokens as they arrive (real-time output)",
    code: 'with client.messages.stream(\n    model="claude-sonnet-4-6",\n    max_tokens=1024,\n    messages=[{"role": "user", "content": "Hello"}],\n) as stream:\n    for text in stream.text_stream:\n        print(text, end="", flush=True)\n',
  },
  {
    label: "Tool use",
    tag: "tools",
    hint: "Let Claude call your functions",
    code: 'tools = [\n    {\n        "name": "get_weather",\n        "description": "Get the weather for a city",\n        "input_schema": {\n            "type": "object",\n            "properties": {"city": {"type": "string"}},\n            "required": ["city"],\n        },\n    }\n]\n',
  },
  {
    label: "Try/except",
    tag: "errors",
    hint: "Handle API errors gracefully in production",
    code: 'try:\n    response = client.messages.create(\n        model="claude-sonnet-4-6",\n        max_tokens=256,\n        messages=[{"role": "user", "content": "Hello"}],\n    )\nexcept anthropic.APIError as e:\n    print(f"API error: {e}")\n',
  },
  {
    label: "Vision",
    tag: "multimodal",
    hint: "Send an image to Claude and ask about it",
    code: 'import base64\n\nwith open("image.jpg", "rb") as f:\n    img_data = base64.standard_b64encode(f.read()).decode("utf-8")\n\nmessage = client.messages.create(\n    model="claude-sonnet-4-6",\n    max_tokens=1024,\n    messages=[\n        {\n            "role": "user",\n            "content": [\n                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_data}},\n                {"type": "text", "text": "What is in this image?"},\n            ],\n        }\n    ],\n)\nprint(message.content)\n',
  },
  {
    label: "Batch",
    tag: "advanced",
    hint: "Process many prompts in one API call",
    code: 'batch = client.messages.batches.create(\n    requests=[\n        {"custom_id": "req-1", "params": {"model": "claude-sonnet-4-6", "max_tokens": 256, "messages": [{"role": "user", "content": "Hello"}]}},\n    ]\n)\nprint(batch.id)\n',
  },
] as const;

const TAG_COLORS: Record<string, string> = {
  setup:      "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  basics:     "bg-sky-500/15 text-sky-700 dark:text-sky-400",
  streaming:  "bg-violet-500/15 text-violet-700 dark:text-violet-400",
  tools:      "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  errors:     "bg-red-500/15 text-red-700 dark:text-red-400",
  multimodal: "bg-pink-500/15 text-pink-700 dark:text-pink-400",
  advanced:   "bg-slate-500/15 text-slate-700 dark:text-slate-400",
};

interface SnippetToolbarProps {
  onInsert: (code: string) => void;
}

export function SnippetToolbar({ onInsert }: SnippetToolbarProps) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  function handlePick(code: string) {
    onInsert(code);
    setOpen(false);
  }

  return (
    <div
      className="relative flex items-center gap-2 border-b border-border bg-muted/30 px-2 py-1"
      role="toolbar"
      aria-label="Code snippets"
    >
      {/* Trigger button — clearly labelled so students know what this is */}
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Insert a code snippet — pick a ready-made Anthropic API pattern"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2 py-1 text-xs font-medium text-muted-foreground transition hover:border-primary/40 hover:bg-muted hover:text-foreground"
      >
        <Code2 className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
        <span>Snippets</span>
        <ChevronDown
          className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>

      {/* Discoverable hint next to the button */}
      {!open && (
        <span className="text-[10px] text-muted-foreground/70 hidden sm:inline">
          ← Click to insert ready-made Claude API patterns
        </span>
      )}

      {/* Dropdown panel */}
      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-10"
            aria-hidden="true"
            onClick={() => setOpen(false)}
          />

          <div
            role="listbox"
            aria-label="Claude API snippet templates"
            className="absolute left-0 top-full z-20 mt-1 w-80 rounded-lg border border-border bg-card shadow-lg"
          >
            {/* Panel header */}
            <div className="flex items-center justify-between border-b border-border px-3 py-2">
              <div>
                <p className="text-xs font-semibold text-foreground">Claude API Snippets</p>
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  Click any pattern to insert it into the editor
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close snippets panel"
                className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>

            {/* Snippet list */}
            <ul className="max-h-72 overflow-y-auto py-1">
              {SNIPPETS.map((s) => (
                <li key={s.label} role="option" aria-selected="false">
                  <button
                    type="button"
                    onClick={() => handlePick(s.code)}
                    aria-label={`Insert ${s.label} snippet: ${s.hint}`}
                    className="flex w-full items-start gap-2.5 px-3 py-2 text-left hover:bg-muted/60"
                  >
                    <span
                      className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${TAG_COLORS[s.tag] ?? ""}`}
                    >
                      {s.tag}
                    </span>
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-foreground">{s.label}</p>
                      <p className="text-[10px] text-muted-foreground leading-snug">{s.hint}</p>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
