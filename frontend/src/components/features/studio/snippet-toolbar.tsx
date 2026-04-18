"use client";

import { Tooltip } from "@/components/ui/tooltip";

const SNIPPETS = [
  {
    label: "Import anthropic",
    code: "import anthropic\nclient = anthropic.Anthropic()\n",
  },
  {
    label: "Claude message",
    code: 'message = client.messages.create(\n    model="claude-sonnet-4-6",\n    max_tokens=1024,\n    messages=[{"role": "user", "content": "Hello"}],\n)\nprint(message.content)\n',
  },
  {
    label: "Streaming",
    code: 'with client.messages.stream(\n    model="claude-sonnet-4-6",\n    max_tokens=1024,\n    messages=[{"role": "user", "content": "Hello"}],\n) as stream:\n    for text in stream.text_stream:\n        print(text, end="", flush=True)\n',
  },
  {
    label: "Tool use",
    code: 'tools = [\n    {\n        "name": "get_weather",\n        "description": "Get the weather for a city",\n        "input_schema": {\n            "type": "object",\n            "properties": {"city": {"type": "string"}},\n            "required": ["city"],\n        },\n    }\n]\n',
  },
  {
    label: "Try/except",
    code: 'try:\n    response = client.messages.create(\n        model="claude-sonnet-4-6",\n        max_tokens=256,\n        messages=[{"role": "user", "content": "Hello"}],\n    )\nexcept anthropic.APIError as e:\n    print(f"API error: {e}")\n',
  },
  {
    label: "Vision",
    code: 'import base64\n\nwith open("image.jpg", "rb") as f:\n    img_data = base64.standard_b64encode(f.read()).decode("utf-8")\n\nmessage = client.messages.create(\n    model="claude-sonnet-4-6",\n    max_tokens=1024,\n    messages=[\n        {\n            "role": "user",\n            "content": [\n                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_data}},\n                {"type": "text", "text": "What is in this image?"},\n            ],\n        }\n    ],\n)\nprint(message.content)\n',
  },
  {
    label: "Batch",
    code: 'batch = client.messages.batches.create(\n    requests=[\n        {"custom_id": "req-1", "params": {"model": "claude-sonnet-4-6", "max_tokens": 256, "messages": [{"role": "user", "content": "Hello"}]}},\n    ]\n)\nprint(batch.id)\n',
  },
] as const;

interface SnippetToolbarProps {
  onInsert: (code: string) => void;
}

export function SnippetToolbar({ onInsert }: SnippetToolbarProps) {
  return (
    <div
      className="flex flex-wrap gap-1 border-b border-border bg-muted/30 px-2 py-1"
      role="toolbar"
      aria-label="Code snippets"
    >
      {SNIPPETS.map((s) => (
        <Tooltip
          key={s.label}
          side="bottom"
          content={
            <pre className="text-[10px] leading-tight whitespace-pre-wrap">
              {s.code.length > 80 ? s.code.slice(0, 80) + "…" : s.code}
            </pre>
          }
        >
          <button
            type="button"
            className="inline-flex h-6 items-center rounded px-2 text-[11px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={() => onInsert(s.code)}
            aria-label={`Insert ${s.label} snippet`}
          >
            {s.label}
          </button>
        </Tooltip>
      ))}
    </div>
  );
}
