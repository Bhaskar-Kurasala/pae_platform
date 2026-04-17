"use client";

import { type ElementType, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  Brain,
  Briefcase,
  Code2,
  GitBranch,
  GitMerge,
  Layers,
  LineChart,
  MessageSquare,
  Network,
  Repeat2,
  Search,
  Sparkles,
  Star,
  Trophy,
  Users,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Agent catalogue (matches AGENTS.md)
// ---------------------------------------------------------------------------

type Category = "creation" | "learning" | "analytics" | "career" | "engagement";

interface Agent {
  name: string;
  icon: ElementType;
  description: string;
  triggers: readonly string[];
  category: Category;
  model: string | null;
  stub: boolean;
}

const agents: Agent[] = [
  // Creation
  {
    name: "Content Ingestion",
    icon: GitBranch,
    description: "Processes GitHub push events and YouTube videos into structured course content automatically.",
    triggers: ["ingest", "youtube", "github push"],
    category: "creation",
    model: null,
    stub: true,
  },
  {
    name: "Curriculum Mapper",
    icon: Layers,
    description: "Maps raw content metadata to an ordered curriculum, generating lesson sequences from any topic.",
    triggers: ["map curriculum", "lesson order"],
    category: "creation",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  {
    name: "MCQ Factory",
    icon: Sparkles,
    description: "Generates 5 high-quality multiple-choice questions per call with distractors and explanations.",
    triggers: ["generate questions", "create mcq"],
    category: "creation",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  {
    name: "Coding Assistant",
    icon: Code2,
    description: "Delivers PR-style inline code feedback, debugging help, and refactoring suggestions.",
    triggers: ["help with code", "debug", "fix my code"],
    category: "creation",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  {
    name: "Student Buddy",
    icon: MessageSquare,
    description: "Delivers TL;DR and ELI5 explanations in under 200 words — perfect for quick concept checks.",
    triggers: ["tldr", "eli5", "quick explanation"],
    category: "creation",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  {
    name: "Deep Capturer",
    icon: Network,
    description: "Synthesizes weekly connections across lessons to surface latent concept relationships.",
    triggers: ["weekly summary", "concept connections"],
    category: "creation",
    model: null,
    stub: true,
  },
  // Learning
  {
    name: "Socratic Tutor",
    icon: Search,
    description: "Guides understanding through targeted questions using Bloom's taxonomy. Never just gives answers.",
    triggers: ["what is", "explain", "help me understand"],
    category: "learning",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  {
    name: "Spaced Repetition",
    icon: Repeat2,
    description: "Schedules your next review at the optimal moment using the SM-2 algorithm — no LLM needed.",
    triggers: ["review", "flashcard", "due cards"],
    category: "learning",
    model: null,
    stub: false,
  },
  {
    name: "Knowledge Graph",
    icon: Network,
    description: "Tracks your concept mastery with an EMA scoring model and visualizes your skill landscape.",
    triggers: ["concept mastery", "skill map"],
    category: "learning",
    model: null,
    stub: true,
  },
  {
    name: "Adaptive Path",
    icon: GitMerge,
    description: "Personalizes your lesson order in real-time based on quiz scores and demonstrated knowledge gaps.",
    triggers: ["learning path", "study plan", "next lesson"],
    category: "learning",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  // Analytics
  {
    name: "Adaptive Quiz",
    icon: Brain,
    description: "Dynamically adjusts question difficulty as you answer, targeting your precise skill boundary.",
    triggers: ["quiz me", "MCQ", "multiple choice"],
    category: "analytics",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  {
    name: "Project Evaluator",
    icon: Star,
    description: "Scores capstone projects on a 5-dimension rubric (correctness, design, tests, docs, performance).",
    triggers: ["evaluate project", "capstone"],
    category: "analytics",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  {
    name: "Progress Report",
    icon: LineChart,
    description: "Generates narrative weekly progress summaries with trend analysis and actionable next steps.",
    triggers: ["my progress", "weekly report", "how am I doing"],
    category: "analytics",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  // Career
  {
    name: "Mock Interviewer",
    icon: Briefcase,
    description: "Runs FAANG-style AI engineering system design interviews with structured evaluation feedback.",
    triggers: ["mock interview", "system design", "interview prep"],
    category: "career",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  {
    name: "Portfolio Builder",
    icon: BookOpen,
    description: "Turns your completed projects into structured, shareable Markdown portfolio entries.",
    triggers: ["build portfolio", "showcase project"],
    category: "career",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  {
    name: "Job Match",
    icon: Search,
    description: "Ranks job listings by skill overlap with your profile. TODO: Adzuna / LinkedIn integration.",
    triggers: ["find jobs", "job listings", "career"],
    category: "career",
    model: null,
    stub: true,
  },
  // Engagement
  {
    name: "Disrupt Prevention",
    icon: Zap,
    description: "Detects inactivity and sends personalized re-engagement nudges (activates after 3+ days inactive).",
    triggers: ["re-engage", "inactive", "churn"],
    category: "engagement",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  {
    name: "Peer Matching",
    icon: Users,
    description: "Finds study partners whose learning goals and progress best overlap with yours.",
    triggers: ["study partner", "find peers"],
    category: "engagement",
    model: null,
    stub: true,
  },
  {
    name: "Community Celebrator",
    icon: Trophy,
    description: "Crafts personalized, shareable milestone celebration messages in multiple formats.",
    triggers: ["celebrate", "milestone", "completed"],
    category: "engagement",
    model: "claude-sonnet-4-6",
    stub: false,
  },
  {
    name: "Code Review",
    icon: Code2,
    description: "Runs ruff analysis and returns a structured JSON review with score 0–100 and inline comments.",
    triggers: ["review my code", "check my code"],
    category: "engagement",
    model: "claude-sonnet-4-6",
    stub: false,
  },
];

// ---------------------------------------------------------------------------
// Filter tabs
// ---------------------------------------------------------------------------

type FilterTab = "all" | Category;

const tabs: { value: FilterTab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "creation", label: "Creation" },
  { value: "learning", label: "Learning" },
  { value: "analytics", label: "Analytics" },
  { value: "career", label: "Career" },
  { value: "engagement", label: "Engagement" },
];

// ---------------------------------------------------------------------------
// Card colours
// ---------------------------------------------------------------------------

function cardBorder(category: Category): string {
  if (category === "creation" || category === "learning")
    return "border-primary/25 hover:border-primary/50";
  if (category === "career" || category === "engagement")
    return "border-[#7C3AED]/25 hover:border-[#7C3AED]/50";
  return "border-border hover:border-border/80";
}

function iconBg(category: Category): string {
  if (category === "creation" || category === "learning") return "bg-primary/10";
  if (category === "career" || category === "engagement") return "bg-[#7C3AED]/10";
  return "bg-muted";
}

function iconColor(category: Category): string {
  if (category === "creation" || category === "learning") return "text-primary";
  if (category === "career" || category === "engagement") return "text-[#7C3AED]";
  return "text-muted-foreground";
}

function categoryLabel(category: Category): string {
  return category.charAt(0).toUpperCase() + category.slice(1);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AgentsGrid() {
  const [active, setActive] = useState<FilterTab>("all");

  const filtered =
    active === "all" ? agents : agents.filter((a) => a.category === active);

  return (
    <div>
      {/* Filter tabs */}
      <div
        role="tablist"
        aria-label="Filter agents by category"
        className="flex flex-wrap gap-2 justify-center mb-10"
      >
        {tabs.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={active === value}
            onClick={() => setActive(value)}
            className={cn(
              "rounded-full px-4 py-1.5 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none",
              active === value
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground hover:bg-muted/80",
            )}
          >
            {label}
            {value === "all" && (
              <span className="ml-1.5 text-xs opacity-70">{agents.length}</span>
            )}
          </button>
        ))}
      </div>

      {/* Grid */}
      <div
        role="tabpanel"
        aria-label={`${active === "all" ? "All" : categoryLabel(active as Category)} agents`}
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
      >
        {filtered.map(({ name, icon: Icon, description, triggers, category, model, stub }) => (
          <article
            key={name}
            className={cn(
              "rounded-xl border bg-card p-5 flex flex-col gap-3 transition-all hover:shadow-sm",
              cardBorder(category),
            )}
          >
            {/* Icon + badge row */}
            <div className="flex items-start justify-between">
              <div
                className={cn(
                  "flex h-9 w-9 items-center justify-center rounded-lg shrink-0",
                  iconBg(category),
                )}
              >
                <Icon
                  className={cn("h-5 w-5", iconColor(category))}
                  aria-hidden="true"
                />
              </div>
              <div className="flex flex-col items-end gap-1">
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-xs font-medium",
                    category === "creation" || category === "learning"
                      ? "bg-primary/10 text-primary"
                      : category === "career" || category === "engagement"
                      ? "bg-[#7C3AED]/10 text-[#7C3AED]"
                      : "bg-muted text-muted-foreground",
                  )}
                >
                  {categoryLabel(category)}
                </span>
                {stub && (
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    Coming soon
                  </span>
                )}
              </div>
            </div>

            {/* Name + description */}
            <div className="flex-1">
              <h3 className="text-sm font-semibold text-foreground mb-1">{name}</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">{description}</p>
            </div>

            {/* Trigger phrases */}
            <div>
              <div className="text-xs text-muted-foreground mb-1.5">Trigger phrases:</div>
              <div className="flex flex-wrap gap-1">
                {triggers.map((t) => (
                  <span
                    key={t}
                    className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono text-muted-foreground"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>

            {/* Model + CTA */}
            <div className="flex items-center justify-between pt-1 border-t border-border">
              <span className="text-xs text-muted-foreground font-mono">
                {model ?? "rule-based"}
              </span>
              {!stub ? (
                <Link
                  href="/register"
                  aria-label={`Try ${name} agent`}
                  className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80 transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none rounded"
                >
                  Try it <ArrowRight className="h-3 w-3" aria-hidden="true" />
                </Link>
              ) : (
                <span className="text-xs text-muted-foreground">In development</span>
              )}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
