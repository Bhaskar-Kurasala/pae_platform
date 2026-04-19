/**
 * P2-3 — Centralized agent display metadata.
 *
 * Maps each of the 20 registered agents (see `docs/AGENTS.md`) to a
 * human-readable display name and a category tag. The category drives a
 * small accent-color badge shown next to the "… is thinking" indicator
 * in the assistant bubble.
 *
 * Kept as a tiny typed table rather than a backend lookup so the UI can
 * render the routed label BEFORE the first token arrives (the first SSE
 * event carries only `agent_name` — there's no extra round-trip).
 *
 * Categories follow `docs/AGENTS.md`:
 *   creation | learning | analytics | career | engagement
 *
 * The Master Orchestrator Agent (`moa`) is intentionally NOT listed: when
 * routing can't decide, the fallback below renders "Tutor" (see
 * `getAgentLabel`). Unknown / missing names also fall through to that.
 */
export type AgentCategory =
  | "creation"
  | "learning"
  | "analytics"
  | "career"
  | "engagement";

export interface AgentLabel {
  displayName: string;
  category: AgentCategory;
}

/**
 * 20 registered agents keyed by the lowercase agent_name emitted by the
 * backend (matches `AGENT_REGISTRY` in `backend/app/agents/registry.py`).
 */
export const AGENT_LABELS: Record<string, AgentLabel> = {
  // Creation (6)
  content_ingestion: { displayName: "Content Ingestion", category: "creation" },
  curriculum_mapper: { displayName: "Curriculum Mapper", category: "creation" },
  mcq_factory: { displayName: "MCQ Factory", category: "creation" },
  coding_assistant: { displayName: "Coding Assistant", category: "creation" },
  student_buddy: { displayName: "Student Buddy", category: "creation" },
  deep_capturer: { displayName: "Deep Capturer", category: "creation" },

  // Learning (4)
  socratic_tutor: { displayName: "Socratic Tutor", category: "learning" },
  spaced_repetition: { displayName: "Spaced Repetition", category: "learning" },
  knowledge_graph: { displayName: "Knowledge Graph", category: "learning" },
  adaptive_path: { displayName: "Adaptive Path", category: "learning" },

  // Analytics (3)
  adaptive_quiz: { displayName: "Adaptive Quiz", category: "analytics" },
  project_evaluator: { displayName: "Project Evaluator", category: "analytics" },
  progress_report: { displayName: "Progress Report", category: "analytics" },

  // Career (3)
  mock_interview: { displayName: "Mock Interview", category: "career" },
  portfolio_builder: { displayName: "Portfolio Builder", category: "career" },
  job_match: { displayName: "Job Match", category: "career" },

  // Engagement (4)
  disrupt_prevention: { displayName: "Re-engagement Coach", category: "engagement" },
  peer_matching: { displayName: "Peer Matching", category: "engagement" },
  community_celebrator: { displayName: "Community Celebrator", category: "engagement" },
  code_review: { displayName: "Code Review", category: "engagement" },
};

/**
 * Accent classes per category — used as a 6px round dot next to the
 * "thinking" indicator. Uses tailwind's solid `bg-*-500` tokens so the
 * dot reads clearly on both light and dark surfaces.
 *
 *   creation   → indigo
 *   learning   → teal
 *   analytics  → amber
 *   career     → purple
 *   engagement → pink
 *
 * Fallback for unknown agents: slate.
 */
export const AGENT_CATEGORY_COLORS: Record<AgentCategory, string> = {
  creation: "bg-indigo-500",
  learning: "bg-teal-500",
  analytics: "bg-amber-500",
  career: "bg-purple-500",
  engagement: "bg-pink-500",
};

const FALLBACK_LABEL: AgentLabel = {
  displayName: "Tutor",
  category: "learning",
};
const FALLBACK_COLOR = "bg-slate-400";

export interface ResolvedAgentLabel {
  displayName: string;
  colorClass: string;
}

/**
 * Resolve an agent's display metadata from its backend `agent_name`.
 *
 * Falls back to "Tutor" + a neutral slate badge when:
 *   - name is null / undefined / empty
 *   - name is "moa" (orchestrator didn't route to a concrete agent)
 *   - name is not in the 20-agent table (unknown / future agent)
 *
 * Matching is case-insensitive to forgive backends that upper/title-case
 * the agent name in transit.
 */
export function getAgentLabel(
  name?: string | null,
): ResolvedAgentLabel {
  if (!name) {
    return { displayName: FALLBACK_LABEL.displayName, colorClass: FALLBACK_COLOR };
  }
  const key = name.toLowerCase().trim();
  if (!key || key === "moa") {
    return { displayName: FALLBACK_LABEL.displayName, colorClass: FALLBACK_COLOR };
  }
  const label = AGENT_LABELS[key];
  if (!label) {
    return { displayName: FALLBACK_LABEL.displayName, colorClass: FALLBACK_COLOR };
  }
  return {
    displayName: label.displayName,
    colorClass: AGENT_CATEGORY_COLORS[label.category],
  };
}
