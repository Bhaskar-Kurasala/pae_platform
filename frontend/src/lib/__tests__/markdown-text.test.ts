/**
 * P-Notebook2: frontend markdown stripper used for Notebook preview tiles.
 * Mirrors the backend `_strip_markdown_to_text` behaviour so previews and
 * SRS card auto-seeds stay in lockstep.
 */
import { describe, expect, it } from "vitest";
import { stripMarkdownToText, truncateAtWord } from "@/lib/markdown-text";

describe("stripMarkdownToText", () => {
  it("removes fenced code blocks entirely", () => {
    const md = "Here is my note.\n\n```python\ndef f():\n    return 1\n```\n\nDone.";
    const out = stripMarkdownToText(md);
    expect(out).not.toContain("def f");
    expect(out).toContain("Here is my note");
    expect(out).toContain("Done");
  });

  it("preserves the inner text of inline code", () => {
    const out = stripMarkdownToText("Use `asyncio.gather` for concurrency.");
    expect(out).toBe("Use asyncio.gather for concurrency.");
  });

  it("strips bold/italic markers but keeps the words", () => {
    const out = stripMarkdownToText(
      "This is **bold** and _italic_ and *also italic* and __underbold__.",
    );
    expect(out).not.toMatch(/[*_]/);
    expect(out).toContain("bold");
    expect(out).toContain("italic");
    expect(out).toContain("underbold");
  });

  it("removes list bullets and numbered prefixes", () => {
    const out = stripMarkdownToText(
      "- First item\n- Second item\n\n1. Numbered\n2. Two",
    );
    expect(out).toContain("First item");
    expect(out).toContain("Numbered");
    expect(out).not.toMatch(/^[-*+]/);
    expect(out).not.toMatch(/\d+\.\s/);
  });

  it("removes heading markers and blockquote chevrons", () => {
    const out = stripMarkdownToText("## Heading\n\n> a quote\n\nbody");
    expect(out).toContain("Heading");
    expect(out).toContain("a quote");
    expect(out).toContain("body");
    expect(out).not.toMatch(/##|>/);
  });

  it("collapses blank-line runs to a single space", () => {
    const out = stripMarkdownToText("First.\n\n\n\nSecond.\n\nThird.");
    expect(out).not.toContain("\n\n");
    expect(out).toContain("First.");
    expect(out).toContain("Second.");
    expect(out).toContain("Third.");
  });

  it("handles empty input safely", () => {
    expect(stripMarkdownToText("")).toBe("");
  });

  it("end-to-end on realistic chat markdown", () => {
    const md = [
      "## RAG: Retrieval-Augmented Generation",
      "",
      "**RAG** stands for **Retrieval-Augmented Generation**.",
      "",
      "It works in three steps:",
      "1. Indexing: split docs into chunks.",
      "2. Retrieval: fetch the most similar chunks.",
      "3. Generation: feed chunks into the LLM.",
      "",
      "```python",
      "def retrieve(q):",
      "    return vector_db.query(q)",
      "```",
    ].join("\n");
    const out = stripMarkdownToText(md);
    expect(out).not.toMatch(/\*\*|##|```|def retrieve/);
    expect(out).toContain("RAG");
    expect(out).toContain("Retrieval-Augmented Generation");
  });
});

describe("truncateAtWord", () => {
  it("returns the input unchanged when shorter than the limit", () => {
    expect(truncateAtWord("short", 30)).toBe("short");
  });

  it("cuts at a word boundary and adds ellipsis", () => {
    const out = truncateAtWord(
      "This is a fairly long sentence we want to clip cleanly.",
      30,
    );
    expect(out.endsWith("…")).toBe(true);
    expect(out.length).toBeLessThanOrEqual(31);
    expect(out).not.toContain("cleanly");
  });

  it("does not trim into a 3-char fragment when no good word boundary exists", () => {
    // "verylongunbrokensequence" — word boundary fallback should kick in.
    const out = truncateAtWord("verylongunbrokensequenceofnowhitespace", 12);
    expect(out.endsWith("…")).toBe(true);
    expect(out.length).toBeLessThanOrEqual(13);
  });
});
