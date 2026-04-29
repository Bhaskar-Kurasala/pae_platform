/**
 * F10 — buildCallInviteMailto unit tests.
 *
 * Locks the URL-encoding contract + slip-context propagation. The
 * downstream consumer is an `<a href={...}>` so any encoding bug
 * silently corrupts the message in the operator's mail client —
 * tests are the only guard.
 */
import { describe, expect, it } from "vitest";
import { buildCallInviteMailto } from "@/lib/calendar-mailto";

function parseMailto(url: string): {
  to: string;
  subject: string;
  body: string;
} {
  expect(url.startsWith("mailto:")).toBe(true);
  const [head, query] = url.slice("mailto:".length).split("?");
  const to = decodeURIComponent(head);
  const params = new URLSearchParams(query);
  return {
    to,
    subject: params.get("subject") ?? "",
    body: params.get("body") ?? "",
  };
}

describe("buildCallInviteMailto", () => {
  it("encodes the recipient email and returns a mailto: URL", () => {
    const url = buildCallInviteMailto({
      studentEmail: "alice+test@example.com",
      studentName: "Alice Walker",
    });
    expect(url.startsWith("mailto:alice%2Btest%40example.com?")).toBe(true);
    const parsed = parseMailto(url);
    expect(parsed.to).toBe("alice+test@example.com");
  });

  it("uses the student's first name in the body greeting", () => {
    const url = buildCallInviteMailto({
      studentEmail: "alice@example.com",
      studentName: "Alice Walker",
    });
    const { body } = parseMailto(url);
    expect(body).toMatch(/^Hey Alice,/);
  });

  it("falls back to 'there' when no student name is provided", () => {
    const url = buildCallInviteMailto({ studentEmail: "anon@example.com" });
    const { body, subject } = parseMailto(url);
    expect(body).toMatch(/^Hey there,/);
    expect(subject).toBe("Quick call?");
  });

  it("references the slip type in subject and body when provided", () => {
    const url = buildCallInviteMailto({
      studentEmail: "alice@example.com",
      studentName: "Alice",
      slipType: "paid_silent",
    });
    const { subject, body } = parseMailto(url);
    expect(subject).toBe("Quick call about the AI engineer track?");
    // The paid_silent opener mentions being quiet since signup.
    expect(body.toLowerCase()).toContain("quiet");
  });

  it("appends risk_reason as parenthetical context when supplied", () => {
    const url = buildCallInviteMailto({
      studentEmail: "alice@example.com",
      studentName: "Alice",
      slipType: "capstone_stalled",
      riskReason: "no submissions in 14 days",
    });
    const { body } = parseMailto(url);
    expect(body).toContain("(For context on my end: no submissions in 14 days.)");
  });

  it("encodes spaces as %20 (not +) so mail clients render them correctly", () => {
    const url = buildCallInviteMailto({
      studentEmail: "alice@example.com",
      studentName: "Alice",
    });
    // The body contains spaces; they MUST be %20, never `+` (Outlook
    // renders `+` literally inside mailto: bodies).
    const query = url.split("?")[1];
    expect(query).not.toMatch(/\+/);
    expect(query).toContain("%20");
  });

  it("throws when studentEmail is empty", () => {
    expect(() =>
      buildCallInviteMailto({ studentEmail: "", studentName: "Alice" }),
    ).toThrow(/studentEmail/);
  });

  it("uses generic opener for unknown slip types", () => {
    const url = buildCallInviteMailto({
      studentEmail: "alice@example.com",
      studentName: "Alice",
      slipType: "zzz_not_real",
    });
    const { subject, body } = parseMailto(url);
    expect(subject).toBe("Quick call?");
    expect(body).toContain("quick call");
  });
});
