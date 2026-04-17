import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  Bot,
  Database,
  GitBranch,
  Globe,
  Server,
  Zap,
} from "lucide-react";
import { GradientMesh } from "@/components/ui/gradient-mesh";
import { MotionFade } from "@/components/ui/motion-fade";

export const metadata: Metadata = {
  title: "About — PAE Platform",
  description: "Built by AI engineers, for AI engineers. Learn why we built PAE Platform and what powers it.",
};

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

const stack = [
  {
    icon: Bot,
    name: "Claude API",
    desc: "claude-sonnet-4-6 powers all 20 AI agents. Anthropic's safest, most capable model in production.",
    color: "text-primary",
    bg: "bg-primary/10",
  },
  {
    icon: GitBranch,
    name: "LangGraph",
    desc: "Stateful agent orchestration. Each student request flows through a typed StateGraph with full conversation history.",
    color: "text-primary",
    bg: "bg-primary/10",
  },
  {
    icon: Globe,
    name: "Next.js 16",
    desc: "App Router with Server Components for instant page loads. Tailwind CSS 4 for design-token-driven styling.",
    color: "text-[#7C3AED]",
    bg: "bg-[#7C3AED]/10",
  },
  {
    icon: Server,
    name: "FastAPI",
    desc: "Async Python backend with Pydantic v2 schemas, SQLAlchemy 2.0 async ORM, and auto-generated OpenAPI docs.",
    color: "text-[#7C3AED]",
    bg: "bg-[#7C3AED]/10",
  },
  {
    icon: Database,
    name: "PostgreSQL 16",
    desc: "12-table relational schema with UUID PKs, soft deletes, and JSONB for flexible agent metadata.",
    color: "text-primary",
    bg: "bg-primary/10",
  },
  {
    icon: Zap,
    name: "Redis 7",
    desc: "Session storage, conversation history (1-hour TTL), and Celery task queue for async agent actions.",
    color: "text-primary",
    bg: "bg-primary/10",
  },
] as const;

const values = [
  {
    title: "Depth over breadth",
    desc: "We cover fewer topics than a MOOC, but we go deep — production-grade deep. Every lesson has real code, real exercises, and a real AI agent reviewing your work.",
  },
  {
    title: "Agents, not videos",
    desc: "Passive video watching doesn't transfer to production skills. We replace the \"pause and rewind\" loop with 20 AI agents that actively coach, quiz, review, and adapt to you.",
  },
  {
    title: "Real systems, not toys",
    desc: "Every example is taken from production AI systems. You will deploy LangGraph agents, wire up RAG pipelines, handle rate limits, write evals — the actual work of an AI engineer.",
  },
] as const;

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AboutPage() {
  return (
    <div className="overflow-x-hidden">
      {/* Hero */}
      <section className="relative overflow-hidden py-24 px-4">
        <GradientMesh />
        <MotionFade>
          <div className="max-w-3xl mx-auto text-center">
            <div className="inline-flex items-center rounded-full border border-border bg-muted px-3 py-1 text-xs font-medium text-muted-foreground mb-6">
              Built by AI engineers, for AI engineers
            </div>
            <h1 className="text-[clamp(2rem,4vw,3rem)] font-bold tracking-tight mb-6">
              We built the platform we wished existed
            </h1>
            <p className="text-lg text-muted-foreground leading-relaxed max-w-2xl mx-auto">
              When we started learning GenAI engineering, the resources were either shallow
              tutorials or academic papers with no bridge to production. We built PAE Platform
              to close that gap — a place where you learn by doing, coached by AI agents
              that actually understand what you are building.
            </p>
          </div>
        </MotionFade>
      </section>

      {/* Mission */}
      <section aria-label="Mission" className="max-w-4xl mx-auto px-4 mb-24">
        <MotionFade>
          <div className="rounded-2xl border border-border bg-card p-8 md:p-12 shadow-sm">
            <div className="max-w-2xl">
              <div className="text-xs font-semibold uppercase tracking-widest text-primary mb-3">
                Our mission
              </div>
              <h2 className="text-2xl font-bold mb-4">
                Make production AI engineering accessible to every software engineer
              </h2>
              <p className="text-muted-foreground leading-relaxed">
                Not just the ones at big labs with PhDs. Not just the ones who can afford
                $5,000 bootcamps. Every engineer who understands Python and wants to build
                real AI systems deserves access to the knowledge and coaching to do it.
              </p>
            </div>
          </div>
        </MotionFade>
      </section>

      {/* Why we built this */}
      <section aria-label="Our values" className="max-w-5xl mx-auto px-4 mb-24">
        <MotionFade>
          <h2 className="text-2xl font-bold mb-8">What we believe</h2>
        </MotionFade>

        <div className="grid md:grid-cols-3 gap-6">
          {values.map(({ title, desc }, i) => (
            <MotionFade key={title} delay={i * 0.08}>
              <div className="rounded-xl border border-border bg-card p-6 h-full">
                <h3 className="text-base font-semibold mb-2">{title}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{desc}</p>
              </div>
            </MotionFade>
          ))}
        </div>
      </section>

      {/* Tech stack */}
      <section
        aria-label="Technology stack"
        className="relative overflow-hidden py-24 px-4"
      >
        <GradientMesh />
        <div className="max-w-5xl mx-auto">
          <MotionFade>
            <div className="mb-10">
              <h2 className="text-2xl font-bold mb-2">The stack is real</h2>
              <p className="text-muted-foreground">
                We use the same technologies in production that we teach. No toy frameworks —
                only battle-tested tools that companies actually ship with.
              </p>
            </div>
          </MotionFade>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {stack.map(({ icon: Icon, name, desc, color, bg }, i) => (
              <MotionFade key={name} delay={i * 0.07}>
                <div className="rounded-xl border border-border bg-card p-5 h-full">
                  <div className={`inline-flex h-9 w-9 items-center justify-center rounded-lg ${bg} mb-3`}>
                    <Icon className={`h-5 w-5 ${color}`} aria-hidden="true" />
                  </div>
                  <h3 className="text-sm font-semibold mb-1">{name}</h3>
                  <p className="text-xs text-muted-foreground leading-relaxed">{desc}</p>
                </div>
              </MotionFade>
            ))}
          </div>
        </div>
      </section>

      {/* Team */}
      <section aria-label="The team" className="max-w-3xl mx-auto px-4 py-24 text-center">
        <MotionFade>
          <h2 className="text-2xl font-bold mb-4">The team</h2>
          <p className="text-muted-foreground leading-relaxed mb-8">
            PAE Platform is built by a small team of AI engineers who have shipped production
            GenAI systems at scale. We are not academics — we are practitioners who have made
            every mistake in the book and want to help you avoid them.
          </p>
          <p className="text-sm text-muted-foreground italic">
            &ldquo;If you are building AI systems in production, you belong here.&rdquo;
          </p>
        </MotionFade>
      </section>

      {/* CTA */}
      <section
        aria-label="Get started"
        className="relative overflow-hidden py-20 px-4"
      >
        <GradientMesh />
        <MotionFade>
          <div className="max-w-xl mx-auto text-center">
            <h2 className="text-2xl font-bold mb-4">Start building today</h2>
            <p className="text-muted-foreground mb-6">
              Free forever tier, no credit card required.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-3">
              <Link
                href="/register"
                className="inline-flex items-center gap-2 h-11 rounded-lg bg-primary px-6 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
              >
                Start free <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
              <Link
                href="/courses"
                className="inline-flex items-center gap-2 h-11 rounded-lg border border-border px-6 text-sm font-semibold hover:bg-muted transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
              >
                Browse courses
              </Link>
            </div>
          </div>
        </MotionFade>
      </section>
    </div>
  );
}
