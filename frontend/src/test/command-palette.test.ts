import { describe, it, expect } from "vitest";
import { matches, type CommandItem } from "@/components/ui/command-palette";

const base: CommandItem = {
  id: "x",
  label: "At-risk students",
  hint: "Likely to churn",
  group: "Admin",
  keywords: ["risk", "churn", "drop off"],
  onSelect: () => {},
};

describe("command-palette matches()", () => {
  it("matches on empty query", () => {
    expect(matches(base, "")).toBe(true);
  });

  it("matches on label substring", () => {
    expect(matches(base, "risk")).toBe(true);
  });

  it("matches on keyword substring", () => {
    expect(matches(base, "churn")).toBe(true);
  });

  it("matches on hint substring", () => {
    expect(matches(base, "likely")).toBe(true);
  });

  it("matches on group name", () => {
    expect(matches(base, "admin")).toBe(true);
  });

  it("is case-insensitive", () => {
    expect(matches(base, "ADMIN")).toBe(true);
    expect(matches(base, "ChUrN")).toBe(true);
  });

  it("requires all tokens (AND semantics)", () => {
    expect(matches(base, "admin risk")).toBe(true);
    expect(matches(base, "admin kitten")).toBe(false);
  });

  it("handles multi-word keywords", () => {
    expect(matches(base, "drop")).toBe(true);
    expect(matches(base, "drop off")).toBe(true);
  });

  it("ignores extra whitespace", () => {
    expect(matches(base, "   admin   ")).toBe(true);
  });

  it("returns false when no fields contain the query", () => {
    expect(matches(base, "zzz")).toBe(false);
  });

  it("tolerates missing optional fields", () => {
    const minimal: CommandItem = { id: "m", label: "Sign out", onSelect: () => {} };
    expect(matches(minimal, "sign")).toBe(true);
    expect(matches(minimal, "churn")).toBe(false);
  });
});
