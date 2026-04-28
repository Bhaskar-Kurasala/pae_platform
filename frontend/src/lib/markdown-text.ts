/**
 * Frontend mirror of the backend's `_strip_markdown_to_text` helper used
 * for SRS card auto-seed sanitization. We need the same conversion on the
 * client for preview text on Notebook cards — those previews are short
 * plain-text blurbs ("the first ~180 chars of the body, dropped onto a
 * sticky-note tile") and they look broken when the underlying content
 * carries `**bold**`, ` ``` ` fences, `## headings`, list bullets, etc.
 *
 * Kept intentionally regex-only — input is bounded by the preview length
 * cap, so the runtime cost is negligible (<200µs) and the logic is small
 * enough to keep in lockstep with the Python version without a shared
 * package.
 */

const FENCED_CODE = /```[\s\S]*?```/g;
const INLINE_CODE = /`([^`\n]+)`/g;
const STRONG_STAR = /\*\*([^*\n]+)\*\*/g;
const STRONG_UNDER = /__([^_\n]+)__/g;
const EM_STAR = /(?<![*_])\*([^*\n]+)\*(?!\*)/g;
const EM_UNDER = /(?<![*_])_([^_\n]+)_(?!_)/g;
const LIST_BULLET = /(?:^|\n)\s*(?:[-*+]|\d+\.)\s+/g;
const HEADING = /(?:^|\n)\s*#{1,6}\s+/g;
const BLOCKQUOTE = /(?:^|\n)\s*>\s?/g;
const MULTI_NEWLINE = /\n{2,}/g;
const COLLAPSE_WS = /[ \t]+/g;

/**
 * Strip markdown formatting markers, keeping only the readable words.
 * Code fences vanish entirely — they're rarely the takeaway on a preview
 * card. Single newlines are preserved (so multi-paragraph notes still
 * render with reasonable spacing); double-newline runs collapse to a
 * single space so previews stay on one logical line.
 */
export function stripMarkdownToText(input: string): string {
  if (!input) return "";
  let s = input;
  s = s.replace(FENCED_CODE, " ");
  s = s.replace(INLINE_CODE, "$1");
  s = s.replace(STRONG_STAR, "$1");
  s = s.replace(STRONG_UNDER, "$1");
  s = s.replace(EM_STAR, "$1");
  s = s.replace(EM_UNDER, "$1");
  // Replace bullet/heading/quote markers with their leading newline (or
  // empty when at the start of input). The `(?:^|\n)` group is preserved
  // by capturing it.
  s = s.replace(LIST_BULLET, (m) => (m.startsWith("\n") ? "\n" : ""));
  s = s.replace(HEADING, (m) => (m.startsWith("\n") ? "\n" : ""));
  s = s.replace(BLOCKQUOTE, (m) => (m.startsWith("\n") ? "\n" : ""));
  s = s.replace(MULTI_NEWLINE, " ");
  s = s.replace(COLLAPSE_WS, " ");
  return s.trim();
}

/**
 * Trim a string at a word boundary so previews don't end mid-word.
 * Appends a single ellipsis when truncation actually happened.
 */
export function truncateAtWord(s: string, limit: number): string {
  if (s.length <= limit) return s;
  let cut = s.slice(0, limit).trimEnd();
  const space = cut.lastIndexOf(" ");
  if (space > limit * 0.6) cut = cut.slice(0, space);
  return cut.replace(/[,;: ]+$/, "") + "…";
}
