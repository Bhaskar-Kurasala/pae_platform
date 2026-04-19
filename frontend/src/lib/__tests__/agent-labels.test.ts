/**
 * P2-3 — tests for the agent-labels helper that drives the thinking-state
 * identity badge + display name. Covers every registered agent, unknown /
 * unmapped names, the `moa` orchestrator sentinel, empty strings, and
 * null / undefined.
 */
import { describe, expect, it } from "vitest";
import {
  AGENT_CATEGORY_COLORS,
  AGENT_LABELS,
  getAgentLabel,
} from "@/lib/agent-labels";

describe("getAgentLabel", () => {
  it("returns the correct display name + category color for all 20 registered agents", () => {
    // Sanity: the registry table has exactly 20 entries (matches docs/AGENTS.md).
    expect(Object.keys(AGENT_LABELS)).toHaveLength(20);

    for (const [key, meta] of Object.entries(AGENT_LABELS)) {
      const resolved = getAgentLabel(key);
      expect(resolved.displayName).toBe(meta.displayName);
      expect(resolved.colorClass).toBe(AGENT_CATEGORY_COLORS[meta.category]);
    }
  });

  it("maps each category to its expected accent color", () => {
    expect(AGENT_CATEGORY_COLORS.creation).toBe("bg-indigo-500");
    expect(AGENT_CATEGORY_COLORS.learning).toBe("bg-teal-500");
    expect(AGENT_CATEGORY_COLORS.analytics).toBe("bg-amber-500");
    expect(AGENT_CATEGORY_COLORS.career).toBe("bg-purple-500");
    expect(AGENT_CATEGORY_COLORS.engagement).toBe("bg-pink-500");
  });

  it("produces user-friendly display names for sample agents", () => {
    expect(getAgentLabel("socratic_tutor").displayName).toBe("Socratic Tutor");
    expect(getAgentLabel("code_review").displayName).toBe("Code Review");
    expect(getAgentLabel("mock_interview").displayName).toBe("Mock Interview");
    expect(getAgentLabel("mcq_factory").displayName).toBe("MCQ Factory");
  });

  it("falls back to Tutor + slate when name is null", () => {
    const result = getAgentLabel(null);
    expect(result.displayName).toBe("Tutor");
    expect(result.colorClass).toBe("bg-slate-400");
  });

  it("falls back to Tutor + slate when name is undefined", () => {
    const result = getAgentLabel(undefined);
    expect(result.displayName).toBe("Tutor");
    expect(result.colorClass).toBe("bg-slate-400");
  });

  it("falls back to Tutor + slate when name is an empty string", () => {
    const result = getAgentLabel("");
    expect(result.displayName).toBe("Tutor");
    expect(result.colorClass).toBe("bg-slate-400");
  });

  it("falls back to Tutor + slate for the 'moa' orchestrator sentinel", () => {
    const result = getAgentLabel("moa");
    expect(result.displayName).toBe("Tutor");
    expect(result.colorClass).toBe("bg-slate-400");
  });

  it("falls back to Tutor + slate for unknown agent names", () => {
    const result = getAgentLabel("some_future_agent_not_registered_yet");
    expect(result.displayName).toBe("Tutor");
    expect(result.colorClass).toBe("bg-slate-400");
  });

  it("is case-insensitive and trims whitespace", () => {
    expect(getAgentLabel("SOCRATIC_TUTOR").displayName).toBe("Socratic Tutor");
    expect(getAgentLabel("  socratic_tutor  ").displayName).toBe("Socratic Tutor");
    expect(getAgentLabel("MoA").displayName).toBe("Tutor");
  });

  it("assigns learning-category agents a teal dot", () => {
    expect(getAgentLabel("socratic_tutor").colorClass).toBe("bg-teal-500");
    expect(getAgentLabel("spaced_repetition").colorClass).toBe("bg-teal-500");
    expect(getAgentLabel("knowledge_graph").colorClass).toBe("bg-teal-500");
    expect(getAgentLabel("adaptive_path").colorClass).toBe("bg-teal-500");
  });

  it("assigns creation-category agents an indigo dot", () => {
    expect(getAgentLabel("coding_assistant").colorClass).toBe("bg-indigo-500");
    expect(getAgentLabel("mcq_factory").colorClass).toBe("bg-indigo-500");
    expect(getAgentLabel("curriculum_mapper").colorClass).toBe("bg-indigo-500");
  });

  it("assigns analytics-category agents an amber dot", () => {
    expect(getAgentLabel("adaptive_quiz").colorClass).toBe("bg-amber-500");
    expect(getAgentLabel("project_evaluator").colorClass).toBe("bg-amber-500");
    expect(getAgentLabel("progress_report").colorClass).toBe("bg-amber-500");
  });

  it("assigns career-category agents a purple dot", () => {
    expect(getAgentLabel("mock_interview").colorClass).toBe("bg-purple-500");
    expect(getAgentLabel("portfolio_builder").colorClass).toBe("bg-purple-500");
    expect(getAgentLabel("job_match").colorClass).toBe("bg-purple-500");
  });

  it("assigns engagement-category agents a pink dot", () => {
    expect(getAgentLabel("disrupt_prevention").colorClass).toBe("bg-pink-500");
    expect(getAgentLabel("peer_matching").colorClass).toBe("bg-pink-500");
    expect(getAgentLabel("community_celebrator").colorClass).toBe("bg-pink-500");
    expect(getAgentLabel("code_review").colorClass).toBe("bg-pink-500");
  });
});
