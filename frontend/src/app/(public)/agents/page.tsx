import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { GradientMesh } from "@/components/ui/gradient-mesh";
import { MotionFade } from "@/components/ui/motion-fade";
import { AgentsGrid } from "./_agents-grid";

export const metadata: Metadata = {
  title: "AI Agents — PAE Platform",
  description:
    "Meet your 20 AI coaches. Every agent is specialized for a different aspect of your learning journey — from content ingestion to career support.",
};

// ---------------------------------------------------------------------------
// Agent category descriptions
// ---------------------------------------------------------------------------

const categories = [
  {
    name: "Creation",
    count: 6,
    desc: "Agents that build and curate the curriculum itself — ingesting content, mapping lessons, and generating exercises.",
    color: "bg-primary/10 text-primary",
  },
  {
    name: "Learning",
    count: 4,
    desc: "Agents that actively coach you — Socratic tutoring, spaced repetition scheduling, and adaptive path planning.",
    color: "bg-primary/10 text-primary",
  },
  {
    name: "Analytics",
    count: 3,
    desc: "Agents that measure and report — adaptive quizzes, project evaluation, and weekly progress narratives.",
    color: "bg-muted text-muted-foreground",
  },
  {
    name: "Career",
    count: 3,
    desc: "Agents that accelerate your career — mock interviews, portfolio entries, and job match scoring.",
    color: "bg-[#7C3AED]/10 text-[#7C3AED]",
  },
  {
    name: "Engagement",
    count: 4,
    desc: "Agents that keep you moving — re-engagement nudges, peer matching, milestone celebrations, and code review.",
    color: "bg-[#7C3AED]/10 text-[#7C3AED]",
  },
] as const;

// ---------------------------------------------------------------------------
// Page (Server Component — grid filter is client island)
// ---------------------------------------------------------------------------

export default function AgentsPage() {
  return (
    <div className="overflow-x-hidden">
      {/* Hero */}
      <section className="relative overflow-hidden py-24 px-4">
        <GradientMesh />
        <MotionFade>
          <div className="max-w-3xl mx-auto text-center">
            <div className="inline-flex items-center rounded-full border border-border bg-muted px-3 py-1 text-xs font-medium text-muted-foreground mb-6">
              20 specialized AI coaches
            </div>
            <h1 className="text-[clamp(2rem,4vw,3rem)] font-bold tracking-tight mb-4">
              Meet your AI coaches
            </h1>
            <p className="text-lg text-muted-foreground leading-relaxed max-w-xl mx-auto">
              Every agent is built for a specific job. Together, they cover every phase of
              your learning journey — from your first lesson to your first production deployment.
            </p>
          </div>
        </MotionFade>
      </section>

      {/* Category overview */}
      <section
        aria-label="Agent categories"
        className="max-w-5xl mx-auto px-4 mb-16"
      >
        <MotionFade>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {categories.map(({ name, count, desc, color }) => (
              <div
                key={name}
                className="rounded-xl border border-border bg-card p-4"
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
                    {name}
                  </span>
                  <span className="text-xs text-muted-foreground">{count}</span>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </MotionFade>
      </section>

      {/* Agents grid with filter (client island) */}
      <section
        aria-label="All agents"
        className="max-w-7xl mx-auto px-4 mb-24"
      >
        <AgentsGrid />
      </section>

      {/* CTA */}
      <section
        aria-label="Get started with agents"
        className="relative overflow-hidden py-20 px-4"
      >
        <GradientMesh />
        <MotionFade>
          <div className="max-w-2xl mx-auto text-center">
            <h2 className="text-2xl font-bold mb-4">
              All 20 agents, one platform
            </h2>
            <p className="text-muted-foreground mb-6">
              Start free with 3 agents. Upgrade to Pro to unlock all 20.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-3">
              <Link
                href="/register"
                className="inline-flex items-center gap-2 h-11 rounded-lg bg-primary px-6 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
              >
                Start free <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
              <Link
                href="/pricing"
                className="inline-flex items-center gap-2 h-11 rounded-lg border border-border px-6 text-sm font-semibold hover:bg-muted transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
              >
                See pricing
              </Link>
            </div>
          </div>
        </MotionFade>
      </section>
    </div>
  );
}
