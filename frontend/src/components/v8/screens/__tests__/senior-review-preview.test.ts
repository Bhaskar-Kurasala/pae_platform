/**
 * PR2/A5.2 — senior review preview-tile copy must be plain text.
 *
 * The senior-review LLM routinely returns `**bold**`, ``backticks``, and
 * the occasional ```python fence``` in the strengths / concern.message /
 * next_step fields. Those payloads render into a small `<span>` with
 * line-clamp styling on the Practice screen, so raw markdown leaked
 * through as literal asterisks before this fix.
 *
 * We pin the helper at the module boundary so a future "let's just dump
 * the LLM body in" doesn't quietly resurrect the leak.
 */
import { describe, it, expect } from "vitest";

import { cleanReviewBody } from "@/components/v8/screens/practice-screen";

describe("cleanReviewBody (PR2/A5.2)", () => {
  it("strips bold and italic markdown", () => {
    expect(cleanReviewBody("**ship it** and *move on*")).toBe(
      "ship it and move on",
    );
  });

  it("strips inline backticks", () => {
    expect(cleanReviewBody("call `await asyncio.gather()` here")).toBe(
      "call await asyncio.gather() here",
    );
  });

  it("drops fenced code blocks (avoids dumping ``` into a small tile)", () => {
    const raw = "```python\nimport os\n```\nThen wire the env var.";
    const out = cleanReviewBody(raw);
    expect(out).not.toContain("```");
    // The senior-review tile is a small <span>; dropping the fenced
    // payload entirely is intentional — students drill into the full
    // review surface to see code. We just need plain prose here.
    expect(out).toContain("Then wire the env var");
  });

  it("truncates very long bodies at a word boundary with an ellipsis", () => {
    const long = "ship the gather call ".repeat(40);
    const out = cleanReviewBody(long);
    expect(out.length).toBeLessThanOrEqual(201);
    expect(out.endsWith("…")).toBe(true);
  });

  it("leaves short plain text unchanged", () => {
    expect(cleanReviewBody("Nothing flagged.")).toBe("Nothing flagged.");
  });
});
